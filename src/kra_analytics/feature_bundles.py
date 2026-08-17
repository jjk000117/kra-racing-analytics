# SQL fragments intentionally remain readable as complete expressions.
# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from duckdb import DuckDBPyConnection

from kra_analytics.database import connect_database, initialize_database
from kra_analytics.development_evaluation import verify_sealed_artifacts
from kra_analytics.modeling_v2 import load_feature_contract
from kra_analytics.paths import ProjectPaths

BASE_TABLE = "mart.place_feature_snapshot_v2_candidate"
ENGINEERED_TABLE = "mart.place_feature_snapshot_v2_engineered_candidate"
SOURCE_AUDIT_TABLE = "quality.post_baseline_v2_feature_source_audit"
REGISTRY = "docs/post-baseline-v2-feature-bundle-registry.csv"
OUTPUT_DIRECTORY = "data/exports/validation/post_baseline_v2_feature_bundles"

F1_FEATURES = (
    "horse_recent3_race_relative_time_advantage_median",
    "horse_recent3_race_time_percentile_median",
    "horse_recent3_race_relative_time_count",
    "horse_recent5_race_relative_time_advantage_median",
    "horse_recent5_race_time_percentile_median",
    "horse_recent5_race_relative_time_count",
)
F2_FEATURES = (
    "horse_recent3_late_kick_advantage_median",
    "horse_recent3_late_kick_advantage_count",
    "horse_recent5_late_kick_advantage_median",
    "horse_recent5_late_kick_advantage_count",
    "horse_recent3_finish_vs_start_advantage_median",
    "horse_recent3_finish_vs_start_advantage_count",
    "horse_recent5_finish_vs_start_advantage_median",
    "horse_recent5_finish_vs_start_advantage_count",
)
F3_FEATURES = (
    "rating_field_percentile",
    "carried_weight_vs_field_median_kg",
    "horse_prior_plc_hit_rate_field_percentile",
    "horse_recent5_plc_hit_rate_field_percentile",
    "horse_same_distance_plc_hit_rate_field_percentile",
    "jockey_recent10_plc_hit_rate_field_percentile",
    "trainer_recent10_plc_hit_rate_field_percentile",
    "horse_recent5_s1f_field_percentile",
    "horse_recent5_g3f_field_percentile",
    "horse_recent5_g1f_field_percentile",
)
BUNDLE_FEATURES = {"F1": F1_FEATURES, "F2": F2_FEATURES, "F3": F3_FEATURES}
ALL_BUNDLE_FEATURES = F1_FEATURES + F2_FEATURES + F3_FEATURES


@dataclass(frozen=True)
class FeatureBundleOutcome:
    row_count: int
    race_count: int
    feature_count: int
    audit_issue_count: int
    output_directory: Path


def _registry_rows(paths: ProjectPaths) -> list[dict[str, str]]:
    with (paths.root / REGISTRY).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    names = tuple(row["feature_name"] for row in rows)
    if names != ALL_BUNDLE_FEATURES:
        raise ValueError("Feature bundle registry order or names differ from the sealed contract")
    if len(names) != 24 or len(set(names)) != 24:
        raise ValueError("Expected exactly 24 unique Feature bundle columns")
    return rows


def bundle_feature_hash(paths: ProjectPaths) -> str:
    _registry_rows(paths)
    return hashlib.sha256(("\n".join(ALL_BUNDLE_FEATURES) + "\n").encode()).hexdigest()


def _higher_percentile(source: str) -> str:
    return (
        f"CASE WHEN {source} IS NOT NULL AND count({source}) OVER (PARTITION BY race_id) >= 3 "
        f"THEN (rank() OVER (PARTITION BY race_id ORDER BY {source}) + "
        f"(count(*) OVER (PARTITION BY race_id, {source}) - 1) / 2.0 - 1) / "
        f"(count({source}) OVER (PARTITION BY race_id) - 1) END"
    )


def _lower_percentile(source: str) -> str:
    return (
        f"CASE WHEN {source} IS NOT NULL AND count({source}) OVER (PARTITION BY race_id) >= 3 "
        f"THEN (count({source}) OVER (PARTITION BY race_id) - rank() OVER "
        f"(PARTITION BY race_id ORDER BY {source}) - "
        f"(count(*) OVER (PARTITION BY race_id, {source}) - 1) / 2.0) / "
        f"(count({source}) OVER (PARTITION BY race_id) - 1) END"
    )


def _build_sql() -> str:
    f3_expressions = [
        f"{_higher_percentile('rating')} AS rating_field_percentile",
        "CASE WHEN carried_weight IS NOT NULL AND count(carried_weight) OVER "
        "(PARTITION BY race_id) >= 3 THEN carried_weight - median(carried_weight) OVER "
        "(PARTITION BY race_id) END AS carried_weight_vs_field_median_kg",
        f"{_higher_percentile('horse_prior_plc_hit_rate')} AS horse_prior_plc_hit_rate_field_percentile",
        f"{_higher_percentile('horse_recent5_plc_hit_rate')} AS horse_recent5_plc_hit_rate_field_percentile",
        f"{_higher_percentile('horse_same_distance_plc_hit_rate')} AS horse_same_distance_plc_hit_rate_field_percentile",
        f"{_higher_percentile('jockey_recent10_plc_hit_rate')} AS jockey_recent10_plc_hit_rate_field_percentile",
        f"{_higher_percentile('trainer_recent10_plc_hit_rate')} AS trainer_recent10_plc_hit_rate_field_percentile",
        f"{_lower_percentile('horse_recent5_s1f_median')} AS horse_recent5_s1f_field_percentile",
        f"{_lower_percentile('horse_recent5_g3f_median')} AS horse_recent5_g3f_field_percentile",
        f"{_lower_percentile('horse_recent5_g1f_median')} AS horse_recent5_g1f_field_percentile",
    ]
    return f"""
CREATE OR REPLACE TABLE {ENGINEERED_TABLE} AS
WITH event_source AS (
    SELECT b.race_id, b.horse_id, b.race_date,
           rr.result_status, rr.is_valid_start, rr.is_valid_finish,
           e.valid_race_time_seconds AS race_time,
           e.s1f_seconds AS s1f, e.historical_g3f_seconds AS g3f,
           e.historical_g1f_seconds AS g1f
    FROM {BASE_TABLE} b
    JOIN canonical.runner_result rr USING (race_id, horse_id)
    JOIN semantic.api4_runner_event_v2 e
      ON e.staging_row_id = rr.source_staging_row_id
),
f1_ranked AS (
    SELECT race_id, horse_id, race_date, race_time,
           count(*) OVER (PARTITION BY race_id) AS comparison_count,
           median(race_time) OVER (PARTITION BY race_id) AS race_median_time,
           rank() OVER (PARTITION BY race_id ORDER BY race_time) +
             (count(*) OVER (PARTITION BY race_id, race_time) - 1) / 2.0 AS average_rank
    FROM event_source
    WHERE is_valid_start AND is_valid_finish AND result_status = 'FINISHED'
      AND race_time IS NOT NULL AND race_time > 0
),
f1_events AS (
    SELECT race_id, horse_id, race_date, comparison_count,
           race_median_time - race_time AS time_advantage,
           (comparison_count - average_rank) / (comparison_count - 1) AS time_percentile
    FROM f1_ranked WHERE comparison_count >= 3
),
f1_history AS (
    SELECT cur.race_id, cur.horse_id, hist.race_id AS historical_race_id,
           hist.race_date AS historical_race_date, hist.comparison_count,
           hist.time_advantage, hist.time_percentile,
           row_number() OVER (PARTITION BY cur.race_id, cur.horse_id
                              ORDER BY hist.race_date DESC, hist.race_id DESC) AS recency_rank
    FROM {BASE_TABLE} cur
    LEFT JOIN f1_events hist ON hist.horse_id = cur.horse_id
                            AND hist.race_date < cur.feature_as_of
),
f1 AS (
    SELECT race_id, horse_id,
           median(time_advantage) FILTER (WHERE recency_rank <= 3) AS horse_recent3_race_relative_time_advantage_median,
           median(time_percentile) FILTER (WHERE recency_rank <= 3) AS horse_recent3_race_time_percentile_median,
           count(historical_race_id) FILTER (WHERE recency_rank <= 3)::INTEGER AS horse_recent3_race_relative_time_count,
           median(time_advantage) FILTER (WHERE recency_rank <= 5) AS horse_recent5_race_relative_time_advantage_median,
           median(time_percentile) FILTER (WHERE recency_rank <= 5) AS horse_recent5_race_time_percentile_median,
           count(historical_race_id) FILTER (WHERE recency_rank <= 5)::INTEGER AS horse_recent5_race_relative_time_count,
           max(historical_race_date) AS f1_source_max_event_date
    FROM f1_history GROUP BY race_id, horse_id
),
f2_events AS (
    SELECT race_id, horse_id, race_date, 'late_kick' AS metric,
           (g3f - 3 * g1f) / 2 AS value
    FROM event_source
    WHERE is_valid_start AND is_valid_finish AND result_status = 'FINISHED'
      AND g3f IS NOT NULL AND g1f IS NOT NULL
    UNION ALL
    SELECT race_id, horse_id, race_date, 'finish_vs_start' AS metric, s1f - g1f AS value
    FROM event_source
    WHERE is_valid_start AND is_valid_finish AND result_status = 'FINISHED'
      AND s1f IS NOT NULL AND g1f IS NOT NULL
),
f2_history AS (
    SELECT cur.race_id, cur.horse_id, hist.race_id AS historical_race_id,
           hist.race_date AS historical_race_date, hist.metric, hist.value,
           row_number() OVER (PARTITION BY cur.race_id, cur.horse_id, hist.metric
                              ORDER BY hist.race_date DESC, hist.race_id DESC) AS recency_rank
    FROM {BASE_TABLE} cur
    LEFT JOIN f2_events hist ON hist.horse_id = cur.horse_id
                            AND hist.race_date < cur.feature_as_of
),
f2 AS (
    SELECT race_id, horse_id,
           median(value) FILTER (WHERE metric='late_kick' AND recency_rank <= 3) AS horse_recent3_late_kick_advantage_median,
           count(historical_race_id) FILTER (WHERE metric='late_kick' AND recency_rank <= 3)::INTEGER AS horse_recent3_late_kick_advantage_count,
           median(value) FILTER (WHERE metric='late_kick' AND recency_rank <= 5) AS horse_recent5_late_kick_advantage_median,
           count(historical_race_id) FILTER (WHERE metric='late_kick' AND recency_rank <= 5)::INTEGER AS horse_recent5_late_kick_advantage_count,
           median(value) FILTER (WHERE metric='finish_vs_start' AND recency_rank <= 3) AS horse_recent3_finish_vs_start_advantage_median,
           count(historical_race_id) FILTER (WHERE metric='finish_vs_start' AND recency_rank <= 3)::INTEGER AS horse_recent3_finish_vs_start_advantage_count,
           median(value) FILTER (WHERE metric='finish_vs_start' AND recency_rank <= 5) AS horse_recent5_finish_vs_start_advantage_median,
           count(historical_race_id) FILTER (WHERE metric='finish_vs_start' AND recency_rank <= 5)::INTEGER AS horse_recent5_finish_vs_start_advantage_count,
           max(historical_race_date) AS f2_source_max_event_date
    FROM f2_history GROUP BY race_id, horse_id
),
f3 AS (
    SELECT race_id, horse_id, {', '.join(f3_expressions)}
    FROM {BASE_TABLE}
)
SELECT b.*, {', '.join('f1.' + name for name in F1_FEATURES)},
       {', '.join('f2.' + name for name in F2_FEATURES)},
       {', '.join('f3.' + name for name in F3_FEATURES)}
FROM {BASE_TABLE} b
JOIN f1 USING (race_id, horse_id)
JOIN f2 USING (race_id, horse_id)
JOIN f3 USING (race_id, horse_id);

CREATE OR REPLACE TABLE {SOURCE_AUDIT_TABLE} AS
WITH event_source AS (
    SELECT b.race_id, b.horse_id, b.race_date,
           rr.result_status, rr.is_valid_start, rr.is_valid_finish,
           e.valid_race_time_seconds AS race_time,
           e.s1f_seconds AS s1f, e.historical_g3f_seconds AS g3f,
           e.historical_g1f_seconds AS g1f
    FROM {BASE_TABLE} b
    JOIN canonical.runner_result rr USING (race_id, horse_id)
    JOIN semantic.api4_runner_event_v2 e
      ON e.staging_row_id = rr.source_staging_row_id
), f1 AS (
    SELECT cur.race_id, cur.horse_id, max(hist.race_date) AS f1_source_max_event_date
    FROM {BASE_TABLE} cur LEFT JOIN event_source hist
      ON hist.horse_id=cur.horse_id AND hist.race_date < cur.feature_as_of
     AND hist.is_valid_start AND hist.is_valid_finish AND hist.result_status='FINISHED'
     AND hist.race_time IS NOT NULL AND hist.race_time > 0
    GROUP BY cur.race_id, cur.horse_id
), f2 AS (
    SELECT cur.race_id, cur.horse_id, max(hist.race_date) AS f2_source_max_event_date
    FROM {BASE_TABLE} cur LEFT JOIN event_source hist
      ON hist.horse_id=cur.horse_id AND hist.race_date < cur.feature_as_of
     AND hist.is_valid_start AND hist.is_valid_finish AND hist.result_status='FINISHED'
     AND ((hist.g3f IS NOT NULL AND hist.g1f IS NOT NULL)
       OR (hist.s1f IS NOT NULL AND hist.g1f IS NOT NULL))
    GROUP BY cur.race_id, cur.horse_id
)
SELECT b.race_id, b.horse_id, b.feature_as_of,
       f1.f1_source_max_event_date, f2.f2_source_max_event_date
FROM {BASE_TABLE} b JOIN f1 USING (race_id, horse_id) JOIN f2 USING (race_id, horse_id);
"""


def _scalar(connection: DuckDBPyConnection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise ValueError("Scalar audit query returned no row")
    return int(row[0])


def build_feature_bundles(*, paths: ProjectPaths | None = None) -> FeatureBundleOutcome:
    project_paths = paths or ProjectPaths.from_root()
    _registry_rows(project_paths)
    initialize_database(paths=project_paths)
    with connect_database(paths=project_paths) as connection:
        connection.execute("BEGIN")
        try:
            connection.execute(_build_sql())
            issues = audit_feature_bundles(connection=connection, paths=project_paths, export=True)
            if issues:
                raise ValueError("; ".join(issues))
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        rows = _scalar(connection, f"SELECT count(*) FROM {ENGINEERED_TABLE}")
        races = _scalar(connection, f"SELECT count(DISTINCT race_id) FROM {ENGINEERED_TABLE}")
    return FeatureBundleOutcome(rows, races, 24, 0, project_paths.root / OUTPUT_DIRECTORY)


def _write_query(connection: DuckDBPyConnection, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(path).replace("'", "''")
    connection.execute(f"COPY ({query}) TO '{escaped}' (HEADER, DELIMITER ',')")


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def audit_feature_bundles(
    *, connection: DuckDBPyConnection | None = None,
    paths: ProjectPaths | None = None,
    export: bool = True,
) -> list[str]:
    project_paths = paths or ProjectPaths.from_root()
    _registry_rows(project_paths)
    owned = connection is None
    context = connect_database(paths=project_paths) if owned else None
    conn = context.__enter__() if context is not None else connection
    assert conn is not None
    try:
        issues: list[str] = []
        base_rows = _scalar(conn, f"SELECT count(*) FROM {BASE_TABLE}")
        rows = _scalar(conn, f"SELECT count(*) FROM {ENGINEERED_TABLE}")
        duplicates = _scalar(conn, f"SELECT count(*)-count(DISTINCT (race_id,horse_id)) FROM {ENGINEERED_TABLE}")
        if rows != base_rows:
            issues.append(f"row count mismatch: base={base_rows}, engineered={rows}")
        if duplicates:
            issues.append(f"business-key duplicates={duplicates}")
        columns = {str(row[0]) for row in conn.execute(f"DESCRIBE {ENGINEERED_TABLE}").fetchall()}
        if set(ALL_BUNDLE_FEATURES) - columns:
            issues.append("registry Feature columns missing from engineered Snapshot")
        percentile_features = tuple(name for name in ALL_BUNDLE_FEATURES if "percentile" in name)
        range_errors = sum(
            _scalar(conn, f"SELECT count(*) FROM {ENGINEERED_TABLE} WHERE {name}<0 OR {name}>1")
            for name in percentile_features
        )
        if range_errors:
            issues.append(f"percentile range errors={range_errors}")
        count_pairs = (
            ("horse_recent3_race_relative_time_count", "horse_recent5_race_relative_time_count"),
            ("horse_recent3_late_kick_advantage_count", "horse_recent5_late_kick_advantage_count"),
            ("horse_recent3_finish_vs_start_advantage_count", "horse_recent5_finish_vs_start_advantage_count"),
        )
        for short, long in count_pairs:
            violations = _scalar(conn, f"SELECT count(*) FROM {ENGINEERED_TABLE} WHERE {short}>{long}")
            if violations:
                issues.append(f"count relation {short}<={long} violations={violations}")
        value_pairs = (
            ("horse_recent3_race_relative_time_count", F1_FEATURES[:2]),
            ("horse_recent5_race_relative_time_count", F1_FEATURES[3:5]),
            ("horse_recent3_late_kick_advantage_count", (F2_FEATURES[0],)),
            ("horse_recent5_late_kick_advantage_count", (F2_FEATURES[2],)),
            ("horse_recent3_finish_vs_start_advantage_count", (F2_FEATURES[4],)),
            ("horse_recent5_finish_vs_start_advantage_count", (F2_FEATURES[6],)),
        )
        for count_name, values in value_pairs:
            for value in values:
                contradictions = _scalar(conn, f"SELECT count(*) FROM {ENGINEERED_TABLE} WHERE ({count_name}=0 AND {value} IS NOT NULL) OR ({count_name}>0 AND {value} IS NULL)")
                if contradictions:
                    issues.append(f"count/value contradiction {count_name}/{value}={contradictions}")
        pit = _scalar(conn, f"SELECT count(*) FROM {SOURCE_AUDIT_TABLE} WHERE f1_source_max_event_date>=feature_as_of OR f2_source_max_event_date>=feature_as_of")
        if pit:
            issues.append(f"historical PIT violations={pit}")

        if export:
            output = project_paths.root / OUTPUT_DIRECTORY
            output.mkdir(parents=True, exist_ok=True)
            unions = []
            for bundle, names in BUNDLE_FEATURES.items():
                for name in names:
                    unions.append(
                        f"SELECT '{bundle}' bundle, '{name}' feature_name, count({name}) non_null_count, "
                        f"count({name})::DOUBLE/count(*) availability_rate, min({name}) minimum, "
                        f"median({name}) median, max({name}) maximum FROM {ENGINEERED_TABLE}"
                    )
            _write_query(conn, " UNION ALL ".join(unions), output / "feature_profile_overall.csv")
            year_queries = []
            meet_queries = []
            for bundle, names in BUNDLE_FEATURES.items():
                for name in names:
                    year_queries.append(f"SELECT year(race_date) calendar_year, '{bundle}' bundle, '{name}' feature_name, count({name}) non_null_count, count({name})::DOUBLE/count(*) availability_rate FROM {ENGINEERED_TABLE} GROUP BY year(race_date)")
                    meet_queries.append(f"SELECT meet_code, '{bundle}' bundle, '{name}' feature_name, count({name}) non_null_count, count({name})::DOUBLE/count(*) availability_rate FROM {ENGINEERED_TABLE} GROUP BY meet_code")
            _write_query(conn, " UNION ALL ".join(year_queries) + " ORDER BY calendar_year,bundle,feature_name", output / "availability_by_year.csv")
            _write_query(conn, " UNION ALL ".join(meet_queries) + " ORDER BY meet_code,bundle,feature_name", output / "availability_by_meet.csv")
            _write_query(conn, "SELECT comparison_count, count(*) event_runner_rows, count(DISTINCT race_id) races FROM (SELECT race_id, count(*) OVER(PARTITION BY race_id) comparison_count FROM canonical.runner_result rr JOIN semantic.api4_runner_event_v2 e ON e.staging_row_id=rr.source_staging_row_id WHERE rr.is_valid_start AND rr.is_valid_finish AND rr.result_status='FINISHED' AND e.valid_race_time_seconds IS NOT NULL AND e.valid_race_time_seconds>0) GROUP BY comparison_count ORDER BY comparison_count", output / "f1_comparison_population.csv")
            _write_query(conn, "SELECT year(r.race_date) calendar_year, r.meet_code, count(*) eligible_finished_rows, count(*) FILTER(WHERE e.historical_g3f_seconds IS NOT NULL AND e.historical_g1f_seconds IS NOT NULL) late_kick_joint_rows, count(*) FILTER(WHERE e.s1f_seconds IS NOT NULL AND e.historical_g1f_seconds IS NOT NULL) finish_start_joint_rows FROM canonical.runner_result rr JOIN canonical.race r USING(race_id) JOIN semantic.api4_runner_event_v2 e ON e.staging_row_id=rr.source_staging_row_id WHERE rr.is_valid_start AND rr.is_valid_finish AND rr.result_status='FINISHED' GROUP BY year(r.race_date),r.meet_code ORDER BY calendar_year,r.meet_code", output / "f2_joint_sectional_availability.csv")
            f3_sources = {
                "rating_field_percentile": "rating", "carried_weight_vs_field_median_kg": "carried_weight",
                "horse_prior_plc_hit_rate_field_percentile": "horse_prior_plc_hit_rate", "horse_recent5_plc_hit_rate_field_percentile": "horse_recent5_plc_hit_rate",
                "horse_same_distance_plc_hit_rate_field_percentile": "horse_same_distance_plc_hit_rate", "jockey_recent10_plc_hit_rate_field_percentile": "jockey_recent10_plc_hit_rate",
                "trainer_recent10_plc_hit_rate_field_percentile": "trainer_recent10_plc_hit_rate", "horse_recent5_s1f_field_percentile": "horse_recent5_s1f_median",
                "horse_recent5_g3f_field_percentile": "horse_recent5_g3f_median", "horse_recent5_g1f_field_percentile": "horse_recent5_g1f_median",
            }
            f3_queries = [f"SELECT '{feature}' feature_name, comparable_count, count(*) runner_rows, count(*) FILTER(WHERE comparable_count<3)::DOUBLE/count(*) under_three_rate FROM (SELECT count({source}) OVER(PARTITION BY race_id) comparable_count FROM {BASE_TABLE}) GROUP BY comparable_count" for feature, source in f3_sources.items()]
            _write_query(conn, " UNION ALL ".join(f3_queries) + " ORDER BY feature_name,comparable_count", output / "f3_comparable_field_sizes.csv")
            _write_query(
                conn,
                """
                WITH eligible AS (
                    SELECT rr.race_id, rr.horse_id, e.valid_race_time_seconds race_time
                    FROM canonical.runner_result rr
                    JOIN semantic.api4_runner_event_v2 e
                      ON e.staging_row_id=rr.source_staging_row_id
                    WHERE rr.is_valid_start AND rr.is_valid_finish
                      AND rr.result_status='FINISHED'
                      AND e.valid_race_time_seconds IS NOT NULL
                      AND e.valid_race_time_seconds > 0
                ), sampled AS (
                    SELECT race_id FROM eligible GROUP BY race_id HAVING count(*)>=3
                    ORDER BY race_id LIMIT 5
                )
                SELECT e.race_id, e.horse_id, e.race_time, count(*) OVER w comparable_count,
                       median(e.race_time) OVER w race_median_time,
                       median(e.race_time) OVER w-e.race_time time_advantage,
                       (count(*) OVER w-1-
                         (SELECT count(*) FROM eligible x
                          WHERE x.race_id=e.race_id AND x.race_time<e.race_time)-
                         ((SELECT count(*) FROM eligible x
                           WHERE x.race_id=e.race_id AND x.race_time=e.race_time)-1)/2.0)
                         /(count(*) OVER w-1) independently_recalculated_percentile
                FROM eligible e JOIN sampled USING(race_id)
                WINDOW w AS (PARTITION BY e.race_id)
                ORDER BY e.race_id,e.race_time,e.horse_id
                """,
                output / "f1_percentile_sample_recalculation.csv",
            )
            _write_query(
                conn,
                f"""
                WITH sampled AS (
                    SELECT race_id FROM {BASE_TABLE}
                    GROUP BY race_id ORDER BY race_id LIMIT 3
                ), source AS (
                    SELECT b.race_id,b.horse_id,b.rating,
                           e.rating_field_percentile stored_percentile,
                           count(b.rating) OVER(PARTITION BY b.race_id) comparable_count
                    FROM {BASE_TABLE} b
                    JOIN {ENGINEERED_TABLE} e USING(race_id,horse_id)
                    WHERE b.race_id IN (SELECT race_id FROM sampled)
                ), recalculated AS (
                SELECT s.*,
                       ((SELECT count(*) FROM source x WHERE x.race_id=s.race_id
                         AND x.rating<s.rating)+
                        ((SELECT count(*) FROM source x WHERE x.race_id=s.race_id
                          AND x.rating=s.rating)-1)/2.0)/(s.comparable_count-1)
                          independently_recalculated_percentile
                FROM source s)
                SELECT *, stored_percentile-independently_recalculated_percentile difference
                FROM recalculated ORDER BY race_id,rating,horse_id
                """,
                output / "f3_percentile_sample_recalculation.csv",
            )
            duplicate_queries = (
                ("horse_recent3_race_relative_time_count", "horse_recent3_race_time_count"),
                ("horse_recent5_race_relative_time_count", "horse_recent5_race_time_count"),
                ("horse_recent3_late_kick_advantage_count", "horse_recent3_g3f_count"),
                ("horse_recent5_late_kick_advantage_count", "horse_recent5_g3f_count"),
                ("horse_recent3_finish_vs_start_advantage_count", "horse_recent3_s1f_count"),
                ("horse_recent5_finish_vs_start_advantage_count", "horse_recent5_s1f_count"),
            )
            _write_query(
                conn,
                " UNION ALL ".join(
                    f"SELECT '{new}' new_feature, '{old}' existing_feature, "
                    f"count(*) FILTER(WHERE {new} IS DISTINCT FROM {old}) differing_rows, "
                    f"count(*) total_rows FROM {ENGINEERED_TABLE}"
                    for new, old in duplicate_queries
                ),
                output / "structural_duplicate_audit.csv",
            )
            protection = json.loads(
                (project_paths.root / "docs/official-place-baseline-v2-protection.json")
                .read_text(encoding="utf-8")
            )
            sealed_hashes = verify_sealed_artifacts(project_paths, protection["artifacts"])
            base_contract = load_feature_contract(project_paths)
            summary: dict[str, Any] = {
                "generated_at": datetime.now().astimezone().isoformat(), "base_rows": base_rows,
                "engineered_rows": rows, "races": _scalar(conn, f"SELECT count(DISTINCT race_id) FROM {ENGINEERED_TABLE}"),
                "bundle_feature_count": 24, "bundle_feature_hash": bundle_feature_hash(project_paths),
                "percentile_range_errors": range_errors, "pit_violations": pit, "issues": issues,
                "base_model_input_count": len(base_contract.inputs),
                "base_model_input_hash": base_contract.feature_hash,
                "sealed_artifact_hashes": sealed_hashes,
            }
            (output / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        return issues
    finally:
        if context is not None:
            context.__exit__(None, None, None)
