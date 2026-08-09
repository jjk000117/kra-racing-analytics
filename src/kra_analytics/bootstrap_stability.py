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
    EPSILON,
    MODEL_INPUTS,
    SEALED_CONTRACT_SHA256,
    SEALED_PIPELINE_SHA256,
    TARGET_COLUMN,
    TRAIN_START,
    build_model_pipeline,
)
from kra_analytics.paths import ProjectPaths

ANALYSIS_VERSION = "bootstrap_stability_diagnostic_v1"
STABLE_MONTHS = tuple(str(month) for month in pd.period_range("2025-10", "2026-04", freq="M"))
DEGRADED_MONTHS = ("2026-05", "2026-06", "2026-07")
BOOTSTRAP_REPETITIONS = 10_000
RANDOM_SEED = 20260809
QUANTILES = (0.025, 0.05, 0.25, 0.5, 0.75, 0.95, 0.975)


@dataclass(frozen=True)
class BootstrapStabilityOutcome:
    analysis_version: str
    stable_races: int
    repetitions: int
    result_path: Path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def race_level_losses(
    frame: pd.DataFrame, probabilities: np.ndarray
) -> pd.DataFrame:
    """Return the race means whose means are the macro Log Loss and Brier."""
    target = frame[TARGET_COLUMN].to_numpy(dtype=float)
    clipped = np.clip(np.asarray(probabilities, dtype=float), EPSILON, 1.0 - EPSILON)
    working = pd.DataFrame(
        {
            "race_id": frame["race_id"].to_numpy(),
            "log_loss": -(target * np.log(clipped) + (1.0 - target) * np.log(1.0 - clipped)),
            "brier": np.square(clipped - target),
        }
    )
    return working.groupby("race_id", sort=False, as_index=False)[["log_loss", "brier"]].mean()


def bootstrap_means(
    values: np.ndarray,
    sample_size: int,
    *,
    repetitions: int,
    rng: np.random.Generator,
) -> np.ndarray:
    indices = rng.integers(0, len(values), size=(repetitions, sample_size))
    return np.asarray(values, dtype=float)[indices].mean(axis=1)


def summarize_bootstrap(distribution: np.ndarray, actual: float) -> dict[str, float]:
    percentiles = np.quantile(distribution, QUANTILES)
    return {
        "bootstrap_mean": float(np.mean(distribution)),
        "bootstrap_median": float(percentiles[3]),
        "p2_5": float(percentiles[0]),
        "p5": float(percentiles[1]),
        "p25": float(percentiles[2]),
        "p75": float(percentiles[4]),
        "p95": float(percentiles[5]),
        "p97_5": float(percentiles[6]),
        "actual": float(actual),
        "empirical_equal_or_worse_rate": float(np.mean(distribution >= actual)),
    }


def _load_snapshot(paths: ProjectPaths) -> pd.DataFrame:
    columns = ("race_id", "horse_id", "race_date", *MODEL_FEATURES, TARGET_COLUMN)
    query = f"""
        SELECT {", ".join(columns)}
        FROM mart.feature_snapshot_place
        WHERE snapshot_version = ?
          AND race_date >= ?
          AND race_date < ?
        ORDER BY race_date, race_id, horse_id
    """
    with connect_database(paths=paths, read_only=True) as connection:
        frame = connection.execute(
            query, [SNAPSHOT_VERSION, TRAIN_START, "2026-05-01"]
        ).fetchdf()
    if frame.empty or frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Bootstrap Snapshot is empty or has duplicate business keys")
    frame["race_date"] = pd.to_datetime(frame["race_date"])
    return frame


def _reproduce_stable_race_losses(
    frame: pd.DataFrame, existing_folds: dict[str, dict[str, Any]]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    race_rows: list[pd.DataFrame] = []
    checks: list[dict[str, Any]] = []
    for month_key in STABLE_MONTHS:
        month = pd.Period(month_key, freq="M")
        start = month.start_time
        end = (month + 1).start_time
        train = frame.loc[
            (frame["race_date"] >= pd.Timestamp(TRAIN_START))
            & (frame["race_date"] < start)
        ]
        evaluation = frame.loc[(frame["race_date"] >= start) & (frame["race_date"] < end)]
        pipeline = build_model_pipeline()
        pipeline.fit(train.loc[:, MODEL_INPUTS], train[TARGET_COLUMN].astype(int))
        probabilities = np.asarray(
            pipeline.predict_proba(evaluation.loc[:, MODEL_INPUTS])[:, 1], dtype=float
        )
        losses = race_level_losses(evaluation, probabilities)
        losses["evaluation_month"] = month_key
        expected = existing_folds[month_key]
        observed_log_loss = float(losses["log_loss"].mean())
        observed_brier = float(losses["brier"].mean())
        log_difference = observed_log_loss - float(expected["model_macro_log_loss"])
        brier_difference = observed_brier - float(expected["model_macro_brier"])
        if int(expected["evaluation_races"]) != len(losses):
            raise ValueError(f"Stable fold race count mismatch for {month_key}")
        if abs(log_difference) > 1e-12 or abs(brier_difference) > 1e-12:
            raise ValueError(f"Stable fold metric reproduction mismatch for {month_key}")
        checks.append(
            {
                "evaluation_month": month_key,
                "races": len(losses),
                "macro_log_loss_absolute_difference": abs(log_difference),
                "macro_brier_absolute_difference": abs(brier_difference),
            }
        )
        race_rows.append(losses)
    return pd.concat(race_rows, ignore_index=True), checks


def run_bootstrap_stability_diagnostic(
    *, paths: ProjectPaths | None = None
) -> BootstrapStabilityOutcome:
    project_paths = paths or ProjectPaths.from_root()
    baseline = project_paths.exports / "modeling" / "place_logistic_baseline_v1"
    walk = project_paths.exports / "modeling" / "walk_forward_stability_v1"
    drift = project_paths.exports / "modeling" / "feature_drift_diagnostic_v1"
    protected_paths = (
        baseline / "run_contract.json",
        baseline / "pipeline.joblib",
        baseline / "final_test_result.json",
        walk / "walk_forward_result.json",
        drift / "feature_drift_result.json",
    )
    hashes_before = {str(path): _file_sha256(path) for path in protected_paths}
    if hashes_before[str(baseline / "run_contract.json")] != SEALED_CONTRACT_SHA256:
        raise ValueError("Sealed run contract changed")
    if hashes_before[str(baseline / "pipeline.joblib")] != SEALED_PIPELINE_SHA256:
        raise ValueError("Sealed Pipeline changed")

    output_directory = project_paths.exports / "modeling" / ANALYSIS_VERSION
    result_path = output_directory / "bootstrap_result.json"
    if result_path.exists():
        raise FileExistsError("Bootstrap stability diagnostic result already exists")

    walk_result = json.loads((walk / "walk_forward_result.json").read_text(encoding="utf-8"))
    folds = {row["evaluation_month"]: row for row in walk_result["folds"]}
    frame = _load_snapshot(project_paths)
    stable_losses, reproduction_checks = _reproduce_stable_race_losses(frame, folds)

    rng = np.random.default_rng(RANDOM_SEED)
    monthly: dict[str, dict[str, Any]] = {}
    monthly_distributions: dict[str, dict[str, np.ndarray]] = {}
    for month in DEGRADED_MONTHS:
        fold = folds[month]
        sample_size = int(fold["evaluation_races"])
        log_distribution = bootstrap_means(
            stable_losses["log_loss"].to_numpy(),
            sample_size,
            repetitions=BOOTSTRAP_REPETITIONS,
            rng=rng,
        )
        brier_distribution = bootstrap_means(
            stable_losses["brier"].to_numpy(),
            sample_size,
            repetitions=BOOTSTRAP_REPETITIONS,
            rng=rng,
        )
        monthly_distributions[month] = {
            "macro_log_loss": log_distribution,
            "macro_brier": brier_distribution,
        }
        monthly[month] = {
            "sample_races": sample_size,
            "macro_log_loss": summarize_bootstrap(
                log_distribution, float(fold["model_macro_log_loss"])
            ),
            "macro_brier": summarize_bootstrap(
                brier_distribution, float(fold["model_macro_brier"])
            ),
        }

    actual_three_month_log = float(
        np.mean([folds[month]["model_macro_log_loss"] for month in DEGRADED_MONTHS])
    )
    actual_three_month_brier = float(
        np.mean([folds[month]["model_macro_brier"] for month in DEGRADED_MONTHS])
    )
    three_month_log = np.mean(
        [monthly_distributions[month]["macro_log_loss"] for month in DEGRADED_MONTHS],
        axis=0,
    )
    three_month_brier = np.mean(
        [monthly_distributions[month]["macro_brier"] for month in DEGRADED_MONTHS],
        axis=0,
    )

    hashes_after = {str(path): _file_sha256(path) for path in protected_paths}
    if hashes_before != hashes_after:
        raise ValueError("Protected analysis artifact changed during bootstrap diagnostic")

    result = {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_purpose": "RACE_LEVEL_SAMPLING_VARIATION_DIAGNOSTIC_ONLY",
        "stable_period": ["2025-10-01", "2026-04-30"],
        "observed_degraded_period": ["2026-05-01", "2026-07-31"],
        "stable_race_population": len(stable_losses),
        "bootstrap_unit": "RACE",
        "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
        "random_seed": RANDOM_SEED,
        "sampling": "with_replacement_from_pooled_stable_period_race_losses",
        "tail_definition": "fraction_of_bootstrap_metrics_greater_than_or_equal_to_actual",
        "tail_interpretation": "EMPIRICAL_REFERENCE_RATE_NOT_AN_INDEPENDENT_SAMPLE_P_VALUE",
        "stable_fold_metric_reproduction": reproduction_checks,
        "monthly": monthly,
        "three_month_equal_month_weighted_average": {
            "month_sample_races": {
                month: int(folds[month]["evaluation_races"]) for month in DEGRADED_MONTHS
            },
            "macro_log_loss": summarize_bootstrap(three_month_log, actual_three_month_log),
            "macro_brier": summarize_bootstrap(three_month_brier, actual_three_month_brier),
            "limitation": "monthly sample sizes preserved; calendar order and continuity ignored",
        },
        "limitations": [
            "stable reference covers only seven calendar months",
            "monthly race composition is not held constant",
            (
                "pooled race bootstrap ignores calendar order, serial dependence, "
                "and repeated entities"
            ),
            "expanding walk-forward refits a different updated model each month",
            (
                "diagnostic compares observed losses only with stable-period "
                "race-level sampling variation"
            ),
        ],
        "model_feature_or_calibration_change_performed": False,
        "final_test_evaluation_performed": False,
        "protected_artifact_hashes_before_after": hashes_before,
        "protected_artifacts_modified": False,
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return BootstrapStabilityOutcome(
        analysis_version=ANALYSIS_VERSION,
        stable_races=len(stable_losses),
        repetitions=BOOTSTRAP_REPETITIONS,
        result_path=result_path,
    )
