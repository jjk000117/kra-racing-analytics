from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS, _fold_frames
from kra_analytics.experiment_database import resolve_experiment_database_paths
from kra_analytics.modeling_v2 import V2FeatureContract
from kra_analytics.near_constant_finish_rate_ablation import (
    CHALLENGER_NAME as BASELINE_NAME,
)
from kra_analytics.near_constant_finish_rate_ablation import (
    candidate_contracts as prior_candidate_contracts,
)
from kra_analytics.paths import ProjectPaths
from kra_analytics.prize_bonus_ablation import (
    PRIMARY,
    SECONDARY,
    _feature_hash,
    _fit,
    _sha256_file,
)
from kra_analytics.relative_experiment import _load_frame

EXPERIMENT_VERSION = "plc_saturated_recent10_count_sequential_ablation_v1"
CONTRACT_PATH = "docs/plc-saturated-recent10-count-sequential-ablation-contract.json"
PRIOR_RESULT = "data/exports/modeling/plc_near_constant_finish_rate_ablation_v1/result.json"
OUTPUT_DIRECTORY = f"data/exports/modeling/{EXPERIMENT_VERSION}"
DIAGNOSTIC_DIRECTORY = "data/exports/diagnostics/plc_final_feature_diagnostic_v1"
BASELINE_HASH = "6b6b737fface03ed636302454db0d2ed9ffcdaf0e8b96f64cc5cfcba1b3cbaf9"
CHALLENGER_HASH = "7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e"
CHALLENGER_NAME = "LR1_FINISH_RATE_AND_RECENT10_COUNT_SIMPLIFIED"
REMOVED_FEATURES = (
    "jockey_recent10_start_count",
    "trainer_recent10_start_count",
)


def load_ablation_contract(paths: ProjectPaths) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((paths.root / CONTRACT_PATH).read_text(encoding="utf-8"))
    if payload["contract_version"] != EXPERIMENT_VERSION:
        raise ValueError("Unexpected saturated recent10 count contract version")
    baseline = payload["baseline"]
    if baseline["feature_count"] != 139 or baseline["feature_hash"] != BASELINE_HASH:
        raise ValueError("Sealed 139-feature baseline contract mismatch")
    challenger = payload["challenger"]
    removals = tuple(item["feature_name"] for item in challenger["remove_features"])
    if (
        challenger["feature_count"] != 137
        or challenger["feature_hash"] != CHALLENGER_HASH
        or removals != REMOVED_FEATURES
    ):
        raise ValueError("Sealed challenger contract mismatch")
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


def identify_saturated_recent10_counts(
    numeric_profile: pd.DataFrame, feature_contract: pd.DataFrame
) -> tuple[str, ...]:
    flags = numeric_profile["near_constant_99pct_flag"].astype("boolean").fillna(False)
    names = numeric_profile["feature_name"].astype(str)
    saturated = numeric_profile.loc[
        flags
        & names.isin(REMOVED_FEATURES)
        & (numeric_profile["dominant_value_rate_non_null"] >= 0.99)
        & (numeric_profile["median"] == 10),
        "feature_name",
    ]
    allowed = set(saturated.astype(str))
    ordered = feature_contract.sort_values("position")["feature_name"].astype(str)
    return tuple(feature for feature in ordered if feature in allowed)


def validate_diagnostic_evidence(paths: ProjectPaths, contract: dict[str, Any]) -> dict[str, Any]:
    evidence = contract["upstream_evidence"]
    for key in (
        "prior_contract",
        "prior_result_report",
        "prior_result_artifact",
        "numeric_profile",
        "feature_contract",
    ):
        artifact = paths.root / evidence[key]["path"]
        if _sha256_file(artifact) != evidence[key]["sha256"]:
            raise ValueError(f"Upstream evidence hash mismatch: {key}")
    diagnostic = paths.root / DIAGNOSTIC_DIRECTORY
    numeric = pd.read_csv(diagnostic / "numeric_profile.csv")
    features = pd.read_csv(diagnostic / "feature_contract.csv")
    identified = identify_saturated_recent10_counts(numeric, features)
    if set(identified) != set(REMOVED_FEATURES):
        raise ValueError(f"Saturated recent10 count set differs: {identified}")
    sealed_profile = {
        item["feature_name"]: item for item in contract["challenger"]["remove_features"]
    }
    profile_rows: list[dict[str, Any]] = []
    for feature in REMOVED_FEATURES:
        row = numeric.loc[numeric["feature_name"] == feature].iloc[0]
        sealed = sealed_profile[feature]
        if not np.isclose(
            float(row["dominant_value_rate_non_null"]),
            float(sealed["dominant_value_rate_non_null"]),
            rtol=0,
            atol=1e-15,
        ) or not np.isclose(
            float(row["missing_rate"]),
            float(sealed["missing_rate"]),
            rtol=0,
            atol=1e-15,
        ):
            raise ValueError(f"Sealed diagnostic profile mismatch: {feature}")
        profile_rows.append(
            {
                "feature_name": feature,
                "dominant_value": 10.0,
                "dominant_value_rate_non_null": float(row["dominant_value_rate_non_null"]),
                "missing_rate": float(row["missing_rate"]),
                "near_constant_99pct_flag": bool(row["near_constant_99pct_flag"]),
            }
        )
    return {
        "identified_features": list(identified),
        "profile": profile_rows,
        "numeric_profile_rows_reviewed": len(numeric),
        "feature_contract_rows_reviewed": len(features),
    }


def candidate_contracts(paths: ProjectPaths) -> dict[str, V2FeatureContract]:
    baseline = prior_candidate_contracts(paths)[BASELINE_NAME]
    if len(baseline.inputs) != 139 or baseline.feature_hash != BASELINE_HASH:
        raise ValueError("Prior KEEP baseline count/hash mismatch")
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
    if len(inputs) != 137 or len(set(inputs)) != 137 or challenger.feature_hash != CHALLENGER_HASH:
        raise ValueError("Derived challenger count/hash mismatch")
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
        metric: mean_deltas[metric] / float(baseline[f"{metric}_mean"]) * 100 for metric in PRIMARY
    }
    both_non_worse = sum(
        float(row["delta_macro_log_loss"]) <= 0 and float(row["delta_macro_brier"]) <= 0
        for row in deltas
    )
    keep = all(value <= 0 for value in mean_deltas.values()) and both_non_worse >= 3
    return {
        "judgement": (
            "KEEP_SATURATED_RECENT10_COUNT_SIMPLIFICATION"
            if keep
            else "DROP_SATURATED_RECENT10_COUNT_SIMPLIFICATION"
        ),
        "delta_macro_log_loss_mean": mean_deltas["macro_log_loss"],
        "delta_macro_brier_mean": mean_deltas["macro_brier"],
        "relative_macro_log_loss_percent": relative_percent["macro_log_loss"],
        "relative_macro_brier_percent": relative_percent["macro_brier"],
        "both_primary_non_worse_folds": both_non_worse,
        "required_both_primary_non_worse_folds": 3,
        "feature_reduction_count": len(REMOVED_FEATURES),
        "feature_reduction_percent": len(REMOVED_FEATURES) / 139 * 100,
        "rule_applied_without_post_hoc_change": True,
    }


def _prior_baseline_reproduction(paths: ProjectPaths, rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload = json.loads((paths.root / PRIOR_RESULT).read_text(encoding="utf-8"))
    reference = {
        row["fold_id"]: row for row in payload["fold_metrics"] if row["candidate"] == BASELINE_NAME
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
        raise ValueError(f"139-feature baseline reproduction failed: {deltas}")
    return {"tolerance": 1e-12, "passed": True, "fold_deltas": deltas}


def run_saturated_recent10_count_ablation(
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    project = paths or ProjectPaths.from_root()
    contract_payload = load_ablation_contract(project)
    diagnostic = validate_diagnostic_evidence(project, contract_payload)
    contracts = candidate_contracts(project)
    databases = resolve_experiment_database_paths(paths=project)
    protected_paths = {
        "source_database": databases.source,
        "experiment_database": databases.experiment,
        "lr1_registry": project.root / "docs/post-baseline-v2-relative-r1-registry.csv",
        "prior_contract": project.root
        / "docs/plc-near-constant-finish-rate-ablation-contract.json",
        "prior_result_report": project.root
        / "docs/plc-near-constant-finish-rate-ablation-result.md",
        "prior_result_artifact": project.root / PRIOR_RESULT,
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
        "diagnostic_evidence": diagnostic,
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
        "baseline_139_reference_reproduction": reproduction,
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
    pd.DataFrame(diagnostic["profile"]).to_csv(output / "removed_feature_profile.csv", index=False)
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_saturated_recent10_count_ablation(), ensure_ascii=False, indent=2))
