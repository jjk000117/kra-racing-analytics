from __future__ import annotations

import hashlib
import json
import time
import warnings
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.database import connect_database
from kra_analytics.development_evaluation import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_FOLDS,
    DEVELOPMENT_START,
    _fold_frames,
    verify_sealed_artifacts,
)
from kra_analytics.feature_bundles import BUNDLE_FEATURES, ENGINEERED_TABLE
from kra_analytics.modeling import evaluate_probabilities
from kra_analytics.modeling_v2 import (
    TARGET_COLUMN,
    V2FeatureContract,
    build_v2_pipeline,
    load_feature_contract,
)
from kra_analytics.paths import ProjectPaths

EXPERIMENT_VERSION = "post_baseline_v2_feature_bundle_development_v1"
BUNDLE_IDS = ("B0", "F1", "F2", "F3")
BUNDLE_COUNT_FEATURES = {
    name
    for bundle in ("F1", "F2")
    for name in BUNDLE_FEATURES[bundle]
    if name.endswith("_count")
}
METRICS = (
    "macro_log_loss",
    "macro_brier",
    "micro_log_loss",
    "micro_brier",
    "calibration_intercept",
    "calibration_slope",
)


def _feature_hash(features: tuple[str, ...]) -> str:
    return hashlib.sha256(("\n".join(features) + "\n").encode()).hexdigest()


def _candidate_contracts(paths: ProjectPaths) -> dict[str, V2FeatureContract]:
    base = load_feature_contract(paths)
    contracts = {"B0": base}
    for bundle in ("F1", "F2", "F3"):
        additions = BUNDLE_FEATURES[bundle]
        inputs = base.inputs + additions
        numeric = base.numeric + additions
        zero_count = base.zero_count + tuple(
            name for name in additions if name in BUNDLE_COUNT_FEATURES
        )
        contracts[bundle] = V2FeatureContract(
            inputs=inputs,
            categorical=base.categorical,
            numeric=numeric,
            zero_count=zero_count,
            feature_hash=_feature_hash(inputs),
        )
    return contracts


def _load_development_frame(
    paths: ProjectPaths, contracts: dict[str, V2FeatureContract]
) -> pd.DataFrame:
    all_features = tuple(dict.fromkeys(contracts["B0"].inputs + sum(BUNDLE_FEATURES.values(), ())))
    columns = ("race_id", "horse_id", "race_date", *all_features, TARGET_COLUMN)
    query = f"""
        SELECT {", ".join(columns)} FROM {ENGINEERED_TABLE}
        WHERE race_date >= ? AND race_date < ?
        ORDER BY race_date, race_id, horse_id
    """
    with connect_database(paths=paths, read_only=True) as connection:
        frame = connection.execute(
            query, [DEVELOPMENT_START, DEVELOPMENT_END_EXCLUSIVE]
        ).fetchdf()
    frame["race_date"] = pd.to_datetime(frame["race_date"]).dt.date
    if frame.empty or frame["race_date"].min() < DEVELOPMENT_START:
        raise ValueError("Development Feature-bundle loader returned an invalid start")
    if frame["race_date"].max() >= DEVELOPMENT_END_EXCLUSIVE:
        raise ValueError("Development loader crossed the 2024-07-01 boundary")
    if frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate development race/horse keys")
    return frame


def _metric_payload(frame: pd.DataFrame, probabilities: np.ndarray) -> dict[str, float]:
    result = asdict(evaluate_probabilities(frame, probabilities))
    return {name: float(result[name]) for name in METRICS}


def _fit_candidate(
    *, train: pd.DataFrame, evaluation: pd.DataFrame, contract: V2FeatureContract
) -> tuple[dict[str, float], np.ndarray, float, list[str]]:
    pipeline = build_v2_pipeline(contract)
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


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for experiment_id in BUNDLE_IDS:
        selected = [row for row in rows if row["experiment_id"] == experiment_id]
        summary: dict[str, Any] = {"experiment_id": experiment_id, "folds": len(selected)}
        for metric in (*METRICS, "fit_seconds"):
            values = np.asarray([row[metric] for row in selected], dtype=float)
            summary[f"{metric}_mean"] = float(values.mean())
            summary[f"{metric}_std"] = float(values.std(ddof=0))
        summaries.append(summary)
    base = next(row for row in summaries if row["experiment_id"] == "B0")
    for row in summaries:
        for metric in METRICS[:4]:
            row[f"delta_vs_b0_{metric}_mean"] = (
                float(row[f"{metric}_mean"]) - float(base[f"{metric}_mean"])
            )
    return summaries


def _fold_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for fold in (spec.fold_id for spec in DEVELOPMENT_FOLDS):
        base = next(
            row for row in rows if row["experiment_id"] == "B0" and row["fold_id"] == fold
        )
        for experiment_id in ("F1", "F2", "F3"):
            candidate = next(
                row
                for row in rows
                if row["experiment_id"] == experiment_id and row["fold_id"] == fold
            )
            results.append(
                {
                    "experiment_id": experiment_id,
                    "fold_id": fold,
                    **{
                        f"delta_{metric}": float(candidate[metric]) - float(base[metric])
                        for metric in METRICS
                    },
                }
            )
    return results


def _availability_diagnostic(
    *, evaluation: pd.DataFrame, probabilities: np.ndarray, bundle: str, fold_id: str
) -> list[dict[str, Any]]:
    if bundle == "B0":
        return []
    value_features = [
        name for name in BUNDLE_FEATURES[bundle] if name not in BUNDLE_COUNT_FEATURES
    ]
    missing = evaluation.loc[:, value_features].isna().any(axis=1)
    rows: list[dict[str, Any]] = []
    groups = (
        ("any_bundle_value_missing", missing),
        ("all_bundle_values_available", ~missing),
    )
    for label, mask in groups:
        subset = evaluation.loc[mask]
        if subset.empty:
            continue
        metric = _metric_payload(subset, probabilities[mask.to_numpy()])
        rows.append(
            {
                "experiment_id": bundle,
                "fold_id": fold_id,
                "availability_group": label,
                "rows": len(subset),
                "races": int(subset["race_id"].nunique()),
                "row_rate": float(mask.mean()),
                **metric,
            }
        )
    return rows


def _judgements(
    summaries: list[dict[str, Any]], deltas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for experiment_id in ("F1", "F2", "F3"):
        summary = next(row for row in summaries if row["experiment_id"] == experiment_id)
        candidate = [row for row in deltas if row["experiment_id"] == experiment_id]
        ll_improved = sum(row["delta_macro_log_loss"] < 0 for row in candidate)
        brier_improved = sum(row["delta_macro_brier"] < 0 for row in candidate)
        mean_ll = float(summary["delta_vs_b0_macro_log_loss_mean"])
        mean_brier = float(summary["delta_vs_b0_macro_brier_mean"])
        if mean_ll < 0 and mean_brier < 0 and ll_improved >= 3 and brier_improved >= 3:
            judgement = "KEEP"
            reason = "both primary means improved and improvement repeated in at least 3/4 folds"
        elif mean_ll < 0 or mean_brier < 0:
            judgement = "CONDITIONAL"
            reason = "mean or fold directions were mixed"
        else:
            judgement = "DROP"
            reason = "neither primary metric improved on average"
        results.append(
            {
                "experiment_id": experiment_id,
                "judgement": judgement,
                "macro_log_loss_improved_folds": ll_improved,
                "macro_brier_improved_folds": brier_improved,
                "reason": reason,
            }
        )
    return results


def run_feature_bundle_development_experiment(
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contracts = _candidate_contracts(project_paths)
    frame = _load_development_frame(project_paths, contracts)
    protection = json.loads(
        (project_paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    sealed_before = verify_sealed_artifacts(project_paths, protection["artifacts"])
    m1_path = project_paths.exports / "modeling/m1_histgradientboosting_development_v1/result.json"
    m1_hash_before = hashlib.sha256(m1_path.read_bytes()).hexdigest()

    fold_rows: list[dict[str, Any]] = []
    availability_rows: list[dict[str, Any]] = []
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
        for experiment_id in BUNDLE_IDS:
            contract = contracts[experiment_id]
            metrics, probabilities, fit_seconds, warning_messages = _fit_candidate(
                train=train, evaluation=evaluation, contract=contract
            )
            fold_rows.append(
                {
                    "experiment_id": experiment_id,
                    "fold_id": spec.fold_id,
                    **metrics,
                    "fit_seconds": fit_seconds,
                    "warning_count": len(warning_messages),
                    "warning_messages": warning_messages,
                }
            )
            availability_rows.extend(
                _availability_diagnostic(
                    evaluation=evaluation,
                    probabilities=probabilities,
                    bundle=experiment_id,
                    fold_id=spec.fold_id,
                )
            )

    summaries = _summaries(fold_rows)
    deltas = _fold_deltas(fold_rows)
    judgements = _judgements(summaries, deltas)
    sealed_after = verify_sealed_artifacts(project_paths, protection["artifacts"])
    if sealed_before != sealed_after:
        raise ValueError("Sealed baseline artifacts changed")
    if hashlib.sha256(m1_path.read_bytes()).hexdigest() != m1_hash_before:
        raise ValueError("M1 result changed")

    output = project_paths.exports / f"modeling/{EXPERIMENT_VERSION}"
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(fold_rows).drop(columns="warning_messages").to_csv(
        output / "fold_metrics.csv", index=False
    )
    pd.DataFrame(summaries).to_csv(output / "summary_metrics.csv", index=False)
    pd.DataFrame(deltas).to_csv(output / "fold_deltas_vs_b0.csv", index=False)
    pd.DataFrame(availability_rows).to_csv(
        output / "availability_diagnostics.csv", index=False
    )
    registry = {
        "experiment_version": EXPERIMENT_VERSION,
        "development_window": ["2023-01-01", "2024-06-30"],
        "validation_access_count": 0,
        "model_family": "LogisticRegression",
        "preprocessing": "official_v2; fold-train only; bundle counts zero; other numeric median",
        "candidates": [
            {
                "experiment_id": experiment_id,
                "feature_count": len(contracts[experiment_id].inputs),
                "feature_hash": contracts[experiment_id].feature_hash,
                "added_features": list(BUNDLE_FEATURES.get(experiment_id, ())),
                "fold_metrics": [
                    row for row in fold_rows if row["experiment_id"] == experiment_id
                ],
                "summary": next(
                    row for row in summaries if row["experiment_id"] == experiment_id
                ),
                "judgement": next(
                    (row for row in judgements if row["experiment_id"] == experiment_id),
                    None,
                ),
            }
            for experiment_id in BUNDLE_IDS
        ],
    }
    (output / "experiment_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = {
        **registry,
        "development_rows": len(frame),
        "development_races": int(frame["race_id"].nunique()),
        "fold_context": fold_context,
        "fold_deltas": deltas,
        "availability_diagnostics": availability_rows,
        "judgements": judgements,
        "sealed_artifacts_unchanged": True,
        "sealed_artifact_hashes": sealed_after,
        "m1_result_unchanged": True,
        "validation_or_later_rows_loaded": False,
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
