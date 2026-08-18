from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import (
    DEVELOPMENT_FOLDS,
    _fold_frames,
    verify_sealed_artifacts,
)
from kra_analytics.feature_bundle_experiment import (
    METRICS,
    _candidate_contracts,
    _fit_candidate,
    _load_development_frame,
)
from kra_analytics.feature_bundles import BUNDLE_FEATURES
from kra_analytics.modeling_v2 import V2FeatureContract
from kra_analytics.paths import ProjectPaths

EXPERIMENT_VERSION = "post_baseline_v2_f1_f3_combination_development_v1"
CANDIDATES = ("B0", "F1", "F3", "F1+F3")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _combined_contract(paths: ProjectPaths) -> dict[str, V2FeatureContract]:
    contracts = _candidate_contracts(paths)
    base = contracts["B0"]
    additions = BUNDLE_FEATURES["F1"] + BUNDLE_FEATURES["F3"]
    inputs = base.inputs + additions
    contracts["F1+F3"] = V2FeatureContract(
        inputs=inputs,
        categorical=base.categorical,
        numeric=base.numeric + additions,
        zero_count=contracts["F1"].zero_count,
        feature_hash=hashlib.sha256(("\n".join(inputs) + "\n").encode()).hexdigest(),
    )
    return {name: contracts[name] for name in CANDIDATES}


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for experiment_id in CANDIDATES:
        selected = [row for row in rows if row["experiment_id"] == experiment_id]
        summary: dict[str, Any] = {"experiment_id": experiment_id, "folds": len(selected)}
        for metric in (*METRICS, "fit_seconds"):
            values = np.asarray([row[metric] for row in selected], dtype=float)
            summary[f"{metric}_mean"] = float(values.mean())
            summary[f"{metric}_std"] = float(values.std(ddof=0))
        results.append(summary)
    return results


def _deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for fold_id in (spec.fold_id for spec in DEVELOPMENT_FOLDS):
        references = {
            name: next(
                row
                for row in rows
                if row["experiment_id"] == name and row["fold_id"] == fold_id
            )
            for name in ("B0", "F1", "F3")
        }
        combo = next(
            row
            for row in rows
            if row["experiment_id"] == "F1+F3" and row["fold_id"] == fold_id
        )
        for reference, row in references.items():
            results.append(
                {
                    "experiment_id": "F1+F3",
                    "reference": reference,
                    "fold_id": fold_id,
                    **{
                        f"delta_{metric}": float(combo[metric]) - float(row[metric])
                        for metric in METRICS
                    },
                }
            )
    return results


def _decision(
    summaries: list[dict[str, Any]], deltas: list[dict[str, Any]]
) -> dict[str, Any]:
    combo = next(row for row in summaries if row["experiment_id"] == "F1+F3")
    f3 = next(row for row in summaries if row["experiment_id"] == "F3")
    against_f3 = [row for row in deltas if row["reference"] == "F3"]
    ll_delta = float(combo["macro_log_loss_mean"]) - float(f3["macro_log_loss_mean"])
    brier_delta = float(combo["macro_brier_mean"]) - float(f3["macro_brier_mean"])
    ll_improved = sum(float(row["delta_macro_log_loss"]) < 0 for row in against_f3)
    brier_improved = sum(float(row["delta_macro_brier"]) < 0 for row in against_f3)
    if ll_delta < 0 and brier_delta < 0 and ll_improved >= 3 and brier_improved >= 3:
        selected = "F1+F3"
        judgement = "KEEP_COMBINATION"
        reason = "combination improves both primary means and at least 3/4 folds versus F3"
    else:
        selected = "F3"
        judgement = "PREFER_SIMPLER_F3"
        reason = "F1 does not retain sufficiently repeated incremental value beyond F3"
    return {
        "judgement": judgement,
        "selected_development_candidate": selected,
        "delta_vs_f3_macro_log_loss_mean": ll_delta,
        "delta_vs_f3_macro_brier_mean": brier_delta,
        "macro_log_loss_improved_folds_vs_f3": ll_improved,
        "macro_brier_improved_folds_vs_f3": brier_improved,
        "reason": reason,
    }


def run_f1_f3_combination_experiment(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contracts = _combined_contract(project_paths)
    frame = _load_development_frame(project_paths, contracts)
    protection = json.loads(
        (project_paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    sealed_before = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_paths = {
        "m1": project_paths.exports / "modeling/m1_histgradientboosting_development_v1/result.json",
        "bundle_result": project_paths.exports
        / "modeling/post_baseline_v2_feature_bundle_development_v1/result.json",
        "feature_code": project_paths.root / "src/kra_analytics/feature_bundles.py",
    }
    before = {
        name: _sha256_file(path)
        for name, path in protected_paths.items()
    }
    rows: list[dict[str, Any]] = []
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
                "evaluation_rows": len(evaluation),
                "strict_temporal_ordering": bool(
                    train["race_date"].max() < evaluation["race_date"].min()
                ),
                "preprocessing_fit_scope": "fold_train_only",
            }
        )
        for experiment_id in CANDIDATES:
            metrics, _, fit_seconds, warning_messages = _fit_candidate(
                train=train,
                evaluation=evaluation,
                contract=contracts[experiment_id],
            )
            rows.append(
                {
                    "experiment_id": experiment_id,
                    "fold_id": spec.fold_id,
                    **metrics,
                    "fit_seconds": fit_seconds,
                    "warning_count": len(warning_messages),
                }
            )
    summaries = _summaries(rows)
    deltas = _deltas(rows)
    decision = _decision(summaries, deltas)
    sealed_after = verify_sealed_artifacts(project_paths, protection["artifacts"])
    after = {
        name: _sha256_file(path)
        for name, path in protected_paths.items()
    }
    if sealed_before != sealed_after or before != after:
        raise ValueError("A protected artifact changed during the combination experiment")

    output = project_paths.exports / f"modeling/{EXPERIMENT_VERSION}"
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output / "fold_metrics.csv", index=False)
    pd.DataFrame(summaries).to_csv(output / "summary_metrics.csv", index=False)
    pd.DataFrame(deltas).to_csv(output / "fold_deltas.csv", index=False)
    registry = {
        "experiment_version": EXPERIMENT_VERSION,
        "development_window": ["2023-01-01", "2024-06-30"],
        "validation_access_count": 0,
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
        "validation_or_later_rows_loaded": False,
        "protected_artifacts_unchanged": True,
        "sealed_artifact_hashes": sealed_after,
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
