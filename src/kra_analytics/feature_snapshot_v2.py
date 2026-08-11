# SQL fragments intentionally remain readable as complete expressions.
# ruff: noqa: E501

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from duckdb import DuckDBPyConnection

from kra_analytics.database import connect_database, initialize_database
from kra_analytics.paths import ProjectPaths

SNAPSHOT_VERSION = "place_feature_snapshot_v2_candidate"
TABLE_NAME = "place_feature_snapshot_v2_candidate"

MANAGEMENT_COLUMNS = {
    "snapshot_id", "snapshot_version", "race_id", "horse_id", "race_date",
    "feature_as_of", "jockey_id", "trainer_id", "owner_id", "source_batch_id",
    "policy_version", "history_window_start_date", "source_max_event_date",
    "history_complete", "population_proxy", "place_hit", "result_status",
    "is_valid_start", "is_valid_finish", "population_exclusion_reason",
    "semantic_version", "created_at",
}

PROHIBITED_FEATURES = {
    "current_finish_rank", "current_race_time", "current_sectionals", "current_margin",
    "current_win_odds", "current_place_odds", "current_sales",
    "api26_current_cumulative_stats", "api37_cumulative_sectionals",
    "ilsu_as_days_since_last_start",
}


@dataclass(frozen=True)
class FeatureSnapshotV2Outcome:
    snapshot_version: str
    feature_count: int
    row_count: int
    race_count: int
    positive_count: int


def registry_feature_names(root: Path) -> tuple[str, ...]:
    path = root / "docs" / "place-feature-registry-v2.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    names = [
        row["feature_name"]
        for row in rows
        if row["recommendation_group"] == "IMMEDIATE_BASELINE"
    ]
    if len(names) != len(set(names)):
        raise ValueError("Immediate Feature registry contains duplicate names")
    return tuple(names)


def _recent_expressions(window: int) -> list[str]:
    condition = f"recency_rank <= {window}"
    prefix = f"horse_recent{window}"
    return [
        f"count(hist_race_id) FILTER (WHERE {condition})::INTEGER AS {prefix}_start_count",
        f"count(hist_race_id) FILTER (WHERE {condition} AND is_valid_finish)::DOUBLE / nullif(count(hist_race_id) FILTER (WHERE {condition}), 0) AS {prefix}_finish_rate",
        f"count(hist_race_id) FILTER (WHERE {condition} AND official_finish_rank = 1)::DOUBLE / nullif(count(hist_race_id) FILTER (WHERE {condition}), 0) AS {prefix}_win_rate",
        f"count(hist_race_id) FILTER (WHERE {condition} AND official_finish_rank <= 3)::DOUBLE / nullif(count(hist_race_id) FILTER (WHERE {condition}), 0) AS {prefix}_top3_rate",
        f"avg(official_finish_rank) FILTER (WHERE {condition} AND is_valid_finish) AS {prefix}_avg_finish_rank",
        f"min(official_finish_rank) FILTER (WHERE {condition} AND is_valid_finish) AS {prefix}_best_finish_rank",
        f"avg(rating) FILTER (WHERE {condition}) AS {prefix}_avg_rating",
        f"arg_max(rating, race_date) FILTER (WHERE {condition}) - arg_min(rating, race_date) FILTER (WHERE {condition}) AS {prefix}_rating_change",
    ]


def _condition_expressions(name: str, predicate: str) -> list[str]:
    prefix = f"horse_{name}"
    return [
        f"count(hist_race_id) FILTER (WHERE {predicate})::INTEGER AS {prefix}_start_count",
        f"count(hist_race_id) FILTER (WHERE {predicate} AND is_valid_finish)::DOUBLE / nullif(count(hist_race_id) FILTER (WHERE {predicate}), 0) AS {prefix}_finish_rate",
        f"count(hist_race_id) FILTER (WHERE {predicate} AND place_hit)::DOUBLE / nullif(count(hist_race_id) FILTER (WHERE {predicate}), 0) AS {prefix}_plc_hit_rate",
        f"avg(official_finish_rank) FILTER (WHERE {predicate} AND is_valid_finish) AS {prefix}_avg_finish_rank",
    ]


def _entity_history_cte(name: str, key: str, *, include_recent: bool) -> str:
    recent_cte = ""
    recent_join = ""
    recent_columns = ""
    if include_recent:
        recent_cte = f""",
{name}_recent AS (
    SELECT cur.race_id, cur.horse_id,
           count(hist.hist_race_id)::INTEGER AS {name}_recent10_start_count,
           count(hist.hist_race_id) FILTER (WHERE hist.place_hit)::DOUBLE /
               nullif(count(hist.hist_race_id), 0) AS {name}_recent10_plc_hit_rate
    FROM base cur
    LEFT JOIN LATERAL (
        SELECT h.race_id AS hist_race_id, h.place_hit
        FROM base h WHERE {key.replace('hist.', 'h.')}
          AND h.race_date < cur.race_date
        ORDER BY h.race_date DESC, h.race_id DESC LIMIT 10
    ) hist ON true
    GROUP BY cur.race_id, cur.horse_id
)"""
        recent_join = f"LEFT JOIN {name}_recent recent USING (race_id, horse_id)"
        recent_columns = f""",
           recent.{name}_recent10_start_count,
           recent.{name}_recent10_plc_hit_rate,
           count(hist_race_id) FILTER (WHERE hist_meet = current_meet)::INTEGER
               AS {name}_same_meet_start_count,
           count(hist_race_id) FILTER (WHERE hist_meet = current_meet AND place_hit)::DOUBLE /
               nullif(count(hist_race_id) FILTER (WHERE hist_meet = current_meet), 0)
               AS {name}_same_meet_plc_hit_rate"""
    return f"""
{name}_pairs AS (
    SELECT cur.race_id, cur.horse_id, cur.meet_code AS current_meet,
           hist.race_id AS hist_race_id, hist.race_date,
           hist.meet_code AS hist_meet, hist.place_hit
    FROM base cur
    LEFT JOIN base hist ON {key} AND hist.race_date < cur.race_date
){recent_cte},
{name}_history AS (
    SELECT race_id, horse_id, count(hist_race_id)::INTEGER AS {name}_prior_start_count,
           count(hist_race_id) FILTER (WHERE place_hit)::DOUBLE /
               nullif(count(hist_race_id), 0) AS {name}_prior_plc_hit_rate
           {recent_columns}, max(race_date) AS {name}_source_max_event_date
    FROM {name}_pairs {recent_join}
    GROUP BY race_id, horse_id{', recent.' + name + '_recent10_start_count, recent.' + name + '_recent10_plc_hit_rate' if include_recent else ''}
)"""


def _build_sql() -> str:
    horse_expressions = [
        "count(hist_race_id)::INTEGER AS horse_prior_start_count",
        "count(hist_race_id) FILTER (WHERE is_valid_finish)::INTEGER AS horse_prior_finish_count",
        "count(hist_race_id) FILTER (WHERE is_valid_finish)::DOUBLE / nullif(count(hist_race_id), 0) AS horse_prior_finish_rate",
        "count(hist_race_id) FILTER (WHERE place_hit)::DOUBLE / nullif(count(hist_race_id), 0) AS horse_prior_plc_hit_rate",
        "avg(official_finish_rank) FILTER (WHERE is_valid_finish) AS horse_prior_avg_finish_rank",
        "date_diff('day', max(race_date), max(current_race_date))::INTEGER AS horse_days_since_last_start",
        "count(hist_race_id) > 0 AS horse_history_available",
        "count(hist_race_id) FILTER (WHERE official_finish_rank = 1)::INTEGER AS horse_prior_win_count",
        "count(hist_race_id) FILTER (WHERE official_finish_rank = 1)::DOUBLE / nullif(count(hist_race_id), 0) AS horse_prior_win_rate",
        "count(hist_race_id) FILTER (WHERE official_finish_rank <= 3)::INTEGER AS horse_prior_top3_count",
        "count(hist_race_id) FILTER (WHERE official_finish_rank <= 3)::DOUBLE / nullif(count(hist_race_id), 0) AS horse_prior_top3_rate",
        "min(official_finish_rank) FILTER (WHERE is_valid_finish) AS horse_prior_best_finish_rank",
        "stddev_samp(official_finish_rank) FILTER (WHERE is_valid_finish) AS horse_prior_finish_rank_std",
        "avg(rating) AS horse_prior_rating_mean",
        "arg_max(rating, race_date) AS horse_last_rating",
        "max(current_rating) - arg_max(rating, race_date) AS horse_rating_change_last_start",
        "avg(carried_weight) AS horse_prior_carried_weight_mean",
    ]
    for window in (3, 5, 10):
        horse_expressions.extend(_recent_expressions(window))
    horse_expressions.append(
        "count(hist_race_id) FILTER (WHERE recency_rank <= 5 AND place_hit)::DOUBLE / "
        "nullif(count(hist_race_id) FILTER (WHERE recency_rank <= 5), 0) "
        "AS horse_recent5_plc_hit_rate"
    )
    horse_expressions.extend(_condition_expressions("same_meet", "meet_code = current_meet"))
    horse_expressions.extend(
        _condition_expressions("same_distance", "distance_m = current_distance")
    )
    horse_expressions.extend(
        _condition_expressions(
            "same_meet_distance",
            "meet_code = current_meet AND distance_m = current_distance",
        )
    )
    horse_expressions.extend(
        [
            "arg_max(horse_weight_kg, race_date) AS horse_last_weight_kg",
            "arg_max(horse_weight_change_kg, race_date) AS horse_last_weight_change_kg",
            "avg(horse_weight_kg) FILTER (WHERE recency_rank <= 5) AS horse_recent5_weight_mean",
            "stddev_samp(horse_weight_kg) FILTER (WHERE recency_rank <= 5) AS horse_recent5_weight_std",
            "count(horse_weight_kg) FILTER (WHERE recency_rank <= 5)::INTEGER AS horse_recent5_weight_count",
            "max(race_date) AS horse_source_max_event_date",
        ]
    )
    speed_expressions = []
    for window in (3, 5):
        for metric in ("race_time", "s1f", "g3f", "g1f"):
            speed_expressions.extend(
                [
                    f"median(value) FILTER (WHERE metric = '{metric}' AND metric_rank <= {window}) AS horse_recent{window}_{metric}_median",
                    f"count(value) FILTER (WHERE metric = '{metric}' AND metric_rank <= {window})::INTEGER AS horse_recent{window}_{metric}_count",
                ]
            )
    return f"""
CREATE OR REPLACE TABLE mart.{TABLE_NAME} AS
WITH base AS (
    SELECT rr.race_id, rr.horse_id, r.race_date, r.meet_code,
           coalesce(nullif(trim(r.race_grade), ''), 'UNKNOWN') AS race_grade,
           r.distance_m, r.runner_count AS registered_runner_count, rr.gate_no,
           coalesce(nullif(trim(rr.horse_sex), ''), 'UNKNOWN') AS horse_sex,
           rr.horse_age, rr.carried_weight, try_cast(s.rating AS INTEGER) AS rating,
           rr.jockey_id, rr.trainer_id, nullif(trim(s.owNo), '') AS owner_id,
           rr.official_finish_rank, rr.result_status, rr.is_valid_start,
           rr.is_valid_finish, rr.source_batch_id, rr.policy_version,
           nullif(trim(s.ageCond), '') AS race_age_condition,
           nullif(trim(s.budam), '') AS race_weight_condition,
           nullif(trim(s.prizeCond), '') AS race_prize_condition,
           nullif(trim(s.sexCond), '') AS race_sex_condition,
           nullif(trim(s.rcName), '') AS race_type,
           strftime(r.race_date, '%w')::INTEGER AS race_day_of_week,
           try_cast(s.chaksun1 AS BIGINT) AS race_first_prize,
           try_cast(s.chaksun2 AS BIGINT) AS race_second_prize,
           try_cast(s.chaksun3 AS BIGINT) AS race_third_prize,
           try_cast(s.chaksun4 AS BIGINT) AS race_fourth_prize,
           try_cast(s.chaksun5 AS BIGINT) AS race_fifth_prize,
           try_cast(s.buga1 AS BIGINT) AS race_bonus_1,
           try_cast(s.buga2 AS BIGINT) AS race_bonus_2,
           try_cast(s.buga3 AS BIGINT) AS race_bonus_3,
           e.weather AS current_weather, e.track_condition AS current_track_condition,
           e.track_moisture_percent AS current_track_moisture_percent,
           e.horse_weight_kg AS current_horse_weight_kg,
           e.horse_weight_change_kg AS current_horse_weight_change_kg,
           e.valid_race_time_seconds, e.s1f_seconds,
           e.historical_g3f_seconds, e.historical_g1f_seconds,
           EXISTS (SELECT 1 FROM canonical.winning_payout wp
                   WHERE wp.race_id = rr.race_id AND wp.pool_code = '연식'
                     AND wp.selection_count = 1 AND wp.horse_no_1 = rr.gate_no) AS place_hit
    FROM canonical.runner_result rr
    JOIN canonical.race r USING (race_id)
    JOIN analytics.fact_race fr USING (race_id)
    JOIN staging.race_result s ON s.staging_row_id = rr.source_staging_row_id
    JOIN semantic.api4_runner_event_v2 e ON e.staging_row_id = s.staging_row_id
    WHERE fr.is_market_eligible AND rr.is_valid_start
),
horse_pairs AS (
    SELECT cur.race_id, cur.horse_id, cur.race_date AS current_race_date,
           cur.rating AS current_rating, cur.meet_code AS current_meet,
           cur.distance_m AS current_distance, hist.race_id AS hist_race_id,
           hist.race_date, hist.meet_code, hist.distance_m, hist.is_valid_finish,
           hist.official_finish_rank, hist.place_hit, hist.rating, hist.carried_weight,
           hist.current_horse_weight_kg AS horse_weight_kg,
           hist.current_horse_weight_change_kg AS horse_weight_change_kg,
           hist.valid_race_time_seconds, hist.s1f_seconds,
           hist.historical_g3f_seconds, hist.historical_g1f_seconds,
           row_number() OVER (PARTITION BY cur.race_id, cur.horse_id
                              ORDER BY hist.race_date DESC, hist.race_id DESC) recency_rank
    FROM base cur LEFT JOIN base hist
      ON hist.horse_id = cur.horse_id AND hist.race_date < cur.race_date
),
horse_history AS (
    SELECT race_id, horse_id, {', '.join(horse_expressions)}
    FROM horse_pairs GROUP BY race_id, horse_id
),
speed_long AS (
    SELECT race_id, horse_id, hist_race_id, race_date, metric, value,
           row_number() OVER (PARTITION BY race_id, horse_id, metric
                              ORDER BY race_date DESC, hist_race_id DESC) metric_rank
    FROM horse_pairs
    UNPIVOT (value FOR metric IN (
        valid_race_time_seconds AS race_time, s1f_seconds AS s1f,
        historical_g3f_seconds AS g3f, historical_g1f_seconds AS g1f
    )) WHERE value IS NOT NULL
),
speed_history AS (
    SELECT race_id, horse_id, {', '.join(speed_expressions)}
    FROM speed_long GROUP BY race_id, horse_id
),
{_entity_history_cte('jockey', 'hist.jockey_id = cur.jockey_id AND cur.jockey_id IS NOT NULL', include_recent=True)},
{_entity_history_cte('trainer', 'hist.trainer_id = cur.trainer_id AND cur.trainer_id IS NOT NULL', include_recent=True)},
{_entity_history_cte('horse_jockey', 'hist.horse_id = cur.horse_id AND hist.jockey_id = cur.jockey_id AND cur.jockey_id IS NOT NULL', include_recent=True)},
{_entity_history_cte('owner', 'hist.owner_id = cur.owner_id AND cur.owner_id IS NOT NULL', include_recent=False)},
{_entity_history_cte('horse_trainer', 'hist.horse_id = cur.horse_id AND hist.trainer_id = cur.trainer_id AND cur.trainer_id IS NOT NULL', include_recent=False)},
history_bounds AS (SELECT min(race_date) history_window_start_date FROM canonical.race)
SELECT md5('{SNAPSHOT_VERSION}|' || b.race_id || '|' || b.horse_id) snapshot_id,
       '{SNAPSHOT_VERSION}' snapshot_version, b.race_id, b.horse_id,
       b.race_date, b.race_date feature_as_of,
       b.* EXCLUDE (race_id, horse_id, race_date, jockey_id, trainer_id, owner_id,
                    official_finish_rank, place_hit, result_status, is_valid_start,
                    is_valid_finish, source_batch_id, policy_version,
                    valid_race_time_seconds, s1f_seconds,
                    historical_g3f_seconds, historical_g1f_seconds),
       hh.* EXCLUDE (race_id, horse_id, horse_source_max_event_date),
       sh.* EXCLUDE (race_id, horse_id),
       jh.* EXCLUDE (race_id, horse_id, jockey_source_max_event_date),
       th.* EXCLUDE (race_id, horse_id, trainer_source_max_event_date),
       hjh.* EXCLUDE (race_id, horse_id, horse_jockey_prior_start_count,
                      horse_jockey_prior_plc_hit_rate,
                      horse_jockey_source_max_event_date),
       oh.owner_prior_start_count, oh.owner_prior_plc_hit_rate,
       hth.horse_trainer_prior_start_count, hth.horse_trainer_prior_plc_hit_rate,
       coalesce(jh.jockey_prior_start_count > 0, false) jockey_history_available,
       coalesce(th.trainer_prior_start_count > 0, false) trainer_history_available,
       b.jockey_id, b.trainer_id, b.owner_id, b.source_batch_id, b.policy_version,
       hb.history_window_start_date,
       greatest(hh.horse_source_max_event_date, jh.jockey_source_max_event_date,
                th.trainer_source_max_event_date, hjh.horse_jockey_source_max_event_date,
                oh.owner_source_max_event_date, hth.horse_trainer_source_max_event_date)
           AS source_max_event_date,
       false history_complete, 'POST_RACE_VALID_START_PROXY' population_proxy,
       b.place_hit, b.result_status, b.is_valid_start, b.is_valid_finish,
       null::VARCHAR population_exclusion_reason,
       'api4_runner_event_v2' semantic_version, now() created_at
FROM base b JOIN horse_history hh USING (race_id, horse_id)
LEFT JOIN speed_history sh USING (race_id, horse_id)
JOIN jockey_history jh USING (race_id, horse_id)
JOIN trainer_history th USING (race_id, horse_id)
JOIN horse_jockey_history hjh USING (race_id, horse_id)
JOIN owner_history oh USING (race_id, horse_id)
JOIN horse_trainer_history hth USING (race_id, horse_id)
CROSS JOIN history_bounds hb
"""


def _audit(connection: DuckDBPyConnection, expected_features: tuple[str, ...]) -> list[str]:
    table = f"mart.{TABLE_NAME}"
    issues: list[str] = []
    scalar_checks = {
        "DUPLICATE_KEY": f"SELECT count(*)-count(DISTINCT race_id || '|' || horse_id) FROM {table}",
        "POPULATION_MISMATCH": f"SELECT abs((SELECT count(*) FROM canonical.runner_result rr JOIN analytics.fact_race fr USING(race_id) WHERE fr.is_market_eligible AND rr.is_valid_start)-(SELECT count(*) FROM {table}))",
        "PIT_VIOLATION": f"SELECT count(*) FROM {table} WHERE source_max_event_date >= feature_as_of",
        "RECENT_COUNT_VIOLATION": f"SELECT count(*) FROM {table} WHERE horse_recent3_start_count > horse_recent5_start_count OR horse_recent5_start_count > horse_recent10_start_count",
        "CONDITION_COUNT_VIOLATION": f"SELECT count(*) FROM {table} WHERE horse_same_distance_start_count > horse_prior_start_count OR horse_same_meet_start_count > horse_prior_start_count OR horse_same_meet_distance_start_count > horse_same_distance_start_count OR horse_same_meet_distance_start_count > horse_same_meet_start_count",
        "HISTORY_FLAG_VIOLATION": f"SELECT count(*) FROM {table} WHERE horse_history_available <> (horse_prior_start_count > 0) OR jockey_history_available <> (jockey_prior_start_count > 0) OR trainer_history_available <> (trainer_prior_start_count > 0)",
    }
    for issue, query in scalar_checks.items():
        result = connection.execute(query).fetchone()
        assert result is not None
        if int(result[0]):
            issues.append(issue)
    actual = {str(row[0]) for row in connection.execute(f"DESCRIBE {table}").fetchall()}
    if set(expected_features) != actual - MANAGEMENT_COLUMNS:
        issues.append("FEATURE_REGISTRY_SCHEMA_MISMATCH")
    if actual & PROHIBITED_FEATURES:
        issues.append("PROHIBITED_CURRENT_RESULT_FEATURE")
    return issues


def build_feature_snapshot_v2(*, paths: ProjectPaths | None = None) -> FeatureSnapshotV2Outcome:
    project_paths = paths or ProjectPaths.from_root()
    expected_features = registry_feature_names(project_paths.root)
    initialize_database(paths=project_paths)
    with connect_database(paths=project_paths) as connection:
        connection.begin()
        try:
            connection.execute(_build_sql())
            issues = _audit(connection, expected_features)
            if issues:
                raise ValueError(f"Feature Snapshot v2 audit failed: {issues}")
            row = connection.execute(
                f"SELECT count(*), count(DISTINCT race_id), count(*) FILTER (WHERE place_hit) FROM mart.{TABLE_NAME}"
            ).fetchone()
            assert row is not None
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return FeatureSnapshotV2Outcome(
        SNAPSHOT_VERSION, len(expected_features), int(row[0]), int(row[1]), int(row[2])
    )


def audit_feature_snapshot_v2(*, paths: ProjectPaths | None = None) -> list[str]:
    project_paths = paths or ProjectPaths.from_root()
    with connect_database(paths=project_paths, read_only=True) as connection:
        return _audit(connection, registry_feature_names(project_paths.root))
