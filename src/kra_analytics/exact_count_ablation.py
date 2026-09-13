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

EXPERIMENT_VERSION = "plc_exact_count_structural_redundancy_ablation_v1"
CONTRACT_PATH = "docs/plc-exact-count-structural-redundancy-ablation-contract.json"
OUTPUT_DIRECTORY = f"data/exports/modeling/{EXPERIMENT_VERSION}"
DIAGNOSTIC_DIRECTORY = "data/exports/diagnostics/plc_final_feature_diagnostic_v1"
BASELINE_HASH = "7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a"
CHALLENGER_HASH = "3f8ba91bcfbfc6b96479f9e5b6729f3d12ba8d9049e4bf0e745effdfe02a32e7"
CHALLENGER_NAME = "LR1_EXACT_COUNT_SIMPLIFIED"
REMOVED_FEATURES = (
    "horse_recent3_g3f_count",
    "horse_recent3_g1f_count",
    "horse_recent3_race_relative_time_count",
    "horse_recent5_g3f_count",
    "horse_recent5_g1f_count",
    "horse_recent5_race_relative_time_count",
    "horse_recent5_weight_count",
)
SEALED_GROUPS = (
    (
        "horse_recent3_g1f_count",
        "horse_recent3_g3f_count",
        "horse_recent3_race_relative_time_count",
        "horse_recent3_race_time_count",
    ),
    (
        "horse_recent5_g1f_count",
        "horse_recent5_g3f_count",
        "horse_recent5_race_relative_time_count",
        "horse_recent5_race_time_count",
    ),
    ("horse_recent5_start_count", "horse_recent5_weight_count"),
)


def exact_duplicate_components(
    pairs: pd.DataFrame, feature_contract: pd.DataFrame
) -> tuple[tuple[str, ...], ...]:
    exact = pairs.loc[pairs["exact_value_and_null_pattern"].astype(bool)]
    allowed = set(
        feature_contract.loc[
            (feature_contract["feature_type"] == "numeric")
            & feature_contract["feature_name"].str.endswith("_count"),
            "feature_name",
        ]
    )
    graph: dict[str, set[str]] = {}
    for row in exact.itertuples(index=False):
        left, right = str(row.feature_left), str(row.feature_right)
        if left not in allowed or right not in allowed:
            continue
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    components: list[tuple[str, ...]] = []
    unseen = set(graph)
    while unseen:
        pending = [min(unseen)]
        component: set[str] = set()
        while pending:
            node = pending.pop()
            if node in component:
                continue
            component.add(node)
            pending.extend(graph[node] - component)
        unseen -= component
        components.append(tuple(sorted(component)))
    return tuple(sorted(components))


def load_ablation_contract(paths: ProjectPaths) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((paths.root / CONTRACT_PATH).read_text(encoding="utf-8"))
    if payload["contract_version"] != EXPERIMENT_VERSION:
        raise ValueError("Unexpected exact-count ablation contract version")
    if (
        payload["baseline"]["feature_count"] != 144
        or payload["baseline"]["feature_hash"] != BASELINE_HASH
    ):
        raise ValueError("Sealed LR1 baseline contract mismatch")
    challenger = payload["challenger"]
    if (
        challenger["feature_count"] != 137
        or challenger["feature_hash"] != CHALLENGER_HASH
        or tuple(challenger["remove_features"]) != REMOVED_FEATURES
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


def reconstruct_exact_groups(paths: ProjectPaths, contract: dict[str, Any]) -> dict[str, Any]:
    diagnostic = paths.root / DIAGNOSTIC_DIRECTORY
    evidence = contract["upstream_evidence"]
    for key in ("exact_pair_artifact", "special_family_artifact", "feature_contract_artifact"):
        artifact = paths.root / evidence[key]["path"]
        if _sha256_file(artifact) != evidence[key]["sha256"]:
            raise ValueError(f"Diagnostic evidence hash mismatch: {key}")
    pairs = pd.read_csv(diagnostic / "exact_or_perfect_linear_numeric_pairs.csv")
    feature_contract = pd.read_csv(diagnostic / "feature_contract.csv")
    special = pd.read_csv(diagnostic / "special_family_relationships.csv")
    components = exact_duplicate_components(pairs, feature_contract)
    if components != tuple(sorted(SEALED_GROUPS)):
        raise ValueError(f"Exact-count components differ from sealed groups: {components}")
    return {
        "groups": [list(group) for group in components],
        "exact_pair_rows": int(pairs["exact_value_and_null_pattern"].astype(bool).sum()),
        "special_family_rows_reviewed": len(special),
        "feature_contract_rows_reviewed": len(feature_contract),
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
        zero_count=tuple(
            feature for feature in baseline.zero_count if feature not in REMOVED_FEATURES
        ),
        feature_hash=_feature_hash(inputs),
    )
    if len(inputs) != 137 or len(set(inputs)) != 137 or challenger.feature_hash != CHALLENGER_HASH:
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
    both_non_worse = sum(
        float(row["delta_macro_log_loss"]) <= 0 and float(row["delta_macro_brier"]) <= 0
        for row in deltas
    )
    keep = all(value <= 0 for value in mean_deltas.values()) and both_non_worse >= 3
    return {
        "judgement": "KEEP_EXACT_COUNT_SIMPLIFICATION"
        if keep
        else "DROP_EXACT_COUNT_SIMPLIFICATION",
        "delta_macro_log_loss_mean": mean_deltas["macro_log_loss"],
        "delta_macro_brier_mean": mean_deltas["macro_brier"],
        "both_primary_non_worse_folds": both_non_worse,
        "required_both_primary_non_worse_folds": 3,
        "rule_applied_without_post_hoc_change": True,
    }


def run_exact_count_ablation(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project = paths or ProjectPaths.from_root()
    contract_payload = load_ablation_contract(project)
    evidence = reconstruct_exact_groups(project, contract_payload)
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
        "diagnostic_evidence": evidence,
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
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_exact_count_ablation(), ensure_ascii=False, indent=2))
