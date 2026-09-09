# SQL fragments intentionally remain readable as complete expressions.
# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.aptitude_features import _protected_hashes
from kra_analytics.development_evaluation import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_FOLDS,
    DEVELOPMENT_START,
)
from kra_analytics.experiment_database import (
    connect_experiment_database,
    connect_source_database,
    resolve_experiment_database_paths,
)
from kra_analytics.feature_bundles import F3_FEATURES, _higher_percentile
from kra_analytics.paths import ProjectPaths
from kra_analytics.trend_experiment import _contracts
from kra_analytics.trend_features import TREND_TABLE

RELATIVE_VERSION = "post_baseline_v2_relative_r1_candidate_v1"
CANDIDATE_TABLE = "mart.place_feature_snapshot_v2_relative_candidate"
REGISTRY_PATH = "docs/post-baseline-v2-relative-r1-registry.csv"
OUTPUT_DIRECTORY = "data/exports/validation/post_baseline_v2_relative_r1"

SOURCE_FEATURES = (
    "horse_same_meet_plc_hit_rate",
    "horse_same_meet_distance_plc_hit_rate",
    "jockey_same_meet_plc_hit_rate",
    "trainer_same_meet_plc_hit_rate",
    "owner_prior_plc_hit_rate",
    "horse_trainer_prior_plc_hit_rate",
    "horse_recent5_race_time_percentile_median",
)
RELATIVE_FEATURES = (
    "horse_same_meet_plc_hit_rate_field_percentile",
    "horse_same_meet_distance_plc_hit_rate_field_percentile",
    "jockey_same_meet_plc_hit_rate_field_percentile",
    "trainer_same_meet_plc_hit_rate_field_percentile",
    "owner_prior_plc_hit_rate_field_percentile",
    "horse_trainer_prior_plc_hit_rate_field_percentile",
    "horse_recent5_race_time_percentile_median_field_percentile",
)
SOURCE_BY_FEATURE = dict(zip(RELATIVE_FEATURES, SOURCE_FEATURES, strict=True))


@dataclass(frozen=True)
class RelativeFeatureOutcome:
    row_count: int
    race_count: int
    feature_count: int
    audit_issue_count: int
    relative_hash: str
    candidate_hash: str
    output_directory: Path


def _registry_rows(paths: ProjectPaths) -> list[dict[str, str]]:
    with (paths.root / REGISTRY_PATH).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    names = tuple(row["feature_name"] for row in rows)
    sources = tuple(row["source_feature"] for row in rows)
    if names != RELATIVE_FEATURES or sources != SOURCE_FEATURES:
        raise ValueError("R1 registry names, order, or source lineage differ from contract")
    if len(names) != 7 or len(set(names)) != 7:
        raise ValueError("R1 registry must contain exactly seven unique Features")
    return rows


def _hash_names(names: tuple[str, ...]) -> str:
    return hashlib.sha256(("\n".join(names) + "\n").encode()).hexdigest()


def relative_feature_hash(paths: ProjectPaths) -> str:
    _registry_rows(paths)
    return _hash_names(RELATIVE_FEATURES)


def relative_candidate_hash(paths: ProjectPaths) -> str:
    contract = _contracts(paths)["LT1"]
    return _hash_names(contract.inputs + RELATIVE_FEATURES)


def _branch_protected_hashes(paths: ProjectPaths) -> dict[str, str]:
    files = {
        "a1_audit": paths.root
        / "data/exports/validation/post_baseline_v2_aptitude_a1/audit_result.json",
        "a1_result": paths.root
        / "data/exports/modeling/post_baseline_v2_aptitude_a1_development_v1/result.json",
        "r1_registry": paths.root / REGISTRY_PATH,
    }
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Branch protected artifacts missing: {missing}")
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}


def _source_query() -> str:
    expressions = [
        f"{_higher_percentile(source)} AS {feature}"
        for feature, source in SOURCE_BY_FEATURE.items()
    ]
    return f"""
SELECT current_rows.*,
       {', '.join(expressions)}
FROM {TREND_TABLE} current_rows
WHERE race_date >= DATE '{DEVELOPMENT_START}'
  AND race_date < DATE '{DEVELOPMENT_END_EXCLUSIVE}'
ORDER BY race_date, race_id, horse_id
"""


def average_rank_percentiles(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    output = pd.Series(np.nan, index=values.index, dtype=float)
    valid = numeric.dropna()
    if len(valid) < 3:
        return output
    output.loc[valid.index] = (valid.rank(method="average") - 1.0) / (len(valid) - 1.0)
    return output


def _fold_label(value: Any) -> str | None:
    for fold in DEVELOPMENT_FOLDS:
        if fold.evaluation_start <= value < fold.evaluation_end_exclusive:
            return fold.fold_id
    return None


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _profile(frame: pd.DataFrame, group_name: str) -> list[dict[str, Any]]:
    groups = [("ALL", frame)] if group_name == "all" else frame.groupby(group_name, dropna=False)
    rows: list[dict[str, Any]] = []
    for label, part in groups:
        for feature in RELATIVE_FEATURES:
            values = pd.to_numeric(part[feature], errors="coerce")
            valid = values.dropna()
            quantiles = valid.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]) if not valid.empty else pd.Series(dtype=float)
            rows.append(
                {
                    "group": str(label),
                    "feature_name": feature,
                    "row_count": len(part),
                    "non_null_count": int(valid.size),
                    "availability_rate": float(valid.size / len(part)),
                    "mean": None if valid.empty else float(valid.mean()),
                    "std": None if valid.empty else float(valid.std()),
                    "p01": None if valid.empty else float(quantiles.loc[0.01]),
                    "p05": None if valid.empty else float(quantiles.loc[0.05]),
                    "p25": None if valid.empty else float(quantiles.loc[0.25]),
                    "median": None if valid.empty else float(quantiles.loc[0.5]),
                    "p75": None if valid.empty else float(quantiles.loc[0.75]),
                    "p95": None if valid.empty else float(quantiles.loc[0.95]),
                    "p99": None if valid.empty else float(quantiles.loc[0.99]),
                    "minimum": None if valid.empty else float(valid.min()),
                    "maximum": None if valid.empty else float(valid.max()),
                    "exact_zero_rate": float((valid == 0).mean()) if not valid.empty else None,
                    "exact_one_rate": float((valid == 1).mean()) if not valid.empty else None,
                    "unique_percentiles": int(valid.nunique()),
                }
            )
    return rows


def _source_audit(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature, source in SOURCE_BY_FEATURE.items():
        source_values = pd.to_numeric(frame[source], errors="coerce")
        comparable = frame.assign(_valid=source_values.notna()).groupby("race_id")["_valid"].transform("sum")
        stored = pd.to_numeric(frame[feature], errors="coerce")
        valid_source = source_values.notna()
        tie_sizes = frame.loc[valid_source].groupby(["race_id", source], dropna=False)[source].transform("size")
        rows.append(
            {
                "feature_name": feature,
                "source_feature": source,
                "source_dtype": str(frame[source].dtype),
                "source_non_null": int(valid_source.sum()),
                "comparable_ge_3": int((valid_source & (comparable >= 3)).sum()),
                "stored_non_null": int(stored.notna().sum()),
                "source_null_with_value": int((source_values.isna() & stored.notna()).sum()),
                "source_non_null_unexplained_null": int((valid_source & (comparable >= 3) & stored.isna()).sum()),
                "less_than_3_with_value": int(((comparable < 3) & stored.notna()).sum()),
                "tie_row_count": int((tie_sizes > 1).sum()),
                "tie_row_rate": float((tie_sizes > 1).mean()),
                "range_violations": int(((stored < 0) | (stored > 1)).sum()),
                "nan_count": int(np.isnan(stored.to_numpy(dtype=float)).sum() - stored.isna().sum()),
                "positive_inf_count": int(np.isposinf(stored.to_numpy(dtype=float)).sum()),
                "negative_inf_count": int(np.isneginf(stored.to_numpy(dtype=float)).sum()),
            }
        )
    return rows


def _manual_recalculation(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    field_sizes = sorted(int(value) for value in frame["registered_runner_count"].dropna().unique())
    if 7 not in field_sizes:
        notes.append("No field-size-7 race exists in development; synthetic unit test covers n=7")
    selected_races: set[str] = set()
    for size in [min(field_sizes), 11, max(field_sizes)]:
        match = frame.loc[frame["registered_runner_count"] == size, "race_id"]
        if not match.empty:
            selected_races.add(str(match.iloc[0]))
    for feature, source in SOURCE_BY_FEATURE.items():
        summaries: list[dict[str, Any]] = []
        for race_id, part in frame.groupby("race_id", sort=True):
            valid = part[source].dropna()
            summaries.append(
                {
                    "race_id": str(race_id),
                    "valid_count": len(valid),
                    "has_tie": bool(valid.duplicated(keep=False).any()),
                    "has_null": bool(part[source].isna().any()),
                }
            )
        summary = pd.DataFrame(summaries)
        case_races: dict[str, set[str]] = {race_id: {"field_size_sample"} for race_id in selected_races}
        selectors = {
            "comparable_2": summary["valid_count"] == 2,
            "comparable_3": summary["valid_count"] == 3,
            "tie": summary["has_tie"],
            "source_null": summary["has_null"],
        }
        for case, mask in selectors.items():
            matches = summary.loc[mask, "race_id"]
            if not matches.empty:
                case_races.setdefault(str(matches.iloc[0]), set()).add(case)
        for race_id in sorted(case_races):
            part = frame[frame["race_id"].astype(str) == race_id].copy()
            expected = average_rank_percentiles(part[source])
            valid_count = int(part[source].notna().sum())
            raw_ranks = part[source].rank(method="min")
            for position, (_, row) in enumerate(part.iterrows()):
                source_value = row[source]
                tie_count = 0 if pd.isna(source_value) else int((part[source] == source_value).sum())
                raw_rank = None if pd.isna(source_value) else float(raw_ranks.iloc[position])
                expected_value = expected.iloc[position]
                stored_value = row[feature]
                error = None if pd.isna(expected_value) and pd.isna(stored_value) else abs(float(expected_value) - float(stored_value))
                rows.append(
                    {
                        "case_feature": feature,
                        "sample_case": "|".join(sorted(case_races[race_id])),
                        "race_id": race_id,
                        "horse_id": row["horse_id"],
                        "field_size": int(row["registered_runner_count"]),
                        "comparable_runner_count": valid_count,
                        "source_value": None if pd.isna(source_value) else float(source_value),
                        "comparison_values": "|".join(str(value) for value in sorted(part[source].dropna().tolist())),
                        "raw_rank": raw_rank,
                        "tie_count": tie_count,
                        "expected_percentile": None if pd.isna(expected_value) else float(expected_value),
                        "stored_percentile": None if pd.isna(stored_value) else float(stored_value),
                        "absolute_error": error,
                    }
                )
    return rows, notes


def build_and_audit_relative_features(*, paths: ProjectPaths | None = None) -> RelativeFeatureOutcome:
    project_paths = paths or ProjectPaths.from_root()
    _registry_rows(project_paths)
    contract = _contracts(project_paths)["LT1"]
    if len(contract.inputs) != 137 or len(set(contract.inputs)) != 137:
        raise ValueError("Protected LT1 must contain exactly 137 unique inputs")
    if set(RELATIVE_FEATURES) & set(contract.inputs) or set(RELATIVE_FEATURES) & set(F3_FEATURES):
        raise ValueError("R1 duplicates LT1 or F3")
    if len(set(contract.inputs + RELATIVE_FEATURES)) != 144:
        raise ValueError("LR1 must contain exactly 144 unique inputs")
    database_paths = resolve_experiment_database_paths(paths=project_paths)
    protected_before = {
        **_protected_hashes(project_paths, database_paths.source),
        **_branch_protected_hashes(project_paths),
    }
    with connect_source_database(database_paths=database_paths) as source:
        base_columns = [str(row[0]) for row in source.execute(f"DESCRIBE {TREND_TABLE}").fetchall()]
        frame = source.execute(_source_query()).fetchdf()
    frame["race_date"] = pd.to_datetime(frame["race_date"]).dt.date
    frame["feature_as_of"] = pd.to_datetime(frame["feature_as_of"]).dt.date
    issues: list[str] = []
    if len(frame) != 28_392 or frame["race_id"].nunique() != 2_675:
        issues.append("development row/race count mismatch")
    if frame.duplicated(["race_id", "horse_id"]).any():
        issues.append("duplicate business key")
    pit_violations = int(
        (
            pd.to_datetime(frame["source_max_event_date"]).dt.date
            >= frame["feature_as_of"]
        ).sum()
    )
    if pit_violations:
        issues.append(f"Historical source_max_event_date PIT violations: {pit_violations}")
    expected_columns = base_columns + list(RELATIVE_FEATURES)
    if list(frame.columns) != expected_columns:
        issues.append("candidate schema differs from LT1 plus sealed R1")
    if len(base_columns) < 137 or not set(contract.inputs).issubset(base_columns):
        issues.append("LT1 source columns missing")
    audit_rows = _source_audit(frame)
    for row in audit_rows:
        if any(
            int(row[name])
            for name in (
                "source_null_with_value",
                "source_non_null_unexplained_null",
                "less_than_3_with_value",
                "range_violations",
                "nan_count",
                "positive_inf_count",
                "negative_inf_count",
            )
        ):
            issues.append(f"R1 source/value contract violation: {row['feature_name']}")
    manual_rows, manual_notes = _manual_recalculation(frame)
    manual_errors = [row["absolute_error"] for row in manual_rows if row["absolute_error"] is not None]
    max_manual_error = max(manual_errors, default=0.0)
    if max_manual_error > 1e-12:
        issues.append(f"manual percentile mismatch: {max_manual_error}")
    candidate_columns = base_columns + list(RELATIVE_FEATURES)
    with connect_experiment_database(database_paths=database_paths, paths=project_paths) as target:
        target.execute("CREATE SCHEMA IF NOT EXISTS mart")
        target.register("relative_candidate_frame", frame[candidate_columns])
        target.execute(f"CREATE OR REPLACE TABLE {CANDIDATE_TABLE} AS SELECT * FROM relative_candidate_frame")
        stored = target.execute(f"SELECT * FROM {CANDIDATE_TABLE} ORDER BY race_date,race_id,horse_id").fetchdf()
    expected_stored = frame[candidate_columns].reset_index(drop=True).copy()
    actual_stored = stored.reset_index(drop=True).copy()
    for column in ("race_date", "feature_as_of"):
        expected_stored[column] = pd.to_datetime(expected_stored[column])
        actual_stored[column] = pd.to_datetime(actual_stored[column])
    try:
        pd.testing.assert_frame_equal(expected_stored, actual_stored, check_dtype=False)
        pd.testing.assert_frame_equal(
            expected_stored[base_columns], actual_stored[base_columns], check_dtype=False
        )
    except AssertionError:
        issues.append("candidate round-trip or LT1 value mismatch")
    output = project_paths.root / OUTPUT_DIRECTORY
    frame["calendar_period"] = np.where(pd.to_datetime(frame["race_date"]).dt.year == 2023, "2023", "2024-H1")
    frame["meet_group"] = frame["meet_code"].map({1: "SEOUL", 3: "BUSAN_GYEONGNAM"}).fillna(frame["meet_code"].astype(str))
    frame["fold_id"] = [_fold_label(value) for value in frame["race_date"]]
    frame["field_size_group"] = frame["registered_runner_count"].astype(str)
    _write_csv(output / "r1_profile_overall.csv", _profile(frame, "all"))
    _write_csv(output / "r1_profile_by_period.csv", _profile(frame, "calendar_period"))
    _write_csv(output / "r1_profile_by_meet.csv", _profile(frame, "meet_group"))
    _write_csv(output / "r1_profile_by_fold.csv", _profile(frame[frame["fold_id"].notna()], "fold_id"))
    _write_csv(output / "r1_profile_by_field_size.csv", _profile(frame, "field_size_group"))
    _write_csv(output / "r1_source_null_tie_audit.csv", audit_rows)
    _write_csv(output / "r1_manual_recalculation.csv", manual_rows)
    protected_after = {
        **_protected_hashes(project_paths, database_paths.source),
        **_branch_protected_hashes(project_paths),
    }
    changed = [name for name in protected_before if protected_before[name] != protected_after[name]]
    if changed:
        issues.append(f"protected artifacts changed: {changed}")
    result = {
        "version": RELATIVE_VERSION,
        "created_at": datetime.now().astimezone().isoformat(),
        "source_database": str(database_paths.source),
        "experiment_database": str(database_paths.experiment),
        "candidate_table": CANDIDATE_TABLE,
        "row_count": len(frame),
        "race_count": int(frame["race_id"].nunique()),
        "base_feature_count": 137,
        "relative_feature_count": 7,
        "candidate_feature_count": 144,
        "lt1_hash": contract.feature_hash,
        "relative_feature_hash": relative_feature_hash(project_paths),
        "candidate_feature_hash": relative_candidate_hash(project_paths),
        "duplicate_business_keys": int(frame.duplicated(["race_id", "horse_id"]).sum()),
        "source_max_event_date_pit_violations": pit_violations,
        "manual_recalculation_rows": len(manual_rows),
        "manual_recalculation_max_absolute_error": max_manual_error,
        "manual_notes": manual_notes,
        "strict_pit_rule": "source Historical Features already satisfy historical.race_date < feature_as_of; R1 only compares cutoff-known current-race rows",
        "forbidden_current_result_sources": [],
        "validation_accessed": False,
        "post_2024_07_accessed": False,
        "protected_sha256_before": protected_before,
        "protected_sha256_after": protected_after,
        "protected_artifacts_changed": changed,
        "audit_issues": issues,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if issues:
        raise ValueError("R1 audit failed: " + "; ".join(issues))
    return RelativeFeatureOutcome(
        len(frame), int(frame["race_id"].nunique()), 7, 0,
        relative_feature_hash(project_paths), relative_candidate_hash(project_paths), output
    )
