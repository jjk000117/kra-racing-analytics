from __future__ import annotations

import hashlib
import json
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.aptitude_features import APTITUDE_FEATURES, CANDIDATE_TABLE
from kra_analytics.development_evaluation import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_FOLDS,
    DEVELOPMENT_START,
    _fold_frames,
)
from kra_analytics.experiment_database import (
    connect_experiment_database_read_only,
    resolve_experiment_database_paths,
)
from kra_analytics.feature_bundle_experiment import METRICS, _metric_payload
from kra_analytics.modeling_v2 import TARGET_COLUMN, V2FeatureContract, build_v2_pipeline
from kra_analytics.paths import ProjectPaths
from kra_analytics.trend_experiment import _contracts as trend_contracts

EXPERIMENT_VERSION = "post_baseline_v2_aptitude_a1_development_v1"
CANDIDATES = ("LT1", "LA1")
EXPECTED_LT1_HASH = "1dcf5f5a630d67f216fa6dc27932d2c6532ec0a50af6360b7521917682f802e8"
EXPECTED_A1_HASH = "9f15c6caa05da889780ac29de73ec11441e470fba759925c00af936c3c5773d2"
REFERENCE_RESULT = "data/exports/modeling/post_baseline_v2_t1_development_v1/result.json"
COUNT_FEATURES = (
    "horse_same_grade_start_count",
    "horse_same_track_condition_start_count",
    "horse_same_distance_race_time_percentile_count",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feature_hash(features: tuple[str, ...]) -> str:
    return hashlib.sha256(("\n".join(features) + "\n").encode()).hexdigest()


def _contracts(paths: ProjectPaths) -> dict[str, V2FeatureContract]:
    lt1 = trend_contracts(paths)["LT1"]
    a1_hash = _feature_hash(APTITUDE_FEATURES)
    if len(lt1.inputs) != 137 or lt1.feature_hash != EXPECTED_LT1_HASH:
        raise ValueError("Protected LT1 contract mismatch")
    if a1_hash != EXPECTED_A1_HASH or set(lt1.inputs) & set(APTITUDE_FEATURES):
        raise ValueError("Sealed A1 contract mismatch")
    inputs = lt1.inputs + APTITUDE_FEATURES
    la1 = V2FeatureContract(
        inputs=inputs,
        categorical=lt1.categorical,
        numeric=lt1.numeric + APTITUDE_FEATURES,
        zero_count=lt1.zero_count + COUNT_FEATURES,
        feature_hash=_feature_hash(inputs),
    )
    if len(inputs) != len(set(inputs)) or len(inputs) != 144:
        raise ValueError("LA1 must contain 144 unique Features")
    return {"LT1": lt1, "LA1": la1}


def _load_frame(paths: ProjectPaths, contract: V2FeatureContract) -> pd.DataFrame:
    databases = resolve_experiment_database_paths(paths=paths)
    columns = list(
        dict.fromkeys(("race_id", "horse_id", "race_date", *contract.inputs, TARGET_COLUMN))
    )
    with connect_experiment_database_read_only(database_paths=databases, paths=paths) as connection:
        frame = connection.execute(
            f"SELECT {', '.join(columns)} FROM {CANDIDATE_TABLE} "
            "WHERE race_date>=? AND race_date<? ORDER BY race_date,race_id,horse_id",
            [DEVELOPMENT_START, DEVELOPMENT_END_EXCLUSIVE],
        ).fetchdf()
    frame["race_date"] = pd.to_datetime(frame["race_date"]).dt.date
    if len(frame) != 28_392 or frame["race_id"].nunique() != 2_675:
        raise ValueError("Development population mismatch")
    if frame["race_date"].max() >= DEVELOPMENT_END_EXCLUSIVE:
        raise ValueError("Validation boundary violation")
    if frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate runner business keys")
    return frame


def _fit(
    train: pd.DataFrame, evaluation: pd.DataFrame, contract: V2FeatureContract
) -> tuple[dict[str, float], Any, float, list[str]]:
    pipeline = build_v2_pipeline(contract)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.perf_counter()
        pipeline.fit(train[list(contract.inputs)], train[TARGET_COLUMN].astype(int))
        elapsed = time.perf_counter() - started
    probability = pipeline.predict_proba(evaluation[list(contract.inputs)])[:, 1]
    return (
        _metric_payload(evaluation, probability),
        pipeline,
        elapsed,
        [str(item.message) for item in caught],
    )


def _preprocessing(
    fold_id: str, train: pd.DataFrame, evaluation: pd.DataFrame, pipeline: Any
) -> list[dict[str, Any]]:
    preprocessor = pipeline.named_steps["preprocessor"]
    numeric_names = list(preprocessor.transformers_[1][2])
    statistics = dict(
        zip(
            numeric_names,
            preprocessor.named_transformers_["numeric"].named_steps["imputer"].statistics_,
            strict=True,
        )
    )
    rows: list[dict[str, Any]] = []
    for feature in APTITUDE_FEATURES:
        is_count = feature in COUNT_FEATURES
        train_numeric = pd.to_numeric(train[feature], errors="coerce").astype("float64")
        fitted = 0.0 if is_count else float(statistics[feature])
        expected = 0.0 if is_count else float(train_numeric.median())
        if not np.isclose(fitted, expected, rtol=0, atol=1e-12):
            raise ValueError(f"Train-only imputation mismatch: {fold_id}/{feature}")
        rows.append(
            {
                "fold_id": fold_id,
                "feature_name": feature,
                "train_non_null_rate": float(train[feature].notna().mean()),
                "evaluation_non_null_rate": float(evaluation[feature].notna().mean()),
                "train_median": float(train_numeric.median()),
                "fitted_imputation_value": fitted,
                "imputation": "constant_zero" if is_count else "fold_train_median",
            }
        )
    return rows


def _coefficients(fold_id: str, pipeline: Any) -> list[dict[str, Any]]:
    names = pipeline.named_steps["preprocessor"].get_feature_names_out()
    mapping = dict(zip(names, pipeline.named_steps["model"].coef_[0], strict=True))
    rows = []
    for feature in APTITUDE_FEATURES:
        prefix = "zero_count" if feature in COUNT_FEATURES else "numeric"
        value = float(mapping[f"{prefix}__{feature}"])
        rows.append(
            {
                "fold_id": fold_id,
                "feature_name": feature,
                "standardized_coefficient": value,
                "sign": "positive" if value > 0 else "negative" if value < 0 else "zero",
            }
        )
    return rows


def _summaries(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for name in CANDIDATES:
        selected = [row for row in metrics if row["experiment_id"] == name]
        summary: dict[str, Any] = {"experiment_id": name, "folds": len(selected)}
        for metric in (*METRICS, "fit_seconds"):
            values = np.asarray([row[metric] for row in selected], dtype=float)
            summary[f"{metric}_mean"] = float(values.mean())
            summary[f"{metric}_std"] = float(values.std(ddof=0))
        results.append(summary)
    return results


def _deltas(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for fold in DEVELOPMENT_FOLDS:
        lt1 = next(
            row
            for row in metrics
            if row["experiment_id"] == "LT1" and row["fold_id"] == fold.fold_id
        )
        la1 = next(
            row
            for row in metrics
            if row["experiment_id"] == "LA1" and row["fold_id"] == fold.fold_id
        )
        result: dict[str, Any] = {"fold_id": fold.fold_id}
        for metric in METRICS:
            delta = float(la1[metric]) - float(lt1[metric])
            result[f"delta_{metric}"] = delta
            result[f"relative_delta_{metric}"] = delta / float(lt1[metric])
        results.append(result)
    return results


def _decision(summaries: list[dict[str, Any]], deltas: list[dict[str, Any]]) -> dict[str, Any]:
    lt1 = next(row for row in summaries if row["experiment_id"] == "LT1")
    la1 = next(row for row in summaries if row["experiment_id"] == "LA1")
    ll = float(la1["macro_log_loss_mean"]) - float(lt1["macro_log_loss_mean"])
    br = float(la1["macro_brier_mean"]) - float(lt1["macro_brier_mean"])
    ll_folds = sum(float(row["delta_macro_log_loss"]) < 0 for row in deltas)
    br_folds = sum(float(row["delta_macro_brier"]) < 0 for row in deltas)
    both = sum(
        float(row["delta_macro_log_loss"]) < 0 and float(row["delta_macro_brier"]) < 0
        for row in deltas
    )
    keep = ll < 0 and br < 0 and ll_folds >= 3 and br_folds >= 3 and both >= 3
    return {
        "judgement": "KEEP_A1" if keep else "DROP_A1",
        "delta_macro_log_loss_mean": ll,
        "relative_delta_macro_log_loss_mean": ll / float(lt1["macro_log_loss_mean"]),
        "delta_macro_brier_mean": br,
        "relative_delta_macro_brier_mean": br / float(lt1["macro_brier_mean"]),
        "macro_log_loss_improved_folds": ll_folds,
        "macro_brier_improved_folds": br_folds,
        "both_primary_metrics_improved_folds": both,
    }


def run_a1_development_experiment(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project = paths or ProjectPaths.from_root()
    databases = resolve_experiment_database_paths(paths=project)
    contracts = _contracts(project)
    common = databases.source.parents[2]
    protected = {
        "common_database": databases.source,
        "a1_registry": project.root / "docs/post-baseline-v2-aptitude-feature-registry.csv",
        "a1_code": project.root / "src/kra_analytics/aptitude_features.py",
        "t1_result": common / REFERENCE_RESULT,
        "validation_contract": project.root
        / "docs/post-baseline-v2-improvement-validation-contract.json",
        "validation_ledger": common
        / (
            "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/"
            "validation_access.json"
        ),
        "validation_result": common
        / "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/result.json",
        "h133_result": common
        / "data/exports/modeling/post_baseline_v2_h133_development_v1/result.json",
        "ra1_result": common
        / "data/exports/modeling/post_baseline_v2_ra1_development_v1/result.json",
    }
    before = {name: _sha(path) for name, path in protected.items()}
    frame = _load_frame(project, contracts["LA1"])
    metrics: list[dict[str, Any]] = []
    preprocessing: list[dict[str, Any]] = []
    coefficients: list[dict[str, Any]] = []
    contexts: list[dict[str, Any]] = []
    for spec in DEVELOPMENT_FOLDS:
        train, evaluation = _fold_frames(frame, spec)
        overlap = len(set(train["race_id"]) & set(evaluation["race_id"]))
        ordered = bool(train["race_date"].max() < evaluation["race_date"].min())
        if overlap or not ordered:
            raise ValueError(f"Temporal contract violation: {spec.fold_id}")
        contexts.append(
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
                "strict_temporal_ordering": ordered,
                "race_overlap": overlap,
            }
        )
        for name in CANDIDATES:
            values, pipeline, elapsed, caught = _fit(train, evaluation, contracts[name])
            metrics.append(
                {
                    "experiment_id": name,
                    "fold_id": spec.fold_id,
                    **values,
                    "fit_seconds": elapsed,
                    "warning_count": len(caught),
                    "warning_messages": " | ".join(caught),
                }
            )
            if name == "LA1":
                preprocessing.extend(_preprocessing(spec.fold_id, train, evaluation, pipeline))
                coefficients.extend(_coefficients(spec.fold_id, pipeline))
    summaries = _summaries(metrics)
    deltas = _deltas(metrics)
    reference_payload = json.loads((common / REFERENCE_RESULT).read_text(encoding="utf-8"))
    reference = next(
        item["summary"]
        for item in reference_payload["candidates"]
        if item["experiment_id"] == "LT1"
    )
    reproduced = next(item for item in summaries if item["experiment_id"] == "LT1")
    reproduction = {
        metric: float(reproduced[f"{metric}_mean"]) - float(reference[f"{metric}_mean"])
        for metric in METRICS
    }
    if any(abs(value) > 1e-12 for value in reproduction.values()):
        raise ValueError(f"LT1 reproduction failed: {reproduction}")
    coefficient_summary = []
    for feature in APTITUDE_FEATURES:
        coefficient_values = np.asarray(
            [
                row["standardized_coefficient"]
                for row in coefficients
                if row["feature_name"] == feature
            ]
        )
        coefficient_summary.append(
            {
                "feature_name": feature,
                "mean": float(coefficient_values.mean()),
                "std": float(coefficient_values.std(ddof=0)),
                "minimum": float(coefficient_values.min()),
                "maximum": float(coefficient_values.max()),
                "positive_folds": int((coefficient_values > 0).sum()),
                "negative_folds": int((coefficient_values < 0).sum()),
            }
        )
    after = {name: _sha(path) for name, path in protected.items()}
    if before != after:
        raise ValueError("Protected artifact changed")
    result = {
        "experiment_version": EXPERIMENT_VERSION,
        "development_rows": len(frame),
        "development_races": int(frame["race_id"].nunique()),
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
        "fold_context": contexts,
        "fold_metrics": metrics,
        "fold_deltas": deltas,
        "a1_preprocessing_audit": preprocessing,
        "a1_coefficients": coefficients,
        "a1_coefficient_summary": coefficient_summary,
        "lt1_reference_reproduction": {"tolerance": 1e-12, "deltas": reproduction, "passed": True},
        "decision": _decision(summaries, deltas),
        "validation_or_later_rows_loaded": False,
        "protected_artifacts_unchanged": True,
        "protected_sha256": after,
    }
    output = project.exports / f"modeling/{EXPERIMENT_VERSION}"
    output.mkdir(parents=True, exist_ok=True)
    for filename, rows in (
        ("fold_metrics.csv", metrics),
        ("summary_metrics.csv", summaries),
        ("fold_deltas.csv", deltas),
        ("a1_preprocessing_audit.csv", preprocessing),
        ("a1_coefficients.csv", coefficients),
        ("a1_coefficient_summary.csv", coefficient_summary),
    ):
        pd.DataFrame(rows).to_csv(output / filename, index=False)
    (output / "experiment_registry.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
