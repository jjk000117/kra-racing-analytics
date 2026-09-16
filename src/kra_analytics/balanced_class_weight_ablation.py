from __future__ import annotations

import json
import time
import warnings
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS, _fold_frames
from kra_analytics.experiment_database import resolve_experiment_database_paths
from kra_analytics.modeling import evaluate_probabilities, fit_sigmoid_calibrator
from kra_analytics.modeling_v2 import TARGET_COLUMN, V2FeatureContract, build_v2_pipeline
from kra_analytics.paths import ProjectPaths
from kra_analytics.prize_bonus_ablation import _sha256_file
from kra_analytics.race_aware_experiment import ranking_metrics
from kra_analytics.relative_experiment import _load_frame
from kra_analytics.saturated_recent10_count_ablation import (
    CHALLENGER_NAME as SOURCE_CONTRACT_NAME,
)
from kra_analytics.saturated_recent10_count_ablation import (
    candidate_contracts as prior_candidate_contracts,
)

EXPERIMENT_VERSION = "plc_balanced_class_weight_development_ablation_v1"
CONTRACT_PATH = "docs/plc-balanced-class-weight-development-ablation-contract.json"
REFERENCE_RESULT = (
    "data/exports/modeling/"
    "plc_saturated_recent10_count_sequential_ablation_v1/result.json"
)
OUTPUT_DIRECTORY = f"data/exports/modeling/{EXPERIMENT_VERSION}"
FEATURE_HASH = "7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e"
BASELINE_NAME = "UNWEIGHTED_137_SIGMOID"
CHALLENGER_NAME = "BALANCED_137_SIGMOID"
CANDIDATE_CLASS_WEIGHTS: dict[str, str | None] = {
    BASELINE_NAME: None,
    CHALLENGER_NAME: "balanced",
}
PRIMARY = ("calibrated_macro_log_loss", "calibrated_macro_brier")
CALIBRATED_SECONDARY = (
    "calibrated_micro_log_loss",
    "calibrated_micro_brier",
    "calibrated_calibration_intercept",
    "calibrated_calibration_slope",
    "calibrated_top1_plc_hit_rate",
    "calibrated_micro_recall_at_3",
    "calibrated_macro_ndcg_at_3",
)
RAW_METRICS = (
    "raw_macro_log_loss",
    "raw_macro_brier",
    "raw_micro_log_loss",
    "raw_micro_brier",
    "raw_calibration_intercept",
    "raw_calibration_slope",
)


def load_ablation_contract(paths: ProjectPaths) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (paths.root / CONTRACT_PATH).read_text(encoding="utf-8")
    )
    if payload["contract_version"] != EXPERIMENT_VERSION:
        raise ValueError("Unexpected balanced class-weight contract version")
    feature = payload["feature_contract"]
    if (
        feature["feature_count"] != 137
        or feature["feature_hash"] != FEATURE_HASH
        or not feature["baseline_and_challenger_identical"]
    ):
        raise ValueError("Sealed 137-feature identity contract mismatch")
    if payload["baseline"]["class_weight"] is not None:
        raise ValueError("Sealed baseline class weight mismatch")
    if payload["challenger"]["class_weight"] != "balanced":
        raise ValueError("Sealed challenger class weight mismatch")
    if any(
        payload["scope"][name]
        for name in (
            "validation_access_allowed",
            "post_2024_07_access_allowed",
            "post_2025_07_access_allowed",
        )
    ):
        raise ValueError("Ablation contract permits forbidden temporal access")
    return payload


def validate_upstream_evidence(paths: ProjectPaths, contract: dict[str, Any]) -> None:
    for name, evidence in contract["upstream_evidence"].items():
        artifact = paths.root / evidence["path"]
        if _sha256_file(artifact) != evidence["sha256"]:
            raise ValueError(f"Upstream evidence hash mismatch: {name}")


def feature_contract(paths: ProjectPaths) -> V2FeatureContract:
    contract = prior_candidate_contracts(paths)[SOURCE_CONTRACT_NAME]
    if len(contract.inputs) != 137 or contract.feature_hash != FEATURE_HASH:
        raise ValueError("Provisional 137-feature contract mismatch")
    return contract


def class_balance(frame: pd.DataFrame) -> dict[str, float | int]:
    targets = frame[TARGET_COLUMN].astype(int)
    positives = int(targets.sum())
    total = len(targets)
    negatives = total - positives
    if positives == 0 or negatives == 0:
        raise ValueError("Class balance requires both classes")
    return {
        "rows": total,
        "positive_count": positives,
        "negative_count": negatives,
        "positive_prevalence": positives / total,
        "balanced_weight_negative": total / (2 * negatives),
        "balanced_weight_positive": total / (2 * positives),
    }


def _build_pipeline(contract: V2FeatureContract, class_weight: str | None) -> Any:
    pipeline = build_v2_pipeline(contract)
    pipeline.set_params(model__class_weight=class_weight)
    return pipeline


def _fit_raw(
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    contract: V2FeatureContract,
    class_weight: str | None,
) -> tuple[np.ndarray, float, list[str]]:
    pipeline = _build_pipeline(contract, class_weight)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.perf_counter()
        pipeline.fit(train.loc[:, contract.inputs], train[TARGET_COLUMN].astype(int))
        elapsed = time.perf_counter() - started
    convergence = [
        str(item.message) for item in caught if item.category.__name__ == "ConvergenceWarning"
    ]
    if convergence:
        raise RuntimeError(f"Logistic convergence failure: {convergence}")
    probabilities = np.asarray(
        pipeline.predict_proba(evaluation.loc[:, contract.inputs])[:, 1], dtype=float
    )
    return probabilities, elapsed, [str(item.message) for item in caught]


def temporal_oof(
    train: pd.DataFrame,
    contract: V2FeatureContract,
    class_weight: str | None,
) -> tuple[pd.Series, list[dict[str, Any]], float]:
    ordered = train.sort_values(["race_date", "race_id", "horse_id"]).copy()
    dates = pd.to_datetime(ordered["race_date"])
    prediction_start = dates.min().to_period("M") + 3
    last_month = dates.max().to_period("M")
    predictions = pd.Series(index=ordered.index, dtype=float)
    folds: list[dict[str, Any]] = []
    fit_seconds = 0.0
    while prediction_start <= last_month:
        prediction_end = prediction_start + 3
        fit_mask = dates < prediction_start.start_time
        prediction_mask = (dates >= prediction_start.start_time) & (
            dates < prediction_end.start_time
        )
        fit_frame = ordered.loc[fit_mask]
        prediction_frame = ordered.loc[prediction_mask]
        if prediction_frame.empty:
            prediction_start = prediction_end
            continue
        values, elapsed, caught = _fit_raw(
            fit_frame, prediction_frame, contract, class_weight
        )
        fit_seconds += elapsed
        predictions.loc[prediction_frame.index] = values
        fit_end = pd.to_datetime(fit_frame["race_date"]).max().date()
        prediction_first = pd.to_datetime(prediction_frame["race_date"]).min().date()
        if fit_end >= prediction_first:
            raise ValueError("Temporal OOF ordering violation")
        folds.append(
            {
                "train_start": str(pd.to_datetime(fit_frame["race_date"]).min().date()),
                "train_end": str(fit_end),
                "prediction_start": str(prediction_first),
                "prediction_end": str(
                    pd.to_datetime(prediction_frame["race_date"]).max().date()
                ),
                "train_rows": len(fit_frame),
                "prediction_rows": len(prediction_frame),
                "train_races": int(fit_frame["race_id"].nunique()),
                "prediction_races": int(prediction_frame["race_id"].nunique()),
                "class_balance": class_balance(fit_frame),
                "preprocessing_fit_scope": "fold_train_only",
                "class_weight": class_weight,
                "warning_count": len(caught),
            }
        )
        prediction_start = prediction_end
    result = predictions.dropna()
    if result.empty:
        raise ValueError("Temporal OOF produced no predictions")
    return result, folds, fit_seconds


def _evaluate(prefix: str, frame: pd.DataFrame, probabilities: np.ndarray) -> dict[str, float]:
    probability = asdict(evaluate_probabilities(frame, probabilities))
    result = {
        f"{prefix}_{name}": float(probability[name])
        for name in (
            "macro_log_loss",
            "macro_brier",
            "micro_log_loss",
            "micro_brier",
            "calibration_intercept",
            "calibration_slope",
        )
    }
    if prefix == "calibrated":
        ranking = ranking_metrics(frame, probabilities)
        result.update(
            {
                f"{prefix}_{name}": float(ranking[name])
                for name in ("top1_plc_hit_rate", "micro_recall_at_3", "macro_ndcg_at_3")
            }
        )
    return result


def candidate_result(
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    contract: V2FeatureContract,
    class_weight: str | None,
) -> dict[str, Any]:
    raw, outer_seconds, caught = _fit_raw(train, evaluation, contract, class_weight)
    oof, oof_folds, oof_seconds = temporal_oof(train, contract, class_weight)
    calibrator = fit_sigmoid_calibrator(
        train.loc[oof.index, TARGET_COLUMN], oof.to_numpy(dtype=float)
    )
    calibrated = calibrator.predict(raw)
    return {
        **_evaluate("raw", evaluation, raw),
        **_evaluate("calibrated", evaluation, calibrated),
        "calibrator_intercept": calibrator.intercept,
        "calibrator_slope": calibrator.slope,
        "outer_fit_seconds": outer_seconds,
        "oof_fit_seconds": oof_seconds,
        "warning_count": len(caught) + sum(row["warning_count"] for row in oof_folds),
        "warning_messages": " | ".join(caught),
        "oof_folds": oof_folds,
    }


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = (*PRIMARY, *CALIBRATED_SECONDARY, *RAW_METRICS)
    summaries: list[dict[str, Any]] = []
    for candidate in (BASELINE_NAME, CHALLENGER_NAME):
        selected = [row for row in rows if row["candidate"] == candidate]
        summary: dict[str, Any] = {"candidate": candidate, "folds": len(selected)}
        for metric in metrics:
            values = np.asarray([row[metric] for row in selected], dtype=float)
            summary[f"{metric}_mean"] = float(values.mean())
            summary[f"{metric}_std"] = float(values.std(ddof=0))
        summaries.append(summary)
    return summaries


def _fold_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = (*PRIMARY, *CALIBRATED_SECONDARY, *RAW_METRICS)
    result: list[dict[str, Any]] = []
    for fold in DEVELOPMENT_FOLDS:
        baseline = next(
            row
            for row in rows
            if row["candidate"] == BASELINE_NAME and row["fold_id"] == fold.fold_id
        )
        challenger = next(
            row
            for row in rows
            if row["candidate"] == CHALLENGER_NAME and row["fold_id"] == fold.fold_id
        )
        result.append(
            {
                "fold_id": fold.fold_id,
                **{
                    f"delta_{metric}": float(challenger[metric]) - float(baseline[metric])
                    for metric in metrics
                },
            }
        )
    return result


def decide_balanced(
    summaries: list[dict[str, Any]], deltas: list[dict[str, Any]]
) -> dict[str, Any]:
    baseline = next(row for row in summaries if row["candidate"] == BASELINE_NAME)
    challenger = next(row for row in summaries if row["candidate"] == CHALLENGER_NAME)
    mean_deltas = {
        metric: float(challenger[f"{metric}_mean"]) - float(baseline[f"{metric}_mean"])
        for metric in PRIMARY
    }
    both_non_worse = sum(
        float(row["delta_calibrated_macro_log_loss"]) <= 0
        and float(row["delta_calibrated_macro_brier"]) <= 0
        for row in deltas
    )
    keep = all(value <= 0 for value in mean_deltas.values()) and both_non_worse >= 3
    return {
        "judgement": "KEEP_BALANCED" if keep else "DROP_BALANCED",
        "delta_calibrated_macro_log_loss_mean": mean_deltas[
            "calibrated_macro_log_loss"
        ],
        "delta_calibrated_macro_brier_mean": mean_deltas["calibrated_macro_brier"],
        "both_primary_non_worse_folds": both_non_worse,
        "required_both_primary_non_worse_folds": 3,
        "rule_applied_without_post_hoc_change": True,
    }


def _raw_baseline_reproduction(
    paths: ProjectPaths, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    payload = json.loads((paths.root / REFERENCE_RESULT).read_text(encoding="utf-8"))
    reference = {
        row["fold_id"]: row
        for row in payload["fold_metrics"]
        if row["candidate"] == SOURCE_CONTRACT_NAME
    }
    mapping = {
        "raw_macro_log_loss": "macro_log_loss",
        "raw_macro_brier": "macro_brier",
        "raw_micro_log_loss": "micro_log_loss",
        "raw_micro_brier": "micro_brier",
        "raw_calibration_intercept": "calibration_intercept",
        "raw_calibration_slope": "calibration_slope",
    }
    fold_deltas: dict[str, dict[str, float]] = {}
    for row in rows:
        if row["candidate"] != BASELINE_NAME:
            continue
        fold_deltas[row["fold_id"]] = {
            current: float(row[current]) - float(reference[row["fold_id"]][previous])
            for current, previous in mapping.items()
        }
    if any(abs(value) > 1e-12 for fold in fold_deltas.values() for value in fold.values()):
        raise ValueError(f"137-feature raw baseline reproduction failed: {fold_deltas}")
    return {"tolerance": 1e-12, "passed": True, "fold_deltas": fold_deltas}


def run_balanced_class_weight_ablation(
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    project = paths or ProjectPaths.from_root()
    contract_payload = load_ablation_contract(project)
    validate_upstream_evidence(project, contract_payload)
    contract = feature_contract(project)
    databases = resolve_experiment_database_paths(paths=project)
    protected_paths = {
        "source_database": databases.source,
        "experiment_database": databases.experiment,
        "lr1_registry": project.root / "docs/post-baseline-v2-relative-r1-registry.csv",
        "baseline_contract": project.root
        / "docs/plc-saturated-recent10-count-sequential-ablation-contract.json",
        "baseline_result_report": project.root
        / "docs/plc-saturated-recent10-count-sequential-ablation-result.md",
        "baseline_result_artifact": project.root / REFERENCE_RESULT,
        "sealed_contract": project.root / CONTRACT_PATH,
    }
    before = {name: _sha256_file(path) for name, path in protected_paths.items()}
    frame = _load_frame(project, contract)
    if (
        len(frame) != 28_392
        or frame["race_id"].nunique() != 2_675
        or frame["race_date"].max().isoformat() >= "2024-07-01"
    ):
        raise ValueError("Development population/boundary mismatch")
    development_balance = class_balance(frame)
    fold_context: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    oof_contracts: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for fold in DEVELOPMENT_FOLDS:
        train, evaluation = _fold_frames(frame, fold)
        ordered = bool(train["race_date"].max() < evaluation["race_date"].min())
        if not ordered or set(train["race_id"]) & set(evaluation["race_id"]):
            raise ValueError(f"Temporal ordering violation: {fold.fold_id}")
        fold_context.append(
            {
                "fold_id": fold.fold_id,
                "train_rows": len(train),
                "train_races": int(train["race_id"].nunique()),
                "evaluation_rows": len(evaluation),
                "evaluation_races": int(evaluation["race_id"].nunique()),
                "strict_temporal_ordering": ordered,
                "train_class_balance": class_balance(train),
                "evaluation_class_balance": class_balance(evaluation),
            }
        )
        oof_contracts[fold.fold_id] = {}
        for candidate, class_weight in CANDIDATE_CLASS_WEIGHTS.items():
            result = candidate_result(train, evaluation, contract, class_weight)
            oof_contracts[fold.fold_id][candidate] = result.pop("oof_folds")
            rows.append(
                {
                    "candidate": candidate,
                    "class_weight": class_weight,
                    "fold_id": fold.fold_id,
                    **result,
                }
            )
    summaries = _summaries(rows)
    deltas = _fold_deltas(rows)
    reproduction = _raw_baseline_reproduction(project, rows)
    decision = decide_balanced(summaries, deltas)
    after = {name: _sha256_file(path) for name, path in protected_paths.items()}
    if before != after:
        raise ValueError("Protected artifact changed")
    result = {
        "experiment_version": EXPERIMENT_VERSION,
        "contract_sha256": before["sealed_contract"],
        "contract": contract_payload,
        "development_rows": len(frame),
        "development_races": int(frame["race_id"].nunique()),
        "date_min": str(frame["race_date"].min()),
        "date_max": str(frame["race_date"].max()),
        "development_class_balance": development_balance,
        "feature_count": len(contract.inputs),
        "feature_hash": contract.feature_hash,
        "feature_identity_preserved": True,
        "fold_context": fold_context,
        "fold_metrics": rows,
        "summary_metrics": summaries,
        "fold_deltas": deltas,
        "oof_contracts": oof_contracts,
        "decision": decision,
        "raw_baseline_137_reference_reproduction": reproduction,
        "validation_access_count": 0,
        "rows_on_or_after_2024_07_01_loaded": 0,
        "post_2025_07_access_count": 0,
        "source_database_modified": False,
        "experiment_database_modified": False,
        "protected_artifacts_unchanged": True,
        "protected_sha256": after,
    }
    output = project.root / OUTPUT_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output / "fold_metrics.csv", index=False)
    pd.DataFrame(summaries).to_csv(output / "summary_metrics.csv", index=False)
    pd.DataFrame(deltas).to_csv(output / "fold_deltas.csv", index=False)
    pd.json_normalize(fold_context, sep=".").to_csv(output / "fold_context.csv", index=False)
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_balanced_class_weight_ablation(), ensure_ascii=False, indent=2))
