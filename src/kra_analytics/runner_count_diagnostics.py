from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from kra_analytics.bootstrap_stability import (
    DEGRADED_MONTHS,
    STABLE_MONTHS,
    load_analysis_snapshot,
    reproduce_race_losses,
)
from kra_analytics.paths import ProjectPaths

ANALYSIS_VERSION = "runner_count_loss_diagnostic_v1"
METRICS = ("log_loss", "brier")


@dataclass(frozen=True)
class RunnerCountDiagnosticOutcome:
    analysis_version: str
    stable_races: int
    degraded_races: int
    result_path: Path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_segments(race_losses: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for runner_count, group in race_losses.groupby("registered_runner_count", sort=True):
        row: dict[str, Any] = {"registered_runner_count": int(str(runner_count))}
        for period in ("STABLE", "DEGRADED"):
            period_group = group.loc[group["period"] == period]
            total = int((race_losses["period"] == period).sum())
            macro_log_loss = (
                float(period_group["log_loss"].mean()) if len(period_group) else None
            )
            macro_brier = float(period_group["brier"].mean()) if len(period_group) else None
            row[period.lower()] = {
                "races": len(period_group),
                "share": len(period_group) / total,
                "macro_log_loss": macro_log_loss,
                "macro_brier": macro_brier,
            }
        stable_metric = row["stable"]
        degraded_metric = row["degraded"]
        row["degraded_minus_stable"] = {
            "share_percentage_points": 100
            * (row["degraded"]["share"] - row["stable"]["share"]),
            "macro_log_loss": (
                degraded_metric["macro_log_loss"] - stable_metric["macro_log_loss"]
                if degraded_metric["macro_log_loss"] is not None
                and stable_metric["macro_log_loss"] is not None
                else None
            ),
            "macro_brier": (
                degraded_metric["macro_brier"] - stable_metric["macro_brier"]
                if degraded_metric["macro_brier"] is not None
                and stable_metric["macro_brier"] is not None
                else None
            ),
        }
        rows.append(row)
    return rows


def decompose_metric(segment_rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    key = f"macro_{metric}"
    stable_actual = float(
        sum(
            row["stable"]["share"] * row["stable"][key]
            for row in segment_rows
            if row["stable"][key] is not None
        )
    )
    degraded_actual = float(
        sum(
            row["degraded"]["share"] * row["degraded"][key]
            for row in segment_rows
            if row["degraded"][key] is not None
        )
    )
    shared = [
        row
        for row in segment_rows
        if row["stable"][key] is not None and row["degraded"][key] is not None
    ]
    stable = np.array([row["stable"][key] for row in shared], dtype=float)
    degraded = np.array([row["degraded"][key] for row in shared], dtype=float)
    stable_weight_raw = np.array([row["stable"]["share"] for row in shared])
    degraded_weight_raw = np.array([row["degraded"]["share"] for row in shared])
    stable_common_mass = float(stable_weight_raw.sum())
    degraded_common_mass = float(degraded_weight_raw.sum())
    stable_weight = stable_weight_raw / stable_common_mass
    degraded_weight = degraded_weight_raw / degraded_common_mass
    stable_common = float(stable_weight @ stable)
    degraded_common = float(degraded_weight @ degraded)
    stable_losses_degraded_mix = float(degraded_weight @ stable)
    degraded_losses_stable_mix = float(stable_weight @ degraded)
    composition = float(0.5 * ((degraded_weight - stable_weight) @ (stable + degraded)))
    within = float(0.5 * ((degraded - stable) @ (stable_weight + degraded_weight)))
    segment_contributions = [
        {
            "registered_runner_count": row["registered_runner_count"],
            "composition_effect": float(
                0.5
                * (degraded_weight[index] - stable_weight[index])
                * (stable[index] + degraded[index])
            ),
            "within_segment_effect": float(
                0.5
                * (degraded[index] - stable[index])
                * (stable_weight[index] + degraded_weight[index])
            ),
        }
        for index, row in enumerate(shared)
    ]
    stable_exclusive_support_effect = stable_common - stable_actual
    degraded_exclusive_support_effect = degraded_actual - degraded_common
    total = degraded_actual - stable_actual
    residual = (
        total
        - stable_exclusive_support_effect
        - composition
        - within
        - degraded_exclusive_support_effect
    )
    if abs(residual) > 1e-12:
        raise ValueError(f"{metric} decomposition does not reconcile")
    return {
        "stable_actual": stable_actual,
        "degraded_actual": degraded_actual,
        "total_change": total,
        "shared_runner_count_count": len(shared),
        "stable_common_support_mass": stable_common_mass,
        "degraded_common_support_mass": degraded_common_mass,
        "stable_common_support_metric": stable_common,
        "degraded_common_support_metric": degraded_common,
        "stable_segment_losses_at_degraded_mix": stable_losses_degraded_mix,
        "degraded_segment_losses_at_stable_mix": degraded_losses_stable_mix,
        "symmetric_composition_effect": composition,
        "symmetric_within_segment_effect": within,
        "shared_segment_contributions": segment_contributions,
        "stable_exclusive_support_effect": stable_exclusive_support_effect,
        "degraded_exclusive_support_effect": degraded_exclusive_support_effect,
        "reconciliation_residual": residual,
    }


def monthly_segments(race_losses: pd.DataFrame) -> list[dict[str, Any]]:
    grouped = (
        race_losses.groupby(["evaluation_month", "registered_runner_count"], sort=True)
        .agg(
            races=("race_id", "size"),
            macro_log_loss=("log_loss", "mean"),
            macro_brier=("brier", "mean"),
        )
        .reset_index()
    )
    return cast(list[dict[str, Any]], grouped.to_dict(orient="records"))


def run_runner_count_loss_diagnostic(
    *, paths: ProjectPaths | None = None
) -> RunnerCountDiagnosticOutcome:
    project_paths = paths or ProjectPaths.from_root()
    modeling = project_paths.exports / "modeling"
    baseline = modeling / "place_logistic_baseline_v1"
    walk = modeling / "walk_forward_stability_v1"
    protected_paths = (
        baseline / "run_contract.json",
        baseline / "pipeline.joblib",
        baseline / "final_test_result.json",
        walk / "walk_forward_result.json",
        modeling / "feature_drift_diagnostic_v1" / "feature_drift_result.json",
        modeling / "bootstrap_stability_diagnostic_v1" / "bootstrap_result.json",
    )
    hashes_before = {str(path): _file_sha256(path) for path in protected_paths}
    output_directory = modeling / ANALYSIS_VERSION
    result_path = output_directory / "runner_count_loss_result.json"
    if result_path.exists():
        raise FileExistsError("Runner-count loss diagnostic result already exists")

    walk_result = json.loads((walk / "walk_forward_result.json").read_text(encoding="utf-8"))
    folds = {row["evaluation_month"]: row for row in walk_result["folds"]}
    frame = load_analysis_snapshot(project_paths, end_exclusive="2026-08-01")
    all_months = STABLE_MONTHS + DEGRADED_MONTHS
    race_losses, reproduction = reproduce_race_losses(frame, folds, all_months)
    race_losses["period"] = np.where(
        race_losses["evaluation_month"].isin(STABLE_MONTHS), "STABLE", "DEGRADED"
    )
    segments = summarize_segments(race_losses)
    decomposition = {metric: decompose_metric(segments, metric) for metric in METRICS}

    hashes_after = {str(path): _file_sha256(path) for path in protected_paths}
    if hashes_before != hashes_after:
        raise ValueError("Protected artifact changed during runner-count diagnostic")
    output_directory.mkdir(parents=True, exist_ok=True)
    stable_races = int((race_losses["period"] == "STABLE").sum())
    degraded_races = int((race_losses["period"] == "DEGRADED").sum())
    result = {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_purpose": "RUNNER_COUNT_COMPOSITION_AND_WITHIN_SEGMENT_LOSS_DIAGNOSTIC_ONLY",
        "stable_period": ["2025-10-01", "2026-04-30"],
        "degraded_period": ["2026-05-01", "2026-07-31"],
        "analysis_grain": "RACE",
        "stable_races": stable_races,
        "degraded_races": degraded_races,
        "segment_summary": segments,
        "monthly_segment_summary": monthly_segments(race_losses),
        "decomposition": decomposition,
        "decomposition_definition": (
            "common-support symmetric two-factor decomposition plus explicit exclusive-"
            "support bridge effects; all effects sum exactly to pooled macro metric change"
        ),
        "causal_interpretation_allowed": False,
        "fold_metric_reproduction": reproduction,
        "protected_artifact_hashes_before_after": hashes_before,
        "protected_artifacts_modified": False,
        "model_feature_or_calibration_change_performed": False,
        "final_test_evaluation_performed": False,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return RunnerCountDiagnosticOutcome(
        analysis_version=ANALYSIS_VERSION,
        stable_races=stable_races,
        degraded_races=degraded_races,
        result_path=result_path,
    )
