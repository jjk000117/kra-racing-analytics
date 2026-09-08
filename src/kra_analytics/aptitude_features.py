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
from duckdb import DuckDBPyConnection

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
from kra_analytics.paths import ProjectPaths
from kra_analytics.trend_experiment import _contracts
from kra_analytics.trend_features import TREND_TABLE

APTITUDE_VERSION = "post_baseline_v2_aptitude_a1_candidate_v1"
CANDIDATE_TABLE = "mart.place_feature_snapshot_v2_aptitude_candidate"
AUDIT_TABLE = "quality.post_baseline_v2_aptitude_source_audit"
BASE_HISTORY_TABLE = "mart.place_feature_snapshot_v2_candidate"
REGISTRY_PATH = "docs/post-baseline-v2-aptitude-feature-registry.csv"
OUTPUT_DIRECTORY = "data/exports/validation/post_baseline_v2_aptitude_a1"

APTITUDE_FEATURES = (
    "horse_same_grade_start_count",
    "horse_same_grade_plc_hit_rate",
    "horse_same_track_condition_start_count",
    "horse_same_track_condition_plc_hit_rate",
    "horse_same_distance_race_time_percentile_count",
    "horse_same_distance_race_time_percentile_median",
    "horse_distance_change_from_last_start_m",
)


@dataclass(frozen=True)
class AptitudeFeatureOutcome:
    row_count: int
    race_count: int
    feature_count: int
    audit_issue_count: int
    output_directory: Path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_files(paths: ProjectPaths, source_database: Path) -> dict[str, Path]:
    common_root = source_database.parents[2]
    return {
        "common_database": source_database,
        "t1_registry": paths.root / "docs/post-baseline-v2-historical-trend-feature-registry.csv",
        "validation_contract": paths.root
        / "docs/post-baseline-v2-improvement-validation-contract.json",
        "t1_result": common_root
        / "data/exports/modeling/post_baseline_v2_t1_development_v1/result.json",
        "validation_ledger": common_root
        / "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/validation_access.json",
        "validation_result": common_root
        / "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/result.json",
        "h133_result": common_root
        / "data/exports/modeling/post_baseline_v2_h133_development_v1/result.json",
        "ra1_result": common_root
        / "data/exports/modeling/post_baseline_v2_ra1_development_v1/result.json",
    }


def _protected_hashes(paths: ProjectPaths, source_database: Path) -> dict[str, str]:
    files = _protected_files(paths, source_database)
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Protected artifacts missing: {missing}")
    return {name: _sha256_file(path) for name, path in files.items()}


def _registry_rows(paths: ProjectPaths) -> list[dict[str, str]]:
    with (paths.root / REGISTRY_PATH).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    names = tuple(row["feature_name"] for row in rows)
    if names != APTITUDE_FEATURES or len(set(names)) != 7:
        raise ValueError("A1 registry must contain the seven sealed Features in exact order")
    return rows


def aptitude_feature_hash(paths: ProjectPaths) -> str:
    _registry_rows(paths)
    return hashlib.sha256(("\n".join(APTITUDE_FEATURES) + "\n").encode()).hexdigest()


def _source_query() -> str:
    return f"""
WITH event_source AS (
    SELECT b.race_id, b.horse_id, b.race_date, b.distance_m,
           rr.result_status, rr.is_valid_start, rr.is_valid_finish,
           e.valid_race_time_seconds AS race_time
    FROM {BASE_HISTORY_TABLE} b
    JOIN canonical.runner_result rr USING (race_id, horse_id)
    JOIN semantic.api4_runner_event_v2 e ON e.staging_row_id=rr.source_staging_row_id
),
f1_ranked AS (
    SELECT race_id, horse_id, race_date, distance_m, race_time,
           count(*) OVER (PARTITION BY race_id) AS comparison_count,
           rank() OVER (PARTITION BY race_id ORDER BY race_time) +
             (count(*) OVER (PARTITION BY race_id,race_time)-1)/2.0 AS average_rank
    FROM event_source
    WHERE is_valid_start AND is_valid_finish AND result_status='FINISHED'
      AND race_time IS NOT NULL AND race_time>0
),
f1_events AS (
    SELECT race_id,horse_id,race_date,distance_m,
           (comparison_count-average_rank)/(comparison_count-1) AS time_percentile
    FROM f1_ranked WHERE comparison_count>=3
),
current_rows AS (
    SELECT * FROM {TREND_TABLE}
    WHERE race_date>=DATE '{DEVELOPMENT_START}' AND race_date<DATE '{DEVELOPMENT_END_EXCLUSIVE}'
),
history_aggregates AS (
    SELECT cur.race_id,cur.horse_id,
           count(hist.race_id) FILTER(WHERE hist.race_grade=cur.race_grade)::INTEGER AS same_grade_count,
           avg(hist.place_hit::INTEGER) FILTER(WHERE hist.race_grade=cur.race_grade) AS same_grade_rate,
           count(hist.race_id) FILTER(WHERE cur.current_track_condition IS NOT NULL AND hist.current_track_condition=cur.current_track_condition)::INTEGER AS same_track_count,
           avg(hist.place_hit::INTEGER) FILTER(WHERE cur.current_track_condition IS NOT NULL AND hist.current_track_condition=cur.current_track_condition) AS same_track_rate
    FROM current_rows cur
    LEFT JOIN {BASE_HISTORY_TABLE} hist
      ON hist.horse_id=cur.horse_id AND hist.race_date<cur.feature_as_of
    GROUP BY cur.race_id,cur.horse_id
),
f1_aggregates AS (
    SELECT cur.race_id,cur.horse_id,count(f.race_id)::INTEGER AS same_distance_f1_count,
           median(f.time_percentile) AS same_distance_f1_median
    FROM current_rows cur
    LEFT JOIN f1_events f ON f.horse_id=cur.horse_id
      AND f.race_date<cur.feature_as_of AND f.distance_m=cur.distance_m
    GROUP BY cur.race_id,cur.horse_id
),
last_start AS (
    SELECT cur.race_id,cur.horse_id,hist.race_id AS previous_race_id,
           hist.race_date AS previous_race_date,hist.distance_m AS previous_distance_m
    FROM current_rows cur
    LEFT JOIN LATERAL (
       SELECT race_id,race_date,distance_m FROM {BASE_HISTORY_TABLE} hist
       WHERE hist.horse_id=cur.horse_id AND hist.race_date<cur.feature_as_of
       ORDER BY hist.race_date DESC,hist.race_id DESC LIMIT 1
    ) hist ON TRUE
)
SELECT cur.*,
       coalesce(h.same_grade_count,0)::INTEGER AS horse_same_grade_start_count,
       CASE WHEN h.same_grade_count>=3 THEN h.same_grade_rate END AS horse_same_grade_plc_hit_rate,
       coalesce(h.same_track_count,0)::INTEGER AS horse_same_track_condition_start_count,
       CASE WHEN h.same_track_count>=3 THEN h.same_track_rate END AS horse_same_track_condition_plc_hit_rate,
       coalesce(f.same_distance_f1_count,0)::INTEGER AS horse_same_distance_race_time_percentile_count,
       CASE WHEN f.same_distance_f1_count>=3 THEN f.same_distance_f1_median END AS horse_same_distance_race_time_percentile_median,
       CASE WHEN l.previous_distance_m IS NOT NULL THEN cur.distance_m-l.previous_distance_m END::INTEGER AS horse_distance_change_from_last_start_m,
       l.previous_race_id,l.previous_race_date,l.previous_distance_m
FROM current_rows cur
JOIN history_aggregates h USING(race_id,horse_id)
JOIN f1_aggregates f USING(race_id,horse_id)
JOIN last_start l USING(race_id,horse_id)
ORDER BY cur.race_date,cur.race_id,cur.horse_id
"""


def _fold_label(date: Any) -> str | None:
    for fold in DEVELOPMENT_FOLDS:
        if fold.evaluation_start <= date < fold.evaluation_end_exclusive:
            return fold.fold_id
    return None


def _profiles(frame: pd.DataFrame, group: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups = [("ALL", frame)] if group == "all" else frame.groupby(group, dropna=False)
    for label, part in groups:
        for feature in APTITUDE_FEATURES:
            values = pd.to_numeric(part[feature], errors="coerce")
            valid = values.dropna()
            rows.append(
                {
                    "group": str(label),
                    "feature_name": feature,
                    "row_count": len(part),
                    "non_null_count": int(valid.size),
                    "availability_rate": float(valid.size / len(part)),
                    "minimum": None if valid.empty else float(valid.min()),
                    "p25": None if valid.empty else float(valid.quantile(0.25)),
                    "median": None if valid.empty else float(valid.median()),
                    "p75": None if valid.empty else float(valid.quantile(0.75)),
                    "maximum": None if valid.empty else float(valid.max()),
                }
            )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _manual_samples(source: DuckDBPyConnection, frame: pd.DataFrame) -> list[dict[str, Any]]:
    selectors = [
        ("grade_count_2", frame[frame[APTITUDE_FEATURES[0]] == 2]),
        ("grade_count_3", frame[frame[APTITUDE_FEATURES[0]] == 3]),
        ("grade_count_10_plus", frame[frame[APTITUDE_FEATURES[0]] >= 10]),
        ("track_count_2", frame[frame[APTITUDE_FEATURES[2]] == 2]),
        ("track_count_3_plus", frame[frame[APTITUDE_FEATURES[2]] >= 3]),
        ("same_distance_f1_3_plus", frame[frame[APTITUDE_FEATURES[4]] >= 3]),
        ("distance_extension", frame[frame[APTITUDE_FEATURES[6]] > 0]),
        ("distance_same", frame[frame[APTITUDE_FEATURES[6]] == 0]),
        ("distance_reduction", frame[frame[APTITUDE_FEATURES[6]] < 0]),
        ("distance_no_history", frame[frame[APTITUDE_FEATURES[6]].isna()]),
    ]
    results: list[dict[str, Any]] = []
    f1_cte = _source_query().split("current_rows AS", 1)[0].rstrip(",\n ")
    for case, candidates in selectors:
        if candidates.empty:
            continue
        row = candidates.iloc[0]
        horse_id = str(row["horse_id"])
        race_id = str(row["race_id"])
        as_of = row["feature_as_of"]
        details: dict[str, Any] = {
            "case": case,
            "race_id": race_id,
            "horse_id": horse_id,
            "feature_as_of": str(as_of),
        }
        if case.startswith("grade"):
            values = source.execute(
                f"SELECT place_hit::INTEGER FROM {BASE_HISTORY_TABLE} WHERE horse_id=? AND race_date<? AND race_grade=? ORDER BY race_date,race_id",
                [horse_id, as_of, str(row["race_grade"])],
            ).fetchall()
            expected_count = len(values)
            expected_value = (
                sum(x[0] for x in values) / expected_count if expected_count >= 3 else None
            )
            stored_count = row[APTITUDE_FEATURES[0]]
            stored_value = row[APTITUDE_FEATURES[1]]
        elif case.startswith("track"):
            values = source.execute(
                f"SELECT place_hit::INTEGER FROM {BASE_HISTORY_TABLE} WHERE horse_id=? AND race_date<? AND current_track_condition=? ORDER BY race_date,race_id",
                [horse_id, as_of, str(row["current_track_condition"])],
            ).fetchall()
            expected_count = len(values)
            expected_value = (
                sum(x[0] for x in values) / expected_count if expected_count >= 3 else None
            )
            stored_count = row[APTITUDE_FEATURES[2]]
            stored_value = row[APTITUDE_FEATURES[3]]
        elif case.startswith("same_distance"):
            values = source.execute(
                f"{f1_cte} SELECT time_percentile FROM f1_events WHERE horse_id=? AND race_date<? AND distance_m=? ORDER BY race_date,race_id",
                [horse_id, as_of, int(row["distance_m"])],
            ).fetchall()
            expected_count = len(values)
            expected_value = (
                float(np.median([x[0] for x in values])) if expected_count >= 3 else None
            )
            stored_count = row[APTITUDE_FEATURES[4]]
            stored_value = row[APTITUDE_FEATURES[5]]
        else:
            previous = source.execute(
                f"SELECT distance_m FROM {BASE_HISTORY_TABLE} WHERE horse_id=? AND race_date<? ORDER BY race_date DESC,race_id DESC LIMIT 1",
                [horse_id, as_of],
            ).fetchone()
            expected_count = 0 if previous is None else 1
            expected_value = None if previous is None else int(row["distance_m"]) - int(previous[0])
            stored_count = expected_count
            stored_value = row[APTITUDE_FEATURES[6]]
        if expected_value is None:
            equal = bool(pd.isna(stored_value))
        else:
            equal = not pd.isna(stored_value) and bool(
                np.isclose(float(stored_value), float(expected_value), atol=1e-12)
            )
        details.update(
            expected_count=expected_count,
            stored_count=int(stored_count),
            expected_value=expected_value,
            stored_value=None if pd.isna(stored_value) else float(stored_value),
            matches=equal,
        )
        results.append(details)
    return results


def _audit(frame: pd.DataFrame, base_columns: list[str], paths: ProjectPaths) -> list[str]:
    issues: list[str] = []
    expected = base_columns + list(APTITUDE_FEATURES)
    candidate = [column for column in frame.columns if not column.startswith("previous_")]
    if candidate != expected:
        issues.append("candidate schema differs from ordered LT1 plus sealed A1")
    if len(frame) != 28_392 or frame["race_id"].nunique() != 2_675:
        issues.append(
            f"development grain mismatch rows={len(frame)} races={frame['race_id'].nunique()}"
        )
    if frame.duplicated(["race_id", "horse_id"]).any():
        issues.append("duplicate business keys")
    has_previous = frame["previous_race_date"].notna()
    previous_dates = pd.to_datetime(frame.loc[has_previous, "previous_race_date"]).dt.date
    if not (previous_dates < frame.loc[has_previous, "feature_as_of"]).all():
        issues.append("last-start PIT violation")
    pairs = [
        (APTITUDE_FEATURES[0], APTITUDE_FEATURES[1]),
        (APTITUDE_FEATURES[2], APTITUDE_FEATURES[3]),
        (APTITUDE_FEATURES[4], APTITUDE_FEATURES[5]),
    ]
    for count, value in pairs:
        if ((frame[count] < 3) & frame[value].notna()).any() or (
            (frame[count] >= 3) & frame[value].isna()
        ).any():
            issues.append(f"count/NULL contradiction: {value}")
    for feature in (APTITUDE_FEATURES[1], APTITUDE_FEATURES[3], APTITUDE_FEATURES[5]):
        values = frame[feature].dropna()
        if ((values < 0) | (values > 1)).any():
            issues.append(f"range violation: {feature}")
    numeric = frame[list(APTITUDE_FEATURES)].select_dtypes(include="number").to_numpy(dtype=float)
    if np.isinf(numeric).any():
        issues.append("non-finite A1 value")
    contract = _contracts(paths)["LT1"]
    if len(contract.inputs) != 137 or len(set(contract.inputs + APTITUDE_FEATURES)) != 144:
        issues.append("LT1/A1 input contract mismatch")
    return issues


def build_and_audit_aptitude_features(
    *, paths: ProjectPaths | None = None
) -> AptitudeFeatureOutcome:
    project_paths = paths or ProjectPaths.from_root()
    _registry_rows(project_paths)
    db_paths = resolve_experiment_database_paths(paths=project_paths)
    protected_before = _protected_hashes(project_paths, db_paths.source)
    output = project_paths.root / OUTPUT_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    with connect_source_database(database_paths=db_paths) as source:
        base_columns = [str(row[0]) for row in source.execute(f"DESCRIBE {TREND_TABLE}").fetchall()]
        frame = source.execute(_source_query()).fetchdf()
        frame["feature_as_of"] = pd.to_datetime(frame["feature_as_of"]).dt.date
        frame["race_date"] = pd.to_datetime(frame["race_date"]).dt.date
        manual = _manual_samples(source, frame)
    issues = _audit(frame, base_columns, project_paths)
    if any(not row["matches"] for row in manual):
        issues.append("independent manual recalculation mismatch")
    candidate_columns = base_columns + list(APTITUDE_FEATURES)
    with connect_experiment_database(database_paths=db_paths, paths=project_paths) as target:
        target.execute("CREATE SCHEMA IF NOT EXISTS mart; CREATE SCHEMA IF NOT EXISTS quality")
        target.register("candidate_frame", frame[candidate_columns])
        target.execute(
            f"CREATE OR REPLACE TABLE {CANDIDATE_TABLE} AS SELECT * FROM candidate_frame"
        )
        target.register(
            "audit_frame",
            frame[
                [
                    "race_id",
                    "horse_id",
                    "feature_as_of",
                    "previous_race_id",
                    "previous_race_date",
                    "previous_distance_m",
                ]
            ],
        )
        target.execute(f"CREATE OR REPLACE TABLE {AUDIT_TABLE} AS SELECT * FROM audit_frame")
        stored = target.execute(
            f"SELECT * FROM {CANDIDATE_TABLE} ORDER BY race_date,race_id,horse_id"
        ).fetchdf()
    expected_stored = frame[candidate_columns].reset_index(drop=True).copy()
    actual_stored = stored.reset_index(drop=True).copy()
    for column in ("race_date", "feature_as_of"):
        expected_stored[column] = pd.to_datetime(expected_stored[column])
        actual_stored[column] = pd.to_datetime(actual_stored[column])
    try:
        pd.testing.assert_frame_equal(expected_stored, actual_stored, check_dtype=False)
    except AssertionError:
        issues.append("branch-local candidate round-trip mismatch")
    frame["calendar_year"] = pd.to_datetime(frame["race_date"]).dt.year
    frame["meet_group"] = frame["meet_code"].astype(str)
    frame["fold_id"] = [_fold_label(value) for value in frame["race_date"]]
    _write_csv(output / "a1_feature_profile_overall.csv", _profiles(frame, "all"))
    _write_csv(output / "a1_feature_profile_by_year.csv", _profiles(frame, "calendar_year"))
    _write_csv(output / "a1_feature_profile_by_meet.csv", _profiles(frame, "meet_group"))
    fold_frame = frame[frame["fold_id"].notna()]
    _write_csv(output / "a1_feature_profile_by_fold.csv", _profiles(fold_frame, "fold_id"))
    _write_csv(output / "a1_manual_recalculation.csv", manual)
    protected_after = _protected_hashes(project_paths, db_paths.source)
    changed_protected = [
        name for name in protected_before if protected_before[name] != protected_after[name]
    ]
    if changed_protected:
        issues.append(f"protected artifacts changed: {changed_protected}")
    count_rate_pairs = [
        (APTITUDE_FEATURES[0], APTITUDE_FEATURES[1]),
        (APTITUDE_FEATURES[2], APTITUDE_FEATURES[3]),
        (APTITUDE_FEATURES[4], APTITUDE_FEATURES[5]),
    ]
    data_audit = {
        "duplicate_business_keys": int(frame.duplicated(["race_id", "horse_id"]).sum()),
        "strict_pit_rule": "historical.race_date < feature_as_of",
        "last_start_pit_violations": int(
            (
                ~(
                    pd.to_datetime(
                        frame.loc[frame["previous_race_date"].notna(), "previous_race_date"]
                    ).dt.date
                    < frame.loc[frame["previous_race_date"].notna(), "feature_as_of"]
                )
            ).sum()
        ),
        "count_value_contradictions": {
            value: int(
                (
                    ((frame[count] < 3) & frame[value].notna())
                    | ((frame[count] >= 3) & frame[value].isna())
                ).sum()
            )
            for count, value in count_rate_pairs
        },
        "distance_change": {
            "available": int(frame[APTITUDE_FEATURES[6]].notna().sum()),
            "unavailable": int(frame[APTITUDE_FEATURES[6]].isna().sum()),
            "extension": int((frame[APTITUDE_FEATURES[6]] > 0).sum()),
            "same": int((frame[APTITUDE_FEATURES[6]] == 0).sum()),
            "reduction": int((frame[APTITUDE_FEATURES[6]] < 0).sum()),
        },
        "manual_recalculation_mismatches": sum(not row["matches"] for row in manual),
    }
    result = {
        "version": APTITUDE_VERSION,
        "created_at": datetime.now().astimezone().isoformat(),
        "source_database": str(db_paths.source),
        "protected_sha256_before": protected_before,
        "protected_sha256_after": protected_after,
        "protected_artifacts_changed": changed_protected,
        "experiment_database": str(db_paths.experiment),
        "row_count": len(frame),
        "race_count": int(frame["race_id"].nunique()),
        "feature_count": 7,
        "base_input_count": 137,
        "candidate_input_count": 144,
        "aptitude_feature_hash": aptitude_feature_hash(project_paths),
        "manual_samples": len(manual),
        "data_audit": data_audit,
        "audit_issues": issues,
    }
    (output / "audit_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if issues:
        raise ValueError("A1 audit failed: " + "; ".join(issues))
    return AptitudeFeatureOutcome(len(frame), int(frame["race_id"].nunique()), 7, 0, output)
