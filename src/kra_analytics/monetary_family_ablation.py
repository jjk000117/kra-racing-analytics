from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS, _fold_frames
from kra_analytics.experiment_database import resolve_experiment_database_paths
from kra_analytics.modeling_v2 import V2FeatureContract
from kra_analytics.paths import ProjectPaths
from kra_analytics.prize_bonus_ablation import (
    PRIMARY,
    SECONDARY,
    _feature_hash,
    _fit,
    _sha256_file,
)
from kra_analytics.relative_experiment import _load_frame
from kra_analytics.saturated_recent10_count_ablation import (
    CHALLENGER_NAME as BASELINE_NAME,
)
from kra_analytics.saturated_recent10_count_ablation import (
    candidate_contracts as prior_candidate_contracts,
)

EXPERIMENT_VERSION = "plc_monetary_family_full_removal_sequential_ablation_v1"
CONTRACT_PATH = "docs/plc-monetary-family-full-removal-sequential-ablation-contract.json"
PRIOR_RESULT = (
    "data/exports/modeling/"
    "plc_saturated_recent10_count_sequential_ablation_v1/result.json"
)
OUTPUT_DIRECTORY = f"data/exports/modeling/{EXPERIMENT_VERSION}"
BASELINE_HASH = "7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e"
CHALLENGER_HASH = "253891f6a97c65df4a5e9f1046efb9f7824fd4fd5d7e3d0cc4135e3b5e3db028"
CHALLENGER_NAME = "LR1_SEQUENTIAL_MONETARY_FREE"
REMOVED_FEATURES = (
    "race_first_prize",
    "race_second_prize",
    "race_third_prize",
    "race_fourth_prize",
    "race_fifth_prize",
    "race_bonus_1",
    "race_bonus_2",
    "race_bonus_3",
)
REQUIRED_RETAINED_FEATURES = ("race_grade", "race_prize_condition")


def load_ablation_contract(paths: ProjectPaths) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (paths.root / CONTRACT_PATH).read_text(encoding="utf-8")
    )
    if payload["contract_version"] != EXPERIMENT_VERSION:
        raise ValueError("Unexpected monetary family ablation contract version")
    baseline = payload["baseline"]
    challenger = payload["challenger"]
    removals = tuple(challenger["remove_features"])
    if baseline["feature_count"] != 137 or baseline["feature_hash"] != BASELINE_HASH:
        raise ValueError("Sealed 137-feature baseline contract mismatch")
    if (
        challenger["feature_count"] != 129
        or challenger["feature_hash"] != CHALLENGER_HASH
        or removals != REMOVED_FEATURES
    ):
        raise ValueError("Sealed monetary-free challenger contract mismatch")
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


def candidate_contracts(paths: ProjectPaths) -> dict[str, V2FeatureContract]:
    baseline = prior_candidate_contracts(paths)[BASELINE_NAME]
    if len(baseline.inputs) != 137 or baseline.feature_hash != BASELINE_HASH:
        raise ValueError("Prior KEEP baseline count/hash mismatch")
    absent = tuple(feature for feature in REMOVED_FEATURES if feature not in baseline.inputs)
    if absent:
        raise ValueError(f"Sealed monetary Features absent from baseline: {absent}")
    if any(feature not in baseline.inputs for feature in REQUIRED_RETAINED_FEATURES):
        raise ValueError("Required non-monetary race context is absent")
    inputs = tuple(feature for feature in baseline.inputs if feature not in REMOVED_FEATURES)
    challenger = V2FeatureContract(
        inputs=inputs,
        categorical=baseline.categorical,
        numeric=tuple(feature for feature in baseline.numeric if feature not in REMOVED_FEATURES),
        zero_count=tuple(
            feature for feature in baseline.zero_count if feature not in REMOVED_FEATURES
        ),
        feature_hash=_feature_hash(inputs),
    )
    if (
        len(inputs) != 129
        or len(set(inputs)) != 129
        or challenger.feature_hash != CHALLENGER_HASH
    ):
        raise ValueError("Derived monetary-free challenger count/hash mismatch")
    return {BASELINE_NAME: baseline, CHALLENGER_NAME: challenger}


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for candidate in (BASELINE_NAME, CHALLENGER_NAME):
        selected = [row for row in rows if row["candidate"] == candidate]
        summary: dict[str, Any] = {"candidate": candidate, "folds": len(selected)}
        for metric in (*PRIMARY, *SECONDARY, "fit_seconds"):
            values = np.asarray([row[metric] for row in selected], dtype=float)
            summary[f"{metric}_mean"] = float(values.mean())
            summary[f"{metric}_std"] = float(values.std(ddof=0))
        summaries.append(summary)
    return summaries


def _fold_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                    for metric in (*PRIMARY, *SECONDARY)
                },
            }
        )
    return result


def decide_simplification(
    summaries: list[dict[str, Any]], deltas: list[dict[str, Any]]
) -> dict[str, Any]:
    baseline = next(row for row in summaries if row["candidate"] == BASELINE_NAME)
    challenger = next(row for row in summaries if row["candidate"] == CHALLENGER_NAME)
    mean_deltas = {
        metric: float(challenger[f"{metric}_mean"]) - float(baseline[f"{metric}_mean"])
        for metric in PRIMARY
    }
    relative_percent = {
        metric: mean_deltas[metric] / float(baseline[f"{metric}_mean"]) * 100
        for metric in PRIMARY
    }
    both_non_worse = sum(
        float(row["delta_macro_log_loss"]) <= 0
        and float(row["delta_macro_brier"]) <= 0
        for row in deltas
    )
    keep = all(value <= 0 for value in mean_deltas.values()) and both_non_worse >= 3
    return {
        "judgement": (
            "KEEP_MONETARY_FAMILY_REMOVAL"
            if keep
            else "DROP_MONETARY_FAMILY_REMOVAL"
        ),
        "delta_macro_log_loss_mean": mean_deltas["macro_log_loss"],
        "delta_macro_brier_mean": mean_deltas["macro_brier"],
        "relative_macro_log_loss_percent": relative_percent["macro_log_loss"],
        "relative_macro_brier_percent": relative_percent["macro_brier"],
        "both_primary_non_worse_folds": both_non_worse,
        "required_both_primary_non_worse_folds": 3,
        "feature_reduction_count": len(REMOVED_FEATURES),
        "feature_reduction_percent": len(REMOVED_FEATURES) / 137 * 100,
        "rule_applied_without_post_hoc_change": True,
    }


def _prior_baseline_reproduction(
    paths: ProjectPaths, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    payload = json.loads((paths.root / PRIOR_RESULT).read_text(encoding="utf-8"))
    reference = {
        row["fold_id"]: row
        for row in payload["fold_metrics"]
        if row["candidate"] == BASELINE_NAME
    }
    metrics = (*PRIMARY, *SECONDARY[:4])
    deltas: dict[str, dict[str, float]] = {}
    for row in rows:
        if row["candidate"] != BASELINE_NAME:
            continue
        deltas[row["fold_id"]] = {
            metric: float(row[metric]) - float(reference[row["fold_id"]][metric])
            for metric in metrics
        }
    if any(abs(value) > 1e-12 for fold in deltas.values() for value in fold.values()):
        raise ValueError(f"137-feature baseline reproduction failed: {deltas}")
    return {"tolerance": 1e-12, "passed": True, "fold_deltas": deltas}


def run_monetary_family_ablation(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project = paths or ProjectPaths.from_root()
    contract_payload = load_ablation_contract(project)
    validate_upstream_evidence(project, contract_payload)
    contracts = candidate_contracts(project)
    databases = resolve_experiment_database_paths(paths=project)
    protected_paths = {
        "source_database": databases.source,
        "experiment_database": databases.experiment,
        "lr1_registry": project.root / "docs/post-baseline-v2-relative-r1-registry.csv",
        "prior_prize_bonus_result": project.root
        / "docs/plc-prize-bonus-structural-redundancy-ablation-result.md",
        "sequential_baseline_contract": project.root
        / "docs/plc-saturated-recent10-count-sequential-ablation-contract.json",
        "sequential_baseline_result": project.root
        / "docs/plc-saturated-recent10-count-sequential-ablation-result.md",
        "sequential_baseline_artifact": project.root / PRIOR_RESULT,
        "sealed_contract": project.root / CONTRACT_PATH,
    }
    before = {name: _sha256_file(path) for name, path in protected_paths.items()}
    frame = _load_frame(project, contracts[BASELINE_NAME])
    if (
        len(frame) != 28_392
        or frame["race_id"].nunique() != 2_675
        or frame["race_date"].max().isoformat() >= "2024-07-01"
    ):
        raise ValueError("Development population/boundary mismatch")
    fold_context: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
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
            }
        )
        for candidate, feature_contract in contracts.items():
            metrics, elapsed, caught = _fit(train, evaluation, feature_contract)
            rows.append(
                {
                    "candidate": candidate,
                    "fold_id": fold.fold_id,
                    **metrics,
                    "fit_seconds": elapsed,
                    "warning_count": len(caught),
                    "warning_messages": " | ".join(caught),
                }
            )
    summaries = _summaries(rows)
    deltas = _fold_deltas(rows)
    reproduction = _prior_baseline_reproduction(project, rows)
    decision = decide_simplification(summaries, deltas)
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
        "candidates": [
            {
                "candidate": name,
                "feature_count": len(value.inputs),
                "feature_hash": value.feature_hash,
                "features": list(value.inputs),
            }
            for name, value in contracts.items()
        ],
        "removed_features": list(REMOVED_FEATURES),
        "fold_context": fold_context,
        "fold_metrics": rows,
        "summary_metrics": summaries,
        "fold_deltas": deltas,
        "decision": decision,
        "baseline_137_reference_reproduction": reproduction,
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
    pd.DataFrame(fold_context).to_csv(output / "fold_context.csv", index=False)
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_monetary_family_ablation(), ensure_ascii=False, indent=2))
