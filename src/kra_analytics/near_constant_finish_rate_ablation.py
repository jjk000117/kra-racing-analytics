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
    _reference_reproduction,
    _sha256_file,
)
from kra_analytics.relative_experiment import _contracts, _load_frame

EXPERIMENT_VERSION = "plc_near_constant_finish_rate_ablation_v1"
CONTRACT_PATH = "docs/plc-near-constant-finish-rate-ablation-contract.json"
OUTPUT_DIRECTORY = f"data/exports/modeling/{EXPERIMENT_VERSION}"
DIAGNOSTIC_DIRECTORY = "data/exports/diagnostics/plc_final_feature_diagnostic_v1"
BASELINE_HASH = "7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a"
CHALLENGER_HASH = "6b6b737fface03ed636302454db0d2ed9ffcdaf0e8b96f64cc5cfcba1b3cbaf9"
CHALLENGER_NAME = "LR1_NEAR_CONSTANT_FINISH_RATE_SIMPLIFIED"
REMOVED_FEATURES = (
    "horse_recent3_finish_rate",
    "horse_recent5_finish_rate",
    "horse_recent10_finish_rate",
    "horse_same_distance_finish_rate",
    "horse_same_meet_distance_finish_rate",
)


def load_ablation_contract(paths: ProjectPaths) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((paths.root / CONTRACT_PATH).read_text(encoding="utf-8"))
    if payload["contract_version"] != EXPERIMENT_VERSION:
        raise ValueError("Unexpected near-constant finish-rate contract version")
    baseline = payload["baseline"]
    if baseline["feature_count"] != 144 or baseline["feature_hash"] != BASELINE_HASH:
        raise ValueError("Sealed LR1 baseline contract mismatch")
    challenger = payload["challenger"]
    removals = tuple(item["feature_name"] for item in challenger["remove_features"])
    if (
        challenger["feature_count"] != 139
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


def identify_flagged_finish_rates(
    numeric_profile: pd.DataFrame, feature_contract: pd.DataFrame
) -> tuple[str, ...]:
    flags = numeric_profile["near_constant_99pct_flag"].astype("boolean").fillna(False)
    flagged = numeric_profile.loc[
        flags
        & numeric_profile["feature_name"].str.endswith("finish_rate")
        & (numeric_profile["dominant_value_rate_non_null"] >= 0.99),
        "feature_name",
    ]
    ordered_contract = feature_contract.sort_values("position")
    allowed = set(flagged.astype(str))
    return tuple(
        feature for feature in ordered_contract["feature_name"].astype(str) if feature in allowed
    )


def validate_diagnostic_evidence(paths: ProjectPaths, contract: dict[str, Any]) -> dict[str, Any]:
    evidence = contract["upstream_evidence"]
    for key in ("numeric_profile", "feature_contract", "special_family_relationships"):
        artifact = paths.root / evidence[key]["path"]
        if _sha256_file(artifact) != evidence[key]["sha256"]:
            raise ValueError(f"Diagnostic evidence hash mismatch: {key}")
    diagnostic = paths.root / DIAGNOSTIC_DIRECTORY
    numeric = pd.read_csv(diagnostic / "numeric_profile.csv")
    features = pd.read_csv(diagnostic / "feature_contract.csv")
    special = pd.read_csv(diagnostic / "special_family_relationships.csv")
    identified = identify_flagged_finish_rates(numeric, features)
    if set(identified) != set(REMOVED_FEATURES):
        raise ValueError(f"Flagged finish-rate set differs from contract: {identified}")
    contract_profile = {
        item["feature_name"]: item for item in contract["challenger"]["remove_features"]
    }
    profile_rows: list[dict[str, Any]] = []
    for feature in REMOVED_FEATURES:
        row = numeric.loc[numeric["feature_name"] == feature].iloc[0]
        sealed = contract_profile[feature]
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
                "dominant_value": float(row["median"]),
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
        "special_family_rows_reviewed": len(special),
    }


def candidate_contracts(paths: ProjectPaths) -> dict[str, V2FeatureContract]:
    baseline = _contracts(paths)["LR1"]
    if len(baseline.inputs) != 144 or baseline.feature_hash != BASELINE_HASH:
        raise ValueError("LR1 count/hash mismatch")
    inputs = tuple(feature for feature in baseline.inputs if feature not in REMOVED_FEATURES)
    challenger = V2FeatureContract(
        inputs=inputs,
        categorical=baseline.categorical,
        numeric=tuple(feature for feature in baseline.numeric if feature not in REMOVED_FEATURES),
        zero_count=baseline.zero_count,
        feature_hash=_feature_hash(inputs),
    )
    if len(inputs) != 139 or len(set(inputs)) != 139 or challenger.feature_hash != CHALLENGER_HASH:
        raise ValueError("Derived challenger count/hash mismatch")
    return {"LR1": baseline, CHALLENGER_NAME: challenger}


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for candidate in ("LR1", CHALLENGER_NAME):
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
            row for row in rows if row["candidate"] == "LR1" and row["fold_id"] == fold.fold_id
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
    baseline = next(row for row in summaries if row["candidate"] == "LR1")
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
            "KEEP_NEAR_CONSTANT_FINISH_RATE_SIMPLIFICATION"
            if keep
            else "DROP_NEAR_CONSTANT_FINISH_RATE_SIMPLIFICATION"
        ),
        "delta_macro_log_loss_mean": mean_deltas["macro_log_loss"],
        "delta_macro_brier_mean": mean_deltas["macro_brier"],
        "relative_macro_log_loss_percent": relative_percent["macro_log_loss"],
        "relative_macro_brier_percent": relative_percent["macro_brier"],
        "both_primary_non_worse_folds": both_non_worse,
        "required_both_primary_non_worse_folds": 3,
        "feature_reduction_count": len(REMOVED_FEATURES),
        "feature_reduction_percent": len(REMOVED_FEATURES) / 144 * 100,
        "rule_applied_without_post_hoc_change": True,
    }


def run_near_constant_finish_rate_ablation(
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
        "lr1_code": project.root / "src/kra_analytics/relative_features.py",
        "lr1_reference_result": project.root
        / "data/exports/modeling/post_baseline_v2_relative_r1_development_v1/result.json",
        "sealed_contract": project.root / CONTRACT_PATH,
    }
    before = {name: _sha256_file(path) for name, path in protected_paths.items()}
    frame = _load_frame(project, contracts["LR1"])
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
    reproduction = _reference_reproduction(project, rows)
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
        "lr1_reference_reproduction": reproduction,
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
    print(json.dumps(run_near_constant_finish_rate_ablation(), ensure_ascii=False, indent=2))
