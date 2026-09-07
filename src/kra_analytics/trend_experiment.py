from __future__ import annotations

import hashlib
import json
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.database import connect_database
from kra_analytics.development_evaluation import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_FOLDS,
    DEVELOPMENT_START,
    _fold_frames,
    verify_sealed_artifacts,
)
from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.feature_bundle_experiment import METRICS, _metric_payload
from kra_analytics.logistic_structure_diagnostics import VALIDATION_ACCESS_LEDGER
from kra_analytics.modeling_v2 import (
    TARGET_COLUMN,
    V2FeatureContract,
    build_v2_pipeline,
)
from kra_analytics.paths import ProjectPaths
from kra_analytics.trend_features import TREND_FEATURES, TREND_TABLE

EXPERIMENT_VERSION = "post_baseline_v2_t1_development_v1"
CANDIDATES = ("L133", "LT1")
EXPECTED_L133_HASH = "18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182"
REFERENCE_L133_RESULT = (
    "data/exports/modeling/post_baseline_v2_f1_f3_combination_development_v1/result.json"
)
REFERENCE_ROUNDED_MACRO_LOG_LOSS = 0.527685
REFERENCE_ROUNDED_MACRO_BRIER = 0.175744
ROUNDED_REFERENCE_TOLERANCE = 5e-7
EXACT_REPRODUCTION_TOLERANCE = 1e-12


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feature_hash(features: tuple[str, ...]) -> str:
    return hashlib.sha256(("\n".join(features) + "\n").encode()).hexdigest()


def _contracts(paths: ProjectPaths) -> dict[str, V2FeatureContract]:
    l133 = _combined_contract(paths)["F1+F3"]
    if len(l133.inputs) != 133 or l133.feature_hash != EXPECTED_L133_HASH:
        raise ValueError("The protected L133 Feature contract does not match its sealed hash")
    additions = tuple(TREND_FEATURES)
    if set(l133.inputs).intersection(additions):
        raise ValueError("T1 must add four new, non-duplicate Feature names")
    inputs = l133.inputs + additions
    lt1 = V2FeatureContract(
        inputs=inputs,
        categorical=l133.categorical,
        numeric=l133.numeric + additions,
        zero_count=l133.zero_count,
        feature_hash=_feature_hash(inputs),
    )
    if len(lt1.inputs) != 137 or len(set(lt1.inputs)) != 137:
        raise ValueError("LT1 must contain exactly 137 unique Features")
    return {"L133": l133, "LT1": lt1}


def _load_development_frame(
    paths: ProjectPaths, contracts: dict[str, V2FeatureContract]
) -> pd.DataFrame:
    columns = list(dict.fromkeys((*contracts["LT1"].inputs, TARGET_COLUMN)))
    query_columns = ", ".join(["race_id", "horse_id", "race_date", *columns])
    with connect_database(paths=paths, read_only=True) as connection:
        frame = connection.execute(
            f"""
            SELECT {query_columns}
            FROM {TREND_TABLE}
            WHERE race_date >= ? AND race_date < ?
            ORDER BY race_date, race_id, horse_id
            """,
            [DEVELOPMENT_START, DEVELOPMENT_END_EXCLUSIVE],
        ).fetchdf()
    frame["race_date"] = pd.to_datetime(frame["race_date"]).dt.date
    if frame.empty:
        raise ValueError("The development-only T1 Snapshot is empty")
    if frame["race_date"].min() < DEVELOPMENT_START:
        raise ValueError("Rows before the development boundary were loaded")
    if frame["race_date"].max() >= DEVELOPMENT_END_EXCLUSIVE:
        raise ValueError("Rows at or after the locked Validation boundary were loaded")
    if frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate runner business keys exist in the T1 Snapshot")
    if set(frame[TARGET_COLUMN].dropna().astype(int).unique()) - {0, 1}:
        raise ValueError("The target must be binary")
    return frame


def _fit_candidate(
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    contract: V2FeatureContract,
) -> tuple[dict[str, float], Any, float, list[str]]:
    pipeline = build_v2_pipeline(contract)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.perf_counter()
        pipeline.fit(train[list(contract.inputs)], train[TARGET_COLUMN].astype(int))
        fit_seconds = time.perf_counter() - started
    probabilities = pipeline.predict_proba(evaluation[list(contract.inputs)])[:, 1]
    return (
        _metric_payload(evaluation, probabilities),
        pipeline,
        fit_seconds,
        [str(item.message) for item in caught],
    )


def _t1_preprocessing_rows(
    fold_id: str,
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    pipeline: Any,
    contract: V2FeatureContract,
) -> list[dict[str, Any]]:
    numeric_features = [name for name in contract.numeric if name not in contract.zero_count]
    imputer = (
        pipeline.named_steps["preprocessor"].named_transformers_["numeric"].named_steps["imputer"]
    )
    statistics = dict(zip(numeric_features, imputer.statistics_, strict=True))
    results: list[dict[str, Any]] = []
    for feature in TREND_FEATURES:
        train_median = float(train[feature].median())
        fitted_value = float(statistics[feature])
        if not np.isclose(train_median, fitted_value, rtol=0.0, atol=1e-12):
            raise ValueError(f"Fold-train median was not used for {feature} in {fold_id}")
        results.append(
            {
                "fold_id": fold_id,
                "feature_name": feature,
                "train_rows": len(train),
                "train_non_null_count": int(train[feature].notna().sum()),
                "train_non_null_rate": float(train[feature].notna().mean()),
                "evaluation_rows": len(evaluation),
                "evaluation_non_null_count": int(evaluation[feature].notna().sum()),
                "evaluation_non_null_rate": float(evaluation[feature].notna().mean()),
                "evaluation_missing_count": int(evaluation[feature].isna().sum()),
                "train_median": train_median,
                "fitted_imputation_value": fitted_value,
                "fit_scope": "fold_train_only",
                "scaling": "StandardScaler_after_train_median_imputation",
            }
        )
    return results


def _t1_coefficient_rows(fold_id: str, pipeline: Any) -> list[dict[str, Any]]:
    feature_names = pipeline.named_steps["preprocessor"].get_feature_names_out()
    coefficients = pipeline.named_steps["model"].coef_[0]
    coefficient_map = dict(zip(feature_names, coefficients, strict=True))
    results: list[dict[str, Any]] = []
    for feature in TREND_FEATURES:
        coefficient = float(coefficient_map[f"numeric__{feature}"])
        results.append(
            {
                "fold_id": fold_id,
                "feature_name": feature,
                "standardized_coefficient": coefficient,
                "sign": "positive"
                if coefficient > 0
                else "negative"
                if coefficient < 0
                else "zero",
            }
        )
    return results


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        selected = [row for row in rows if row["experiment_id"] == candidate]
        summary: dict[str, Any] = {"experiment_id": candidate, "folds": len(selected)}
        for metric in (*METRICS, "fit_seconds"):
            values = np.asarray([row[metric] for row in selected], dtype=float)
            summary[f"{metric}_mean"] = float(values.mean())
            summary[f"{metric}_std"] = float(values.std(ddof=0))
        results.append(summary)
    return results


def _deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for fold_id in (spec.fold_id for spec in DEVELOPMENT_FOLDS):
        l133 = next(
            row for row in rows if row["experiment_id"] == "L133" and row["fold_id"] == fold_id
        )
        lt1 = next(
            row for row in rows if row["experiment_id"] == "LT1" and row["fold_id"] == fold_id
        )
        result: dict[str, Any] = {"fold_id": fold_id, "candidate": "LT1", "reference": "L133"}
        for metric in METRICS:
            delta = float(lt1[metric]) - float(l133[metric])
            result[f"delta_{metric}"] = delta
            result[f"relative_delta_{metric}"] = (
                delta / float(l133[metric]) if float(l133[metric]) != 0 else None
            )
        results.append(result)
    return results


def _coefficient_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for feature in TREND_FEATURES:
        values = np.asarray(
            [row["standardized_coefficient"] for row in rows if row["feature_name"] == feature],
            dtype=float,
        )
        results.append(
            {
                "feature_name": feature,
                "coefficient_mean": float(values.mean()),
                "coefficient_std": float(values.std(ddof=0)),
                "coefficient_min": float(values.min()),
                "coefficient_max": float(values.max()),
                "positive_folds": int((values > 0).sum()),
                "negative_folds": int((values < 0).sum()),
                "zero_folds": int((values == 0).sum()),
            }
        )
    return results


def _decision(summaries: list[dict[str, Any]], deltas: list[dict[str, Any]]) -> dict[str, Any]:
    l133 = next(row for row in summaries if row["experiment_id"] == "L133")
    lt1 = next(row for row in summaries if row["experiment_id"] == "LT1")
    ll_delta = float(lt1["macro_log_loss_mean"]) - float(l133["macro_log_loss_mean"])
    brier_delta = float(lt1["macro_brier_mean"]) - float(l133["macro_brier_mean"])
    ll_improved = sum(float(row["delta_macro_log_loss"]) < 0 for row in deltas)
    brier_improved = sum(float(row["delta_macro_brier"]) < 0 for row in deltas)
    simultaneous = sum(
        float(row["delta_macro_log_loss"]) < 0 and float(row["delta_macro_brier"]) < 0
        for row in deltas
    )
    keep = (
        ll_delta < 0
        and brier_delta < 0
        and ll_improved >= 3
        and brier_improved >= 3
        and simultaneous >= 3
    )
    return {
        "judgement": "KEEP_T1" if keep else "DROP_T1",
        "delta_macro_log_loss_mean": ll_delta,
        "relative_delta_macro_log_loss_mean": ll_delta / float(l133["macro_log_loss_mean"]),
        "delta_macro_brier_mean": brier_delta,
        "relative_delta_macro_brier_mean": brier_delta / float(l133["macro_brier_mean"]),
        "macro_log_loss_improved_folds": ll_improved,
        "macro_brier_improved_folds": brier_improved,
        "both_primary_metrics_improved_folds": simultaneous,
        "rule": (
            "KEEP only when both primary means improve and both improve together "
            "in at least 3/4 folds"
        ),
        "calibration_role": "secondary diagnostic; it does not override the two primary losses",
    }


def _reference_summary(paths: ProjectPaths) -> dict[str, Any]:
    payload = json.loads((paths.root / REFERENCE_L133_RESULT).read_text(encoding="utf-8"))
    return next(row["summary"] for row in payload["candidates"] if row["experiment_id"] == "F1+F3")


def run_t1_development_experiment(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contracts = _contracts(project_paths)
    protection = json.loads(
        (project_paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    sealed_before = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_paths = {
        "l133_reference_result": project_paths.root / REFERENCE_L133_RESULT,
        "t1_registry": project_paths.root
        / "docs/post-baseline-v2-historical-trend-feature-registry.csv",
        "t1_design": project_paths.root
        / "docs/post-baseline-v2-historical-trend-feature-design.md",
        "t1_implementation_audit": project_paths.root
        / "docs/post-baseline-v2-historical-trend-feature-implementation-audit.md",
        "trend_feature_code": project_paths.root / "src/kra_analytics/trend_features.py",
        "validation_ledger": project_paths.root / VALIDATION_ACCESS_LEDGER,
        "m1_result": project_paths.exports
        / "modeling/m1_histgradientboosting_development_v1/result.json",
        "h133_result": project_paths.exports
        / "modeling/post_baseline_v2_h133_development_v1/result.json",
        "ra1_result": project_paths.exports
        / "modeling/post_baseline_v2_ra1_development_v1/result.json",
    }
    protected_before = {name: _sha256_file(path) for name, path in protected_paths.items()}
    ledger_before = json.loads(protected_paths["validation_ledger"].read_text(encoding="utf-8"))
    frame = _load_development_frame(project_paths, contracts)

    rows: list[dict[str, Any]] = []
    preprocessing_rows: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []
    fold_context: list[dict[str, Any]] = []
    for spec in DEVELOPMENT_FOLDS:
        train, evaluation = _fold_frames(frame, spec)
        fold_context.append(
            {
                "fold_id": spec.fold_id,
                "train_start": str(train["race_date"].min()),
                "train_end": str(train["race_date"].max()),
                "evaluation_start": str(evaluation["race_date"].min()),
                "evaluation_end": str(evaluation["race_date"].max()),
                "train_rows": len(train),
                "train_races": int(train["race_id"].nunique()),
                "evaluation_rows": len(evaluation),
                "evaluation_races": int(evaluation["race_id"].nunique()),
                "strict_temporal_ordering": bool(
                    train["race_date"].max() < evaluation["race_date"].min()
                ),
                "preprocessing_fit_scope": "fold_train_only",
            }
        )
        for candidate in CANDIDATES:
            metrics, pipeline, fit_seconds, warning_messages = _fit_candidate(
                train, evaluation, contracts[candidate]
            )
            rows.append(
                {
                    "experiment_id": candidate,
                    "fold_id": spec.fold_id,
                    **metrics,
                    "fit_seconds": fit_seconds,
                    "warning_count": len(warning_messages),
                    "warning_messages": " | ".join(warning_messages),
                }
            )
            if candidate == "LT1":
                preprocessing_rows.extend(
                    _t1_preprocessing_rows(
                        spec.fold_id, train, evaluation, pipeline, contracts[candidate]
                    )
                )
                coefficient_rows.extend(_t1_coefficient_rows(spec.fold_id, pipeline))

    summaries = _summaries(rows)
    deltas = _deltas(rows)
    coefficient_summary = _coefficient_summary(coefficient_rows)
    reference = _reference_summary(project_paths)
    reproduced = next(row for row in summaries if row["experiment_id"] == "L133")
    exact_deltas = {
        "macro_log_loss": float(reproduced["macro_log_loss_mean"])
        - float(reference["macro_log_loss_mean"]),
        "macro_brier": float(reproduced["macro_brier_mean"]) - float(reference["macro_brier_mean"]),
    }
    rounded_ok = (
        abs(float(reproduced["macro_log_loss_mean"]) - REFERENCE_ROUNDED_MACRO_LOG_LOSS)
        <= ROUNDED_REFERENCE_TOLERANCE
        and abs(float(reproduced["macro_brier_mean"]) - REFERENCE_ROUNDED_MACRO_BRIER)
        <= ROUNDED_REFERENCE_TOLERANCE
    )
    exact_ok = all(abs(value) <= EXACT_REPRODUCTION_TOLERANCE for value in exact_deltas.values())
    if not rounded_ok or not exact_ok:
        raise ValueError(f"L133 reference reproduction failed: {exact_deltas}")

    decision = _decision(summaries, deltas)
    sealed_after = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_after = {name: _sha256_file(path) for name, path in protected_paths.items()}
    ledger_after = json.loads(protected_paths["validation_ledger"].read_text(encoding="utf-8"))
    if (
        sealed_before != sealed_after
        or protected_before != protected_after
        or ledger_before != ledger_after
    ):
        raise ValueError(
            "A protected artifact or the Validation ledger changed during the T1 experiment"
        )

    output = project_paths.exports / f"modeling/{EXPERIMENT_VERSION}"
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output / "fold_metrics.csv", index=False)
    pd.DataFrame(summaries).to_csv(output / "summary_metrics.csv", index=False)
    pd.DataFrame(deltas).to_csv(output / "fold_deltas.csv", index=False)
    pd.DataFrame(preprocessing_rows).to_csv(output / "t1_preprocessing_audit.csv", index=False)
    pd.DataFrame(coefficient_rows).to_csv(output / "t1_coefficients.csv", index=False)
    pd.DataFrame(coefficient_summary).to_csv(output / "t1_coefficient_summary.csv", index=False)
    registry = {
        "experiment_version": EXPERIMENT_VERSION,
        "development_window": [str(DEVELOPMENT_START), str(DEVELOPMENT_END_EXCLUSIVE)],
        "probability_procedure": "raw_logistic",
        "validation_access_ledger_unchanged": True,
        "candidates": [
            {
                "experiment_id": name,
                "feature_count": len(contracts[name].inputs),
                "feature_hash": contracts[name].feature_hash,
                "features": list(contracts[name].inputs),
                "summary": next(row for row in summaries if row["experiment_id"] == name),
            }
            for name in CANDIDATES
        ],
        "decision": decision,
    }
    (output / "experiment_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = {
        **registry,
        "development_rows": len(frame),
        "development_races": int(frame["race_id"].nunique()),
        "fold_context": fold_context,
        "fold_metrics": rows,
        "fold_deltas": deltas,
        "t1_preprocessing_audit": preprocessing_rows,
        "t1_coefficients": coefficient_rows,
        "t1_coefficient_summary": coefficient_summary,
        "l133_reference_reproduction": {
            "rounded_tolerance": ROUNDED_REFERENCE_TOLERANCE,
            "exact_tolerance": EXACT_REPRODUCTION_TOLERANCE,
            "reference_summary": reference,
            "reproduced_summary": reproduced,
            "exact_deltas": exact_deltas,
            "passed": True,
        },
        "validation_or_later_rows_loaded": False,
        "protected_artifacts_unchanged": True,
        "sealed_artifact_hashes": sealed_after,
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
