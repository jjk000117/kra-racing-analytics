from __future__ import annotations

import hashlib
import inspect
import json
import time
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]

from kra_analytics.development_evaluation import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_FOLDS,
    _fold_frames,
    verify_sealed_artifacts,
)
from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.feature_bundle_experiment import _fit_candidate, _load_development_frame
from kra_analytics.improvement_validation_contract import EXPECTED_FEATURE_HASH
from kra_analytics.logistic_structure_diagnostics import (
    VALIDATION_ACCESS_LEDGER,
    _one_dimensional,
    _pattern_summary,
    _two_dimensional,
)
from kra_analytics.m1_experiment import COMMON_HGB_SETTINGS, build_m1_pipeline
from kra_analytics.modeling import evaluate_probabilities
from kra_analytics.modeling_v2 import TARGET_COLUMN, V2FeatureContract
from kra_analytics.paths import ProjectPaths

EXPERIMENT_VERSION = "post_baseline_v2_h133_development_v1"
H133_SETTINGS = {
    **COMMON_HGB_SETTINGS,
    "max_leaf_nodes": 15,
    "l2_regularization": 1.0,
}
METRICS = (
    "macro_log_loss",
    "macro_brier",
    "micro_log_loss",
    "micro_brier",
    "calibration_intercept",
    "calibration_slope",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_h133_contract(contract: V2FeatureContract) -> dict[str, Any]:
    parameters = inspect.signature(HistGradientBoostingClassifier).parameters
    missing = sorted(set(H133_SETTINGS) - set(parameters))
    if missing:
        raise ValueError(f"H133 settings are unsupported by sklearn: {missing}")
    if len(contract.inputs) != 133 or contract.feature_hash != EXPECTED_FEATURE_HASH:
        raise ValueError("H133 does not match the promoted 133-Feature contract")
    if len(contract.categorical) != 11 or len(contract.numeric) != 122:
        raise ValueError("Unexpected H133 categorical/numeric composition")
    f1_counts = {
        "horse_recent3_race_relative_time_count",
        "horse_recent5_race_relative_time_count",
    }
    if not f1_counts.issubset(contract.zero_count):
        raise ValueError("F1 count Features are not covered by the zero-count contract")
    return {
        "feature_count": len(contract.inputs),
        "feature_hash": contract.feature_hash,
        "categorical_count": len(contract.categorical),
        "numeric_count": len(contract.numeric),
        "zero_count_count": len(contract.zero_count),
        "f1_counts_zero_imputed": sorted(f1_counts),
        "sklearn_api_compatible": True,
    }


def _metric_payload(frame: pd.DataFrame, probabilities: np.ndarray) -> dict[str, float]:
    payload = asdict(evaluate_probabilities(frame, probabilities))
    return {name: float(payload[name]) for name in METRICS}


def _fit_h133(
    *, train: pd.DataFrame, evaluation: pd.DataFrame, contract: V2FeatureContract
) -> tuple[dict[str, float], np.ndarray, float, list[str]]:
    pipeline = build_m1_pipeline(
        contract,
        max_leaf_nodes=15,
        l2_regularization=1.0,
    )
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        pipeline.fit(train.loc[:, contract.inputs], train[TARGET_COLUMN].astype(int))
    elapsed = time.perf_counter() - started
    probabilities = np.asarray(
        pipeline.predict_proba(evaluation.loc[:, contract.inputs])[:, 1], dtype=float
    )
    return (
        _metric_payload(evaluation, probabilities),
        probabilities,
        elapsed,
        [str(item.message) for item in caught],
    )


def _summaries(fold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id in ("L133", "H133"):
        selected = [row for row in fold_rows if row["model_id"] == model_id]
        summary: dict[str, Any] = {"model_id": model_id, "folds": len(selected)}
        for metric in (*METRICS, "fit_seconds"):
            values = np.asarray([row[metric] for row in selected], dtype=float)
            summary[f"{metric}_mean"] = float(values.mean())
            summary[f"{metric}_std"] = float(values.std(ddof=0))
        rows.append(summary)
    return rows


def _deltas(fold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in DEVELOPMENT_FOLDS:
        logistic = next(
            row
            for row in fold_rows
            if row["model_id"] == "L133" and row["fold_id"] == spec.fold_id
        )
        hgb = next(
            row
            for row in fold_rows
            if row["model_id"] == "H133" and row["fold_id"] == spec.fold_id
        )
        rows.append(
            {
                "fold_id": spec.fold_id,
                **{
                    f"delta_{metric}": float(hgb[metric]) - float(logistic[metric])
                    for metric in METRICS
                },
            }
        )
    return rows


def decide_h133(
    summaries: list[dict[str, Any]], deltas: list[dict[str, Any]]
) -> dict[str, Any]:
    logistic = next(row for row in summaries if row["model_id"] == "L133")
    hgb = next(row for row in summaries if row["model_id"] == "H133")
    ll_delta = float(hgb["macro_log_loss_mean"]) - float(
        logistic["macro_log_loss_mean"]
    )
    brier_delta = float(hgb["macro_brier_mean"]) - float(
        logistic["macro_brier_mean"]
    )
    ll_folds = sum(float(row["delta_macro_log_loss"]) < 0 for row in deltas)
    brier_folds = sum(float(row["delta_macro_brier"]) < 0 for row in deltas)
    if ll_delta < 0 and brier_delta < 0 and ll_folds >= 3 and brier_folds >= 3:
        judgement = "KEEP_NONLINEAR"
        reason = "both Macro means improve and each improvement repeats in at least 3/4 folds"
    elif ll_delta < 0 or brier_delta < 0 or ll_folds > 0 or brier_folds > 0:
        judgement = "MIXED"
        reason = "improvement is partial across primary metrics or temporal folds"
    else:
        judgement = "DROP_NONLINEAR"
        reason = "neither Macro mean nor temporal fold evidence supports improvement"
    return {
        "judgement": judgement,
        "reason": reason,
        "delta_macro_log_loss_mean": ll_delta,
        "delta_macro_brier_mean": brier_delta,
        "macro_log_loss_improved_folds": ll_folds,
        "macro_brier_improved_folds": brier_folds,
        "additional_hgb_tuning_allowed": False,
    }


def _diagnostic_frame(
    evaluation: pd.DataFrame,
    probabilities: np.ndarray,
    *,
    fold_id: str,
    model_id: str,
) -> pd.DataFrame:
    frame = evaluation.copy()
    frame["fold_id"] = fold_id
    frame["model_id"] = model_id
    frame["prediction"] = probabilities
    frame["target"] = frame[TARGET_COLUMN].astype(int)
    frame["residual"] = frame["target"] - frame["prediction"]
    frame["squared_error"] = frame["residual"] ** 2
    return frame


def _structural_comparison(
    logistic_oof: pd.DataFrame, hgb_oof: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    one_rows: list[dict[str, Any]] = []
    two_rows: list[dict[str, Any]] = []
    for model_id, frame in (("L133", logistic_oof), ("H133", hgb_oof)):
        one_d = _one_dimensional(frame)
        two_d = _two_dimensional(frame)
        patterns = _pattern_summary(one_d, two_d)
        for row in patterns["one_dimensional"]:
            if row["feature"] in {
                "rating",
                "carried_weight_vs_field_median_kg",
                "horse_recent5_g3f_median",
            }:
                one_rows.append({"model_id": model_id, **row})
        for row in patterns["two_dimensional"]:
            pair = (row["left_feature"], row["right_feature"])
            if pair in {
                ("gate_no", "registered_runner_count"),
                ("horse_recent5_s1f_median", "distance_m"),
            }:
                two_rows.append({"model_id": model_id, **row})

    race_rows: list[dict[str, Any]] = []
    logistic_races = logistic_oof.groupby(["fold_id", "race_id"], observed=True).agg(
        logistic_gap=("prediction", lambda value: float(value.max() - value.min()))
    ).reset_index()
    logistic_races["gap_bin"] = logistic_races.groupby("fold_id", observed=True)[
        "logistic_gap"
    ].transform(
        lambda value: np.minimum(
            np.ceil(value.rank(method="average", pct=True) * 4), 4
        ).astype(int)
    )
    for model_id, frame in (("L133", logistic_oof), ("H133", hgb_oof)):
        races = frame.groupby(["fold_id", "race_id"], observed=True).agg(
            race_brier=("squared_error", "mean"),
            predicted_sum=("prediction", "sum"),
            actual_hits=("target", "sum"),
        ).reset_index()
        races = races.merge(
            logistic_races[["fold_id", "race_id", "gap_bin"]],
            on=["fold_id", "race_id"],
            validate="one_to_one",
        )
        summary = races.groupby(["fold_id", "gap_bin"], observed=True).agg(
            races=("race_id", "size"),
            race_brier=("race_brier", "mean"),
            predicted_sum=("predicted_sum", "mean"),
            actual_hits=("actual_hits", "mean"),
        ).reset_index()
        summary.insert(0, "model_id", model_id)
        for record in summary.to_dict(orient="records"):
            race_rows.append({str(key): value for key, value in record.items()})
    return pd.DataFrame(one_rows), pd.DataFrame(two_rows), pd.DataFrame(race_rows)


def _structural_deltas(
    one_d: pd.DataFrame, two_d: pd.DataFrame, race_gap: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    one = one_d.pivot(
        index="feature", columns="model_id", values="median_within_fold_residual_range"
    ).reset_index()
    one["h133_minus_l133_residual_range"] = one["H133"] - one["L133"]

    pair_keys = ["pair_family", "left_feature", "right_feature"]
    two = two_d.pivot(
        index=pair_keys,
        columns="model_id",
        values="median_interaction_residual_spread",
    ).reset_index()
    two["h133_minus_l133_interaction_spread"] = two["H133"] - two["L133"]

    race = race_gap.pivot(
        index=["fold_id", "gap_bin"],
        columns="model_id",
        values=["race_brier", "predicted_sum"],
    )
    race.columns = [
        f"{metric}_{model.lower()}"
        for metric, model in (cast(tuple[str, str], column) for column in race.columns)
    ]
    race = race.reset_index()
    race["h133_minus_l133_race_brier"] = (
        race["race_brier_h133"] - race["race_brier_l133"]
    )
    race["h133_minus_l133_predicted_sum"] = (
        race["predicted_sum_h133"] - race["predicted_sum_l133"]
    )
    return one, two, race


def run_h133_development_experiment(
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contracts = _combined_contract(project_paths)
    contract = contracts["F1+F3"]
    contract_audit = validate_h133_contract(contract)
    frame = _load_development_frame(project_paths, contracts)
    if frame["race_date"].max() >= DEVELOPMENT_END_EXCLUSIVE:
        raise ValueError("H133 experiment crossed the Validation boundary")

    protection = json.loads(
        (project_paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    sealed_before = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_paths = {
        "validation_result": project_paths.root
        / "docs/post-baseline-v2-f1-f3-one-time-validation-result.md",
        "validation_access": project_paths.root / VALIDATION_ACCESS_LEDGER,
        "f1_f3_implementation": project_paths.root / "src/kra_analytics/feature_bundles.py",
        "m1_result": project_paths.exports
        / "modeling/m1_histgradientboosting_development_v1/result.json",
    }
    protected_before = {name: _sha256_file(path) for name, path in protected_paths.items()}
    access_before = json.loads(protected_paths["validation_access"].read_text(encoding="utf-8"))
    if access_before.get("access_count") != 1:
        raise ValueError("Validation access ledger is not at the protected value 1")

    fold_rows: list[dict[str, Any]] = []
    fold_context: list[dict[str, Any]] = []
    logistic_parts: list[pd.DataFrame] = []
    hgb_parts: list[pd.DataFrame] = []
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
        logistic_metrics, logistic_p, logistic_seconds, logistic_warnings = _fit_candidate(
            train=train, evaluation=evaluation, contract=contract
        )
        hgb_metrics, hgb_p, hgb_seconds, hgb_warnings = _fit_h133(
            train=train, evaluation=evaluation, contract=contract
        )
        for model_id, metrics, seconds, warning_messages in (
            ("L133", logistic_metrics, logistic_seconds, logistic_warnings),
            ("H133", hgb_metrics, hgb_seconds, hgb_warnings),
        ):
            fold_rows.append(
                {
                    "model_id": model_id,
                    "fold_id": spec.fold_id,
                    **metrics,
                    "fit_seconds": seconds,
                    "warning_count": len(warning_messages),
                    "warning_messages": warning_messages,
                }
            )
        logistic_parts.append(
            _diagnostic_frame(evaluation, logistic_p, fold_id=spec.fold_id, model_id="L133")
        )
        hgb_parts.append(
            _diagnostic_frame(evaluation, hgb_p, fold_id=spec.fold_id, model_id="H133")
        )

    summaries = _summaries(fold_rows)
    deltas = _deltas(fold_rows)
    decision = decide_h133(summaries, deltas)
    one_d, two_d, race_gap = _structural_comparison(
        pd.concat(logistic_parts, ignore_index=True),
        pd.concat(hgb_parts, ignore_index=True),
    )
    one_delta, two_delta, race_delta = _structural_deltas(one_d, two_d, race_gap)

    sealed_after = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_after = {name: _sha256_file(path) for name, path in protected_paths.items()}
    access_after = json.loads(protected_paths["validation_access"].read_text(encoding="utf-8"))
    if sealed_before != sealed_after or protected_before != protected_after:
        raise ValueError("A sealed or protected artifact changed during H133")
    if access_after.get("access_count") != 1:
        raise ValueError("Validation access count changed during H133")

    output = project_paths.exports / f"modeling/{EXPERIMENT_VERSION}"
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(fold_rows).drop(columns="warning_messages").to_csv(
        output / "fold_metrics.csv", index=False
    )
    pd.DataFrame(summaries).to_csv(output / "summary_metrics.csv", index=False)
    pd.DataFrame(deltas).to_csv(output / "fold_deltas.csv", index=False)
    one_d.to_csv(output / "structural_one_dimensional.csv", index=False)
    two_d.to_csv(output / "structural_interactions.csv", index=False)
    race_gap.to_csv(output / "structural_race_gap.csv", index=False)
    one_delta.to_csv(output / "structural_one_dimensional_deltas.csv", index=False)
    two_delta.to_csv(output / "structural_interaction_deltas.csv", index=False)
    race_delta.to_csv(output / "structural_race_gap_deltas.csv", index=False)

    registry = {
        "experiment_version": EXPERIMENT_VERSION,
        "question": (
            "Does conservative HGB improve repeatedly over Logistic "
            "on the same 133 Features?"
        ),
        "development_window": ["2023-01-01", "2024-06-30"],
        "feature_contract": contract_audit,
        "models": {
            "L133": {"family": "LogisticRegression", "contract": "promoted_133_raw"},
            "H133": {
                "family": "HistGradientBoostingClassifier",
                **H133_SETTINGS,
                "categorical_preprocessing": "fold-train OrdinalEncoder + native categorical mask",
                "numeric_preprocessing": "fold-train median; zero-count constant 0; no scaling",
            },
        },
        "selection_rule": (
            "KEEP only if both Macro means improve and each improves in at least 3/4 folds; "
            "otherwise MIXED or DROP; no tuning"
        ),
        "fold_metrics": fold_rows,
        "summary_metrics": summaries,
        "fold_deltas": deltas,
        "decision": decision,
        "validation_access_count": 1,
    }
    (output / "experiment_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = {
        **registry,
        "development_rows": len(frame),
        "development_races": int(frame["race_id"].nunique()),
        "oof_rows": sum(int(item["evaluation_rows"]) for item in fold_context),
        "oof_races": sum(int(item["evaluation_races"]) for item in fold_context),
        "fold_context": fold_context,
        "validation_access_count_before": 1,
        "validation_access_count_after": 1,
        "validation_or_later_rows_loaded": False,
        "max_loaded_race_date": str(frame["race_date"].max()),
        "sealed_artifacts_unchanged": True,
        "protected_artifacts_unchanged": True,
        "sealed_artifact_hashes": sealed_after,
        "protected_artifact_hashes": protected_after,
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
