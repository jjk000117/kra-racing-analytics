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
from kra_analytics.modeling import AUDIT_ONLY_FEATURE, MODEL_INPUTS, TARGET_COLUMN
from kra_analytics.paths import ProjectPaths

ANALYSIS_VERSION = "feature_drift_diagnostic_v1"
STABLE_START = pd.Timestamp("2025-10-01")
STABLE_END = pd.Timestamp("2026-05-01")
DEGRADED_START = pd.Timestamp("2026-05-01")
DEGRADED_END = pd.Timestamp("2026-08-01")

RACE_STRUCTURE_FEATURES = (
    "meet_code",
    "race_grade",
    "distance_m",
    "registered_runner_count",
)
ROW_CATEGORICAL_FEATURES = (
    "horse_sex",
    "horse_history_available",
    "jockey_history_available",
    "trainer_history_available",
)
NUMERIC_FEATURES = tuple(
    feature
    for feature in MODEL_INPUTS
    if feature not in {"meet_code", "race_grade", "horse_sex"}
    and feature
    not in {
        "horse_history_available",
        "jockey_history_available",
        "trainer_history_available",
    }
)


@dataclass(frozen=True)
class DriftDiagnosticOutcome:
    analysis_version: str
    stable_rows: int
    degraded_rows: int
    result_path: Path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_frame(*, paths: ProjectPaths) -> pd.DataFrame:
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
            query, [SNAPSHOT_VERSION, STABLE_START.date(), DEGRADED_END.date()]
        ).fetchdf()
    frame["race_date"] = pd.to_datetime(frame["race_date"])
    frame["period"] = np.where(frame["race_date"] < STABLE_END, "STABLE", "DEGRADED")
    if frame.empty or frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Diagnostic input is empty or has duplicate business keys")
    return frame


def summarize_numeric(frame: pd.DataFrame, features: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in features:
        summaries: dict[str, dict[str, float | int | None]] = {}
        for period in ("STABLE", "DEGRADED"):
            values = pd.to_numeric(
                frame.loc[frame["period"] == period, feature], errors="coerce"
            )
            non_null = values.dropna()
            summaries[period] = {
                "rows": len(values),
                "non_null_rows": len(non_null),
                "null_rate": float(values.isna().mean()),
                "mean": float(non_null.mean()) if len(non_null) else None,
                "p10": float(non_null.quantile(0.10)) if len(non_null) else None,
                "p25": float(non_null.quantile(0.25)) if len(non_null) else None,
                "p50": float(non_null.quantile(0.50)) if len(non_null) else None,
                "p75": float(non_null.quantile(0.75)) if len(non_null) else None,
                "p90": float(non_null.quantile(0.90)) if len(non_null) else None,
            }
        stable = summaries["STABLE"]
        degraded = summaries["DEGRADED"]

        def difference(
            name: str,
            stable_summary: dict[str, float | int | None] = stable,
            degraded_summary: dict[str, float | int | None] = degraded,
        ) -> float | None:
            left = stable_summary[name]
            right = degraded_summary[name]
            if left is None or right is None:
                return None
            return float(right) - float(left)

        rows.append(
            {
                "feature": feature,
                "stable": stable,
                "degraded": degraded,
                "degraded_minus_stable": {
                    name: difference(name)
                    for name in ("null_rate", "mean", "p10", "p25", "p50", "p75", "p90")
                },
            }
        )
    return rows


def summarize_categorical(
    frame: pd.DataFrame, features: tuple[str, ...], *, grain: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in features:
        working = frame.loc[:, ["period", feature]].copy()
        working[feature] = working[feature].astype("string").fillna("<NULL>")
        counts = working.groupby(["period", feature], observed=True).size().rename("rows")
        totals = working.groupby("period", observed=True).size().rename("total")
        table = counts.reset_index().merge(totals.reset_index(), on="period")
        table["share"] = table["rows"] / table["total"]
        categories = sorted(table[feature].unique().tolist())
        for category in categories:
            category_rows: dict[str, dict[str, float | int]] = {}
            for period in ("STABLE", "DEGRADED"):
                matched = table.loc[(table["period"] == period) & (table[feature] == category)]
                category_rows[period] = {
                    "rows": int(matched["rows"].iloc[0]) if len(matched) else 0,
                    "share": float(matched["share"].iloc[0]) if len(matched) else 0.0,
                }
            rows.append(
                {
                    "grain": grain,
                    "feature": feature,
                    "category": str(category),
                    "stable": category_rows["STABLE"],
                    "degraded": category_rows["DEGRADED"],
                    "share_change_percentage_points": 100
                    * (
                        float(category_rows["DEGRADED"]["share"])
                        - float(category_rows["STABLE"]["share"])
                    ),
                }
            )
    return rows


def run_feature_drift_diagnostic(*, paths: ProjectPaths | None = None) -> DriftDiagnosticOutcome:
    project_paths = paths or ProjectPaths.from_root()
    baseline_directory = project_paths.exports / "modeling" / "place_logistic_baseline_v1"
    walk_directory = project_paths.exports / "modeling" / "walk_forward_stability_v1"
    protected_paths = (
        baseline_directory / "run_contract.json",
        baseline_directory / "pipeline.joblib",
        baseline_directory / "final_test_result.json",
        walk_directory / "walk_forward_result.json",
    )
    hashes_before = {str(path): _file_sha256(path) for path in protected_paths}

    output_directory = project_paths.exports / "modeling" / ANALYSIS_VERSION
    result_path = output_directory / "feature_drift_result.json"
    if result_path.exists():
        raise FileExistsError("Feature drift diagnostic result already exists")

    frame = _load_frame(paths=project_paths)
    stable = frame.loc[frame["period"] == "STABLE"]
    degraded = frame.loc[frame["period"] == "DEGRADED"]
    race_frame = frame.drop_duplicates("race_id")

    period_summary: dict[str, dict[str, float | int | str]] = {}
    for period, period_frame in (("STABLE", stable), ("DEGRADED", degraded)):
        period_summary[period] = {
            "start_date": str(period_frame["race_date"].min().date()),
            "end_date": str(period_frame["race_date"].max().date()),
            "runner_rows": len(period_frame),
            "race_count": int(period_frame["race_id"].nunique()),
            "plc_positive_rate": float(period_frame[TARGET_COLUMN].mean()),
            "horse_history_available_rate": float(
                period_frame["horse_history_available"].mean()
            ),
            "jockey_history_available_rate": float(
                period_frame["jockey_history_available"].mean()
            ),
            "trainer_history_available_rate": float(
                period_frame["trainer_history_available"].mean()
            ),
        }

    numeric = summarize_numeric(frame, NUMERIC_FEATURES)
    race_categories = summarize_categorical(
        race_frame, RACE_STRUCTURE_FEATURES, grain="RACE"
    )
    row_categories = summarize_categorical(
        frame, ROW_CATEGORICAL_FEATURES, grain="RUNNER"
    )

    hashes_after = {str(path): _file_sha256(path) for path in protected_paths}
    if hashes_before != hashes_after:
        raise ValueError("Protected baseline or walk-forward artifact changed during diagnostic")

    output_directory.mkdir(parents=True, exist_ok=True)
    result = {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_purpose": "INPUT_TARGET_AND_RACE_MIX_DIAGNOSTIC_ONLY",
        "stable_period": [str(STABLE_START.date()), "2026-04-30"],
        "degraded_period": [str(DEGRADED_START.date()), "2026-07-31"],
        "snapshot_version": SNAPSHOT_VERSION,
        "snapshot_features": MODEL_FEATURES,
        "model_inputs": MODEL_INPUTS,
        "audit_only_feature_excluded_from_model": AUDIT_ONLY_FEATURE,
        "period_summary": period_summary,
        "numeric_feature_distributions": numeric,
        "categorical_composition": race_categories + row_categories,
        "numeric_summary_definition": "row_count_null_rate_mean_p10_p25_p50_p75_p90",
        "categorical_summary_definition": (
            "period_share_and_degraded_minus_stable_percentage_points"
        ),
        "composite_score_created": False,
        "model_training_or_selection_performed": False,
        "protected_artifact_hashes_before_after": hashes_before,
        "protected_artifacts_modified": False,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return DriftDiagnosticOutcome(
        analysis_version=ANALYSIS_VERSION,
        stable_rows=len(stable),
        degraded_rows=len(degraded),
        result_path=result_path,
    )
