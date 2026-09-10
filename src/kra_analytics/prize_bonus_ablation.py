from __future__ import annotations

import hashlib
import json
import time
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS, _fold_frames
from kra_analytics.experiment_database import resolve_experiment_database_paths
from kra_analytics.modeling import evaluate_probabilities
from kra_analytics.modeling_v2 import TARGET_COLUMN, V2FeatureContract, build_v2_pipeline
from kra_analytics.paths import ProjectPaths
from kra_analytics.race_aware_experiment import ranking_metrics
from kra_analytics.relative_experiment import _contracts, _load_frame

EXPERIMENT_VERSION = "plc_prize_bonus_structural_redundancy_ablation_v1"
CONTRACT_PATH = "docs/plc-prize-bonus-structural-redundancy-ablation-contract.json"
REFERENCE_RESULT = "data/exports/modeling/post_baseline_v2_relative_r1_development_v1/result.json"
OUTPUT_DIRECTORY = f"data/exports/modeling/{EXPERIMENT_VERSION}"
BASELINE_HASH = "7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a"
CHALLENGER_HASH = "e767676c30493b51f9f5548cf417fd2503a79bf08120ac41be01027fb410f260"
REMOVED_FEATURES = (
    "race_second_prize",
    "race_third_prize",
    "race_fourth_prize",
    "race_fifth_prize",
    "race_bonus_2",
    "race_bonus_3",
)
PRIMARY = ("macro_log_loss", "macro_brier")
SECONDARY = (
    "micro_log_loss",
    "micro_brier",
    "calibration_intercept",
    "calibration_slope",
    "top1_plc_hit_rate",
    "micro_recall_at_3",
    "macro_ndcg_at_3",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _feature_hash(features: tuple[str, ...]) -> str:
    return hashlib.sha256(("\n".join(features) + "\n").encode()).hexdigest()


def load_ablation_contract(paths: ProjectPaths) -> dict[str, Any]:
    path = paths.root / CONTRACT_PATH
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if payload["contract_version"] != EXPERIMENT_VERSION:
        raise ValueError("Unexpected ablation contract version")
    if payload["baseline"] != {
        "name": "LR1",
        "feature_count": 144,
        "feature_hash": BASELINE_HASH,
    }:
        raise ValueError("Sealed LR1 baseline contract mismatch")
    challenger = payload["challenger"]
    if (
        challenger["feature_count"] != 138
        or challenger["feature_hash"] != CHALLENGER_HASH
        or tuple(challenger["remove_features"]) != REMOVED_FEATURES
    ):
        raise ValueError("Sealed challenger contract mismatch")
    scope = payload["scope"]
    if any(
        scope[name]
        for name in (
            "validation_access_allowed",
            "post_2024_07_access_allowed",
            "post_2025_07_access_allowed",
        )
    ):
        raise ValueError("Ablation contract permits forbidden temporal access")
    return payload


def candidate_contracts(paths: ProjectPaths) -> dict[str, V2FeatureContract]:
    baseline = _contracts(paths)["LR1"]
    if len(baseline.inputs) != 144 or baseline.feature_hash != BASELINE_HASH:
        raise ValueError("LR1 count/hash mismatch")
    if any(feature not in baseline.inputs for feature in REMOVED_FEATURES):
        raise ValueError("A sealed removal Feature is absent from LR1")
    inputs = tuple(feature for feature in baseline.inputs if feature not in REMOVED_FEATURES)
    challenger = V2FeatureContract(
        inputs=inputs,
        categorical=baseline.categorical,
        numeric=tuple(feature for feature in baseline.numeric if feature not in REMOVED_FEATURES),
        zero_count=baseline.zero_count,
        feature_hash=_feature_hash(inputs),
    )
    if len(inputs) != 138 or len(set(inputs)) != 138 or challenger.feature_hash != CHALLENGER_HASH:
        raise ValueError("Derived challenger count/hash mismatch")
    return {"LR1": baseline, "LR1_PRIZE_BONUS_SIMPLIFIED": challenger}


def decide_simplification(
    summaries: list[dict[str, Any]], deltas: list[dict[str, Any]]
) -> dict[str, Any]:
    baseline = next(row for row in summaries if row["candidate"] == "LR1")
    challenger = next(
        row for row in summaries if row["candidate"] == "LR1_PRIZE_BONUS_SIMPLIFIED"
    )
    mean_deltas = {
        metric: float(challenger[f"{metric}_mean"]) - float(baseline[f"{metric}_mean"])
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
            "KEEP_PRIZE_BONUS_SIMPLIFICATION"
            if keep
            else "DROP_PRIZE_BONUS_SIMPLIFICATION"
        ),
        "delta_macro_log_loss_mean": mean_deltas["macro_log_loss"],
        "delta_macro_brier_mean": mean_deltas["macro_brier"],
        "both_primary_non_worse_folds": both_non_worse,
        "required_both_primary_non_worse_folds": 3,
        "rule_applied_without_post_hoc_change": True,
    }


def _fit(
    train: pd.DataFrame, evaluation: pd.DataFrame, contract: V2FeatureContract
) -> tuple[dict[str, float], float, list[str]]:
    pipeline = build_v2_pipeline(contract)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        started = time.perf_counter()
        pipeline.fit(train.loc[:, contract.inputs], train[TARGET_COLUMN].astype(int))
        elapsed = time.perf_counter() - started
    probabilities = np.asarray(
        pipeline.predict_proba(evaluation.loc[:, contract.inputs])[:, 1], dtype=float
    )
    probability_metrics = asdict(evaluate_probabilities(evaluation, probabilities))
    ranking = ranking_metrics(evaluation, probabilities)
    metrics = {
        name: float(probability_metrics[name])
        for name in (
            "macro_log_loss",
            "macro_brier",
            "micro_log_loss",
            "micro_brier",
            "calibration_intercept",
            "calibration_slope",
        )
    }
    metrics.update({name: float(ranking[name]) for name in SECONDARY[-3:]})
    return metrics, elapsed, [str(item.message) for item in caught]


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for candidate in ("LR1", "LR1_PRIZE_BONUS_SIMPLIFIED"):
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
            if row["candidate"] == "LR1_PRIZE_BONUS_SIMPLIFIED"
            and row["fold_id"] == fold.fold_id
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


def _reference_reproduction(paths: ProjectPaths, rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload = json.loads((paths.root / REFERENCE_RESULT).read_text(encoding="utf-8"))
    reference = {
        row["fold_id"]: row
        for row in payload["fold_metrics"]
        if row["experiment_id"] == "LR1"
    }
    deltas: dict[str, dict[str, float]] = {}
    for row in rows:
        if row["candidate"] != "LR1":
            continue
        deltas[row["fold_id"]] = {
            metric: float(row[metric]) - float(reference[row["fold_id"]][metric])
            for metric in (*PRIMARY, *SECONDARY[:4])
        }
    if any(abs(value) > 1e-12 for fold in deltas.values() for value in fold.values()):
        raise ValueError(f"LR1 reference reproduction failed: {deltas}")
    return {"tolerance": 1e-12, "passed": True, "fold_deltas": deltas}


def run_prize_bonus_ablation(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project = paths or ProjectPaths.from_root()
    contract_payload = load_ablation_contract(project)
    contracts = candidate_contracts(project)
    databases = resolve_experiment_database_paths(paths=project)
    protected_paths = {
        "source_database": databases.source,
        "experiment_database": databases.experiment,
        "lr1_registry": project.root / "docs/post-baseline-v2-relative-r1-registry.csv",
        "lr1_code": project.root / "src/kra_analytics/relative_features.py",
        "lr1_reference_result": project.root / REFERENCE_RESULT,
        "sealed_contract": project.root / CONTRACT_PATH,
    }
    before = {name: _sha256_file(path) for name, path in protected_paths.items()}
    frame = _load_frame(project, contracts["LR1"])
    if frame["race_date"].max().isoformat() >= "2024-07-01":
        raise ValueError("Development boundary violation")
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
        for candidate, contract in contracts.items():
            metrics, elapsed, caught = _fit(train, evaluation, contract)
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
        "development_rows": len(frame),
        "development_races": int(frame["race_id"].nunique()),
        "date_min": str(frame["race_date"].min()),
        "date_max": str(frame["race_date"].max()),
        "candidates": [
            {
                "candidate": name,
                "feature_count": len(contract.inputs),
                "feature_hash": contract.feature_hash,
                "features": list(contract.inputs),
            }
            for name, contract in contracts.items()
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
    print(json.dumps(run_prize_bonus_ablation(), ensure_ascii=False, indent=2))
