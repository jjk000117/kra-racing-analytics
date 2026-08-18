from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
)

from kra_analytics.development_evaluation import verify_sealed_artifacts
from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.improvement_validation import (
    ACCESS_FILE,
    EXPECTED_CONTRACT_SHA256,
    METRIC_NAMES,
    _load_frames,
    _sha256_file,
)
from kra_analytics.improvement_validation_contract import (
    CONTRACT_PATH,
    EXPECTED_FEATURE_HASH,
)
from kra_analytics.modeling import (
    calibration_table,
    evaluate_probabilities,
    fit_sigmoid_calibrator,
)
from kra_analytics.modeling_v2 import (
    TARGET_COLUMN,
    _fit_pipeline,
    expanding_temporal_oof_v2,
)
from kra_analytics.paths import ProjectPaths

DIAGNOSTIC_VERSION = "l133_sigmoid_descriptive_validation_diagnostic_v1"
OUTPUT_DIRECTORY = "data/exports/modeling/l133_sigmoid_descriptive_validation_diagnostic_v1"
RECONCILIATION_ATOL = 1e-12
FIXED_THRESHOLDS = (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_ready(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _file_hashes(paths: ProjectPaths) -> dict[str, str]:
    files = {
        "baseline_run_contract": paths.exports
        / "modeling/official_place_logistic_baseline_v2/run_contract.json",
        "baseline_refit_artifact": paths.exports
        / "modeling/official_place_logistic_baseline_v2/refit_artifact.joblib",
        "one_time_validation_result": paths.exports
        / "modeling/post_baseline_v2_f1_f3_one_time_validation_v1/result.json",
        "validation_contract": paths.root / CONTRACT_PATH,
        "feature_bundle_registry": paths.root
        / "docs/post-baseline-v2-feature-bundle-registry.csv",
        "feature_bundle_implementation": paths.root
        / "src/kra_analytics/feature_bundles.py",
    }
    return {name: _sha256_file(path) for name, path in files.items()}


def _preflight(paths: ProjectPaths) -> dict[str, Any]:
    contract_path = paths.root / CONTRACT_PATH
    contract_hash = _sha256_file(contract_path)
    if contract_hash != EXPECTED_CONTRACT_SHA256:
        raise ValueError("Validation contract SHA256 mismatch")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    candidate = _combined_contract(paths)["F1+F3"]
    if len(candidate.inputs) != 133 or candidate.feature_hash != EXPECTED_FEATURE_HASH:
        raise ValueError("133-Feature implementation contract mismatch")
    if list(candidate.inputs) != contract["candidate"]["feature_order"]:
        raise ValueError("Feature name/order mismatch")
    if contract["logistic"] != {
        "penalty": "l2",
        "C": 1.0,
        "solver": "lbfgs",
        "max_iter": 2000,
        "class_weight": None,
        "random_state": 20260817,
        "warning_policy": (
            "record sklearn penalty deprecation separately; any ConvergenceWarning fails the run"
        ),
    }:
        raise ValueError("Logistic contract mismatch")
    if contract["calibration"]["oof_rule"] != (
        "first 3 months train; predict next 3 months; expand by 3 months"
    ):
        raise ValueError("Temporal OOF calibration contract mismatch")
    access_path = paths.root / ACCESS_FILE
    access = json.loads(access_path.read_text(encoding="utf-8"))
    if access.get("access_count") != 1 or access.get("status") != "COMPLETED":
        raise ValueError("Original model-selection Validation access is not completed once")
    if access.get("promotion_decision") != "PROMOTE":
        raise ValueError("Original PROMOTE decision mismatch")
    reaccesses = access.get("descriptive_diagnostic_reaccesses", [])
    if reaccesses:
        raise RuntimeError("Descriptive diagnostic re-access has already been recorded")
    protection = json.loads(
        (paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    sealed_hashes = verify_sealed_artifacts(paths, protection["artifacts"])
    if sealed_hashes != contract["protection"]["sealed_baseline_artifacts"]:
        raise ValueError("Sealed baseline artifact hash mismatch")
    return {
        "contract_sha256": contract_hash,
        "feature_count": len(candidate.inputs),
        "feature_hash": candidate.feature_hash,
        "feature_order_matches": True,
        "preprocessing_contract_matches": True,
        "logistic_contract_matches": True,
        "temporal_oof_contract_matches": True,
        "original_promotion_decision": "PROMOTE",
        "original_model_selection_access_count": 1,
        "protected_hashes_before": _file_hashes(paths),
    }


def _record_reaccess(paths: ProjectPaths, *, status: str, **details: Any) -> None:
    access_path = paths.root / ACCESS_FILE
    access = json.loads(access_path.read_text(encoding="utf-8"))
    entries = list(access.get("descriptive_diagnostic_reaccesses", []))
    if status == "ACCESS_STARTED":
        if entries:
            raise RuntimeError("Descriptive diagnostic re-access already exists")
        entries.append(
            {
                "access_type": "DESCRIPTIVE_DIAGNOSTIC_REACCESS",
                "accessed_at_utc": datetime.now(UTC).isoformat(),
                "status": status,
                "purpose": "restore omitted row-level predictions for descriptive diagnostics only",
                "candidate_selection_allowed": False,
                "feature_or_model_change_allowed": False,
                "threshold_adoption_allowed": False,
            }
        )
    else:
        if len(entries) != 1:
            raise RuntimeError("Expected one started descriptive diagnostic re-access")
        entries[0].update({"status": status, **_json_ready(details)})
    access["descriptive_diagnostic_reaccess_count"] = len(entries)
    access["descriptive_diagnostic_reaccesses"] = entries
    _write_json(access_path, access)


def threshold_metrics(
    targets: np.ndarray, probabilities: np.ndarray, thresholds: tuple[float, ...]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        predicted = probabilities >= threshold
        tn, fp, fn, tp = confusion_matrix(
            targets, predicted, labels=[0, 1]
        ).ravel()
        precision = float(tp / (tp + fp)) if tp + fp else 0.0
        recall = float(tp / (tp + fn)) if tp + fn else 0.0
        specificity = float(tn / (tn + fp)) if tn + fp else 0.0
        f1 = float(2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        rows.append(
            {
                "threshold": threshold,
                "precision": precision,
                "recall": recall,
                "miss_rate": 1.0 - recall,
                "f1": f1,
                "specificity": specificity,
                "predicted_positive_rate": float(predicted.mean()),
                "tp": int(tp),
                "fp": int(fp),
                "fn": int(fn),
                "tn": int(tn),
            }
        )
    return rows


def maximum_f1_reference(targets: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    precision, recall, thresholds = precision_recall_curve(targets, probabilities)
    numerator = 2 * precision[:-1] * recall[:-1]
    denominator = precision[:-1] + recall[:-1]
    f1 = np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator),
        where=denominator > 0,
    )
    best = int(np.flatnonzero(f1 == f1.max())[-1])
    return {
        "threshold": float(thresholds[best]),
        "precision": float(precision[best]),
        "recall": float(recall[best]),
        "miss_rate": float(1.0 - recall[best]),
        "f1": float(f1[best]),
        "selection_scope": "descriptive reference only; not an adopted threshold",
        "tie_rule": "highest threshold among exactly tied maximum-F1 points",
    }


def ranking_metrics(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = frame.sort_values(
        ["race_id", "sigmoid_probability", "horse_id"],
        ascending=[True, False, True],
        kind="mergesort",
    ).copy()
    ranked["within_race_probability_rank"] = (
        ranked.groupby("race_id", observed=True).cumcount() + 1
    )
    race_hits = ranked.groupby("race_id", observed=True)[TARGET_COLUMN].sum()
    rows: list[dict[str, Any]] = []
    for top_k in (1, 2, 3):
        selected = ranked.loc[ranked["within_race_probability_rank"] <= top_k]
        selected_hits = selected.groupby("race_id", observed=True)[TARGET_COLUMN].sum()
        selected_hits = selected_hits.reindex(race_hits.index, fill_value=0)
        rows.append(
            {
                "top_k": top_k,
                "races": int(len(race_hits)),
                "races_with_at_least_one_hit": int((selected_hits > 0).sum()),
                "race_any_hit_rate": float((selected_hits > 0).mean()),
                "mean_hits_per_race": float(selected_hits.mean()),
                "total_selected_hits": int(selected_hits.sum()),
                "total_actual_hits": int(race_hits.sum()),
                "micro_recall_at_k": float(selected_hits.sum() / race_hits.sum()),
                "macro_race_recall_at_k": float((selected_hits / race_hits).mean()),
            }
        )
    top3 = ranked.loc[ranked["within_race_probability_rank"] <= 3]
    top3_hits = (
        top3.groupby("race_id", observed=True)[TARGET_COLUMN]
        .sum()
        .reindex(race_hits.index, fill_value=0)
    )
    distribution = [
        {
            "top3_actual_hit_count": hit_count,
            "races": int((top3_hits == hit_count).sum()),
            "race_share": float((top3_hits == hit_count).mean()),
        }
        for hit_count in (0, 1, 2, 3)
    ]
    return rows, distribution


def fixed_probability_bins(frame: pd.DataFrame) -> list[dict[str, Any]]:
    working = frame.copy()
    edges = np.linspace(0.0, 1.0, 11).tolist()
    working["probability_bin"] = pd.cut(
        working["sigmoid_probability"], edges, include_lowest=True, right=False
    )
    grouped = working.groupby("probability_bin", observed=False)
    rows: list[dict[str, Any]] = []
    for interval, group in grouped:
        rows.append(
            {
                "probability_bin": str(interval),
                "rows": len(group),
                "predicted_mean": float(group["sigmoid_probability"].mean())
                if len(group)
                else None,
                "observed_rate": float(group[TARGET_COLUMN].mean()) if len(group) else None,
            }
        )
    return rows


def run_descriptive_validation_diagnostic(
    *, paths: ProjectPaths | None = None
) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    preflight = _preflight(project_paths)
    original_result_path = (
        project_paths.exports
        / "modeling/post_baseline_v2_f1_f3_one_time_validation_v1/result.json"
    )
    original_result = json.loads(original_result_path.read_text(encoding="utf-8"))
    stored_raw = original_result["metrics"]["f1_f3_logistic_raw"]
    stored_sigmoid = original_result["metrics"]["f1_f3_logistic_sigmoid"]
    output = project_paths.root / OUTPUT_DIRECTORY
    _record_reaccess(project_paths, status="ACCESS_STARTED")
    try:
        candidate = _combined_contract(project_paths)["F1+F3"]
        train, validation, data_audit = _load_frames(project_paths, candidate.inputs)
        pipeline, convergence_warnings = _fit_pipeline(train, candidate)
        raw = cast(
            np.ndarray,
            pipeline.predict_proba(validation.loc[:, candidate.inputs])[:, 1],
        )
        oof, oof_folds = expanding_temporal_oof_v2(train, candidate)
        calibrator = fit_sigmoid_calibrator(
            train.loc[oof.index, TARGET_COLUMN], oof.to_numpy()
        )
        sigmoid = calibrator.predict(raw)
        raw_metrics = asdict(evaluate_probabilities(validation, raw))
        sigmoid_metrics = asdict(evaluate_probabilities(validation, sigmoid))
        reconciliation: dict[str, Any] = {}
        for candidate_name, observed, stored in (
            ("raw", raw_metrics, stored_raw),
            ("sigmoid", sigmoid_metrics, stored_sigmoid),
        ):
            for metric in METRIC_NAMES:
                difference = abs(float(observed[metric]) - float(stored[metric]))
                reconciliation[f"{candidate_name}_{metric}"] = {
                    "stored": stored[metric],
                    "reproduced": observed[metric],
                    "absolute_difference": difference,
                    "within_tolerance": difference <= RECONCILIATION_ATOL,
                }
        if not all(row["within_tolerance"] for row in reconciliation.values()):
            raise ValueError("Reproduced Validation aggregate metrics exceeded 1e-12 tolerance")

        evaluation = validation.loc[
            :, ["race_id", "race_date", "horse_id", TARGET_COLUMN, "registered_runner_count"]
        ].copy()
        evaluation["raw_probability"] = raw
        evaluation["sigmoid_probability"] = sigmoid
        if evaluation["race_date"].max() >= datetime(2025, 7, 1).date():
            raise ValueError("Evaluation artifact crossed 2025-07-01")
        targets = evaluation[TARGET_COLUMN].astype(int).to_numpy()
        discrimination = {
            "roc_auc": float(roc_auc_score(targets, sigmoid)),
            "pr_auc_average_precision": float(average_precision_score(targets, sigmoid)),
            "prevalence": float(targets.mean()),
            "pr_auc_lift_over_prevalence": float(
                average_precision_score(targets, sigmoid) / targets.mean()
            ),
        }
        fixed_threshold_rows = threshold_metrics(targets, sigmoid, FIXED_THRESHOLDS)
        maximum_f1 = maximum_f1_reference(targets, sigmoid)
        top_k_rows, top3_distribution = ranking_metrics(evaluation)
        fixed_bin_rows = fixed_probability_bins(evaluation)
        deciles = calibration_table(validation, sigmoid)

        output.mkdir(parents=True, exist_ok=True)
        evaluation.to_csv(
            output / "row_level_validation_predictions.csv",
            index=False,
            encoding="utf-8-sig",
        )
        _write_csv(output / "threshold_metrics.csv", fixed_threshold_rows)
        _write_csv(output / "top_k_ranking_metrics.csv", top_k_rows)
        _write_csv(output / "top3_hit_count_distribution.csv", top3_distribution)
        _write_csv(output / "fixed_probability_bins.csv", fixed_bin_rows)
        _write_csv(output / "probability_deciles.csv", deciles)
        _write_csv(output / "oof_folds.csv", oof_folds)

        protected_after = _file_hashes(project_paths)
        if protected_after != preflight["protected_hashes_before"]:
            raise ValueError("Protected artifact changed during descriptive diagnostic")
        result: dict[str, Any] = {
            "diagnostic_version": DIAGNOSTIC_VERSION,
            "access_type": "DESCRIPTIVE_DIAGNOSTIC_REACCESS",
            "reconciliation_tolerance_absolute": RECONCILIATION_ATOL,
            "preflight": preflight,
            "train": {
                "start": str(train["race_date"].min()),
                "end": str(train["race_date"].max()),
                "rows": len(train),
                "races": int(train["race_id"].nunique()),
            },
            "validation": {
                "start": str(validation["race_date"].min()),
                "end": str(validation["race_date"].max()),
                "rows": len(validation),
                "races": int(validation["race_id"].nunique()),
            },
            "reconciliation": reconciliation,
            "raw_metrics": raw_metrics,
            "sigmoid_metrics": sigmoid_metrics,
            "discrimination": discrimination,
            "fixed_thresholds": fixed_threshold_rows,
            "maximum_f1_reference": maximum_f1,
            "top_k": top_k_rows,
            "top3_hit_count_distribution": top3_distribution,
            "calibrator": asdict(calibrator),
            "oof_folds": oof_folds,
            "data_audit": {
                **data_audit,
                "candidate_convergence_warnings": convergence_warnings,
                "row_level_duplicate_keys": int(
                    evaluation.duplicated(["race_id", "horse_id"]).sum()
                ),
                "post_2025_07_rows": 0,
            },
            "interpretation_contract": {
                "descriptive_only": True,
                "threshold_adopted": False,
                "candidate_selection_changed": False,
                "promotion_decision_changed": False,
                "train_plus_validation_refit_performed": False,
                "post_selection_temporal_evaluation_performed": False,
            },
            "protected_hashes_after": protected_after,
            "artifacts": {
                "row_level_predictions": "row_level_validation_predictions.csv",
                "threshold_metrics": "threshold_metrics.csv",
                "top_k_metrics": "top_k_ranking_metrics.csv",
                "top3_distribution": "top3_hit_count_distribution.csv",
                "fixed_probability_bins": "fixed_probability_bins.csv",
                "probability_deciles": "probability_deciles.csv",
            },
        }
        _write_json(output / "result.json", result)
        _record_reaccess(
            project_paths,
            status="COMPLETED",
            completed_at_utc=datetime.now(UTC).isoformat(),
            diagnostic_version=DIAGNOSTIC_VERSION,
            aggregate_reconciliation_passed=True,
            reconciliation_tolerance_absolute=RECONCILIATION_ATOL,
            row_level_artifact=str(
                Path(OUTPUT_DIRECTORY) / "row_level_validation_predictions.csv"
            ),
            candidate_selection_changed=False,
            promotion_decision_changed=False,
            post_2025_07_access=False,
        )
        return result
    except Exception as error:
        _record_reaccess(
            project_paths,
            status="FAILED_AFTER_ACCESS",
            failed_at_utc=datetime.now(UTC).isoformat(),
            error_type=type(error).__name__,
            error_message=str(error),
        )
        raise
