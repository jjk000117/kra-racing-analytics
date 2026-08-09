from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.database import connect_database
from kra_analytics.feature_snapshot import MODEL_FEATURES, SNAPSHOT_VERSION
from kra_analytics.modeling import (
    FINAL_TEST_END,
    MODEL_INPUTS,
    SEALED_CONTRACT_SHA256,
    SEALED_PIPELINE_SHA256,
    TARGET_COLUMN,
    TRAIN_START,
    build_model_pipeline,
    calibration_table,
    evaluate_probabilities,
)
from kra_analytics.paths import ProjectPaths

ANALYSIS_VERSION = "walk_forward_stability_v1"
FIRST_EVALUATION_MONTH = pd.Period("2025-10", freq="M")
LAST_EVALUATION_MONTH = pd.Period("2026-07", freq="M")


@dataclass(frozen=True)
class WalkForwardOutcome:
    analysis_version: str
    fold_count: int
    first_evaluation_month: str
    last_evaluation_month: str
    result_path: Path


def evaluation_months() -> tuple[pd.Period, ...]:
    return tuple(pd.period_range(FIRST_EVALUATION_MONTH, LAST_EVALUATION_MONTH, freq="M"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_analysis_snapshot(*, paths: ProjectPaths) -> pd.DataFrame:
    columns = ("race_id", "horse_id", "race_date", *MODEL_FEATURES, TARGET_COLUMN)
    query = f"""
        SELECT {", ".join(columns)}
        FROM mart.feature_snapshot_place
        WHERE snapshot_version = ?
          AND race_date >= ?
          AND race_date <= ?
        ORDER BY race_date, race_id, horse_id
    """
    with connect_database(paths=paths, read_only=True) as connection:
        frame = connection.execute(
            query, [SNAPSHOT_VERSION, TRAIN_START, FINAL_TEST_END]
        ).fetchdf()
    if frame.empty or frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Walk-forward Snapshot is empty or has duplicate business keys")
    return frame


def add_auxiliary_three_month_averages(rows: list[dict[str, Any]]) -> None:
    """Add descriptive moving averages; these fields never select or alter a model."""
    fields = (
        "model_macro_log_loss",
        "model_macro_brier",
        "calibration_intercept",
        "calibration_slope",
    )
    for index, row in enumerate(rows):
        for field in fields:
            values = [rows[position][field] for position in range(max(0, index - 2), index + 1)]
            key = f"auxiliary_3m_mean_{field}"
            row[key] = float(np.mean(values)) if len(values) == 3 else None


def run_walk_forward_stability(*, paths: ProjectPaths | None = None) -> WalkForwardOutcome:
    project_paths = paths or ProjectPaths.from_root()
    baseline_directory = project_paths.exports / "modeling" / "place_logistic_baseline_v1"
    contract_path = baseline_directory / "run_contract.json"
    pipeline_path = baseline_directory / "pipeline.joblib"
    final_result_path = baseline_directory / "final_test_result.json"
    if _file_sha256(contract_path) != SEALED_CONTRACT_SHA256:
        raise ValueError("Baseline run contract changed before walk-forward analysis")
    if _file_sha256(pipeline_path) != SEALED_PIPELINE_SHA256:
        raise ValueError("Baseline Pipeline changed before walk-forward analysis")
    final_result_sha256 = _file_sha256(final_result_path)

    output_directory = project_paths.exports / "modeling" / ANALYSIS_VERSION
    result_path = output_directory / "walk_forward_result.json"
    if result_path.exists():
        raise FileExistsError("Walk-forward stability analysis result already exists")

    frame = _load_analysis_snapshot(paths=project_paths)
    dates = pd.to_datetime(frame["race_date"])
    rows: list[dict[str, Any]] = []
    fold_calibration_tables: dict[str, list[dict[str, Any]]] = {}
    for month in evaluation_months():
        evaluation_start = month.start_time
        evaluation_end = (month + 1).start_time
        train = frame.loc[(dates >= pd.Timestamp(TRAIN_START)) & (dates < evaluation_start)]
        evaluation = frame.loc[(dates >= evaluation_start) & (dates < evaluation_end)]
        if train.empty or evaluation.empty:
            raise ValueError(f"Missing train or evaluation rows for {month}")
        if dates.loc[train.index].max() >= dates.loc[evaluation.index].min():
            raise ValueError(f"Temporal leakage in walk-forward fold {month}")

        pipeline = build_model_pipeline()
        pipeline.fit(train.loc[:, MODEL_INPUTS], train[TARGET_COLUMN].astype(int))
        probabilities = np.asarray(
            pipeline.predict_proba(evaluation.loc[:, MODEL_INPUTS])[:, 1], dtype=float
        )
        baseline_prevalence = float(train[TARGET_COLUMN].mean())
        baseline_probabilities = np.full(len(evaluation), baseline_prevalence)
        model_metrics = evaluate_probabilities(evaluation, probabilities)
        baseline_metrics = evaluate_probabilities(evaluation, baseline_probabilities)
        model = pipeline.named_steps["model"]
        converged = bool(np.max(model.n_iter_) < model.max_iter)
        month_key = str(month)
        fold_calibration_tables[month_key] = calibration_table(
            evaluation, probabilities, bins=5
        )
        rows.append(
            {
                "evaluation_month": month_key,
                "train_start": str(dates.loc[train.index].min().date()),
                "train_end": str(dates.loc[train.index].max().date()),
                "evaluation_start": str(dates.loc[evaluation.index].min().date()),
                "evaluation_end": str(dates.loc[evaluation.index].max().date()),
                "train_rows": len(train),
                "train_races": int(train["race_id"].nunique()),
                "evaluation_rows": len(evaluation),
                "evaluation_races": int(evaluation["race_id"].nunique()),
                "horse_history_available_rate": float(
                    evaluation["horse_history_available"].mean()
                ),
                "model_macro_log_loss": model_metrics.macro_log_loss,
                "model_macro_brier": model_metrics.macro_brier,
                "model_micro_log_loss": model_metrics.micro_log_loss,
                "model_micro_brier": model_metrics.micro_brier,
                "baseline_macro_log_loss": baseline_metrics.macro_log_loss,
                "baseline_macro_brier": baseline_metrics.macro_brier,
                "baseline_micro_log_loss": baseline_metrics.micro_log_loss,
                "baseline_micro_brier": baseline_metrics.micro_brier,
                "macro_log_loss_improvement_vs_baseline": (
                    baseline_metrics.macro_log_loss - model_metrics.macro_log_loss
                ),
                "macro_brier_improvement_vs_baseline": (
                    baseline_metrics.macro_brier - model_metrics.macro_brier
                ),
                "mean_predicted_probability": float(probabilities.mean()),
                "observed_positive_rate": model_metrics.positive_rate,
                "observed_minus_predicted": (
                    model_metrics.positive_rate - float(probabilities.mean())
                ),
                "calibration_intercept": model_metrics.calibration_intercept,
                "calibration_slope": model_metrics.calibration_slope,
                "probability_min": model_metrics.probability_min,
                "probability_max": model_metrics.probability_max,
                "null_probability_count": int(np.isnan(probabilities).sum()),
                "infinite_probability_count": int(np.isinf(probabilities).sum()),
                "model_converged": converged,
            }
        )

    add_auxiliary_three_month_averages(rows)
    if _file_sha256(contract_path) != SEALED_CONTRACT_SHA256:
        raise ValueError("Baseline run contract changed during walk-forward analysis")
    if _file_sha256(pipeline_path) != SEALED_PIPELINE_SHA256:
        raise ValueError("Baseline Pipeline changed during walk-forward analysis")
    if _file_sha256(final_result_path) != final_result_sha256:
        raise ValueError("Baseline Final Test result changed during walk-forward analysis")

    output_directory.mkdir(parents=True, exist_ok=True)
    result = {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_purpose": "TIME_STABILITY_DIAGNOSTIC_ONLY",
        "baseline_model_version": "place_logistic_baseline_v1",
        "model_inputs": MODEL_INPUTS,
        "procedure": "raw_logistic_same_fixed_parameters_refit_each_fold",
        "first_training_period": "2024-10-01_to_2025-09-30",
        "warmup_feature_history_inherited": True,
        "training_window": "expanding_all_prior_rows_from_2024-10",
        "evaluation_window": "one_calendar_month",
        "fold_count": len(rows),
        "auxiliary_three_month_average_role": "DIAGNOSTIC_ONLY_NOT_A_TREND_DECISION_RULE",
        "baseline_contract_sha256_before_after": SEALED_CONTRACT_SHA256,
        "baseline_pipeline_sha256_before_after": SEALED_PIPELINE_SHA256,
        "baseline_final_result_sha256_before_after": final_result_sha256,
        "folds": rows,
        "calibration_tables_5_quantiles": fold_calibration_tables,
        "baseline_artifacts_modified": False,
        "feature_or_model_selection_performed": False,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return WalkForwardOutcome(
        analysis_version=ANALYSIS_VERSION,
        fold_count=len(rows),
        first_evaluation_month=rows[0]["evaluation_month"],
        last_evaluation_month=rows[-1]["evaluation_month"],
        result_path=result_path,
    )
