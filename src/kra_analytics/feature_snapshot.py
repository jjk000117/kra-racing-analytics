from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from duckdb import DuckDBPyConnection

from kra_analytics.canonical import POLICY_VERSION
from kra_analytics.canonical import TRANSFORM_VERSION as CANONICAL_TRANSFORM_VERSION
from kra_analytics.database import connect_database, initialize_database
from kra_analytics.paths import ProjectPaths
from kra_analytics.star import TRANSFORM_VERSION as STAR_TRANSFORM_VERSION

SNAPSHOT_VERSION = "place_feature_snapshot_v1"

MODEL_FEATURES = (
    "meet_code",
    "race_grade",
    "distance_m",
    "registered_runner_count",
    "gate_no",
    "horse_sex",
    "horse_age",
    "carried_weight",
    "rating",
    "horse_prior_start_count",
    "horse_prior_finish_count",
    "horse_prior_finish_rate",
    "horse_prior_plc_hit_count",
    "horse_prior_plc_hit_rate",
    "horse_prior_avg_finish_rank",
    "horse_days_since_last_start",
    "horse_history_available",
    "horse_recent5_start_count",
    "horse_recent5_finish_rate",
    "horse_recent5_plc_hit_rate",
    "horse_recent5_avg_finish_rank",
    "horse_same_distance_start_count",
    "horse_same_distance_plc_hit_rate",
    "jockey_prior_start_count",
    "jockey_prior_plc_hit_rate",
    "jockey_history_available",
    "trainer_prior_start_count",
    "trainer_prior_plc_hit_rate",
    "trainer_history_available",
)


@dataclass(frozen=True)
class FeatureSnapshotOutcome:
    snapshot_version: str
    row_count: int
    race_count: int
    positive_count: int
    no_horse_history_count: int


def _require_completed_inputs(connection: DuckDBPyConnection) -> None:
    canonical_run = connection.execute(
        "SELECT status FROM canonical.transform_run WHERE transform_version = ?",
        [CANONICAL_TRANSFORM_VERSION],
    ).fetchone()
    if canonical_run is None or str(canonical_run[0]) != "COMPLETED":
        raise ValueError("Completed Canonical input is required")

    star_run = connection.execute(
        "SELECT status FROM analytics.transform_run WHERE transform_version = ?",
        [STAR_TRANSFORM_VERSION],
    ).fetchone()
    if star_run is None or str(star_run[0]) != "COMPLETED":
        raise ValueError("Completed Star input is required")


def _audit_connection(connection: DuckDBPyConnection) -> list[str]:
    issues: list[str] = []
    run = connection.execute(
        """
        SELECT status, row_count, race_count, positive_count, no_horse_history_count
        FROM mart.feature_snapshot_run
        WHERE snapshot_version = ?
        """,
        [SNAPSHOT_VERSION],
    ).fetchone()
    if run is None:
        return ["MISSING_FEATURE_SNAPSHOT_RUN"]

    actual = connection.execute(
        """
        SELECT count(*), count(DISTINCT race_id),
               count(*) FILTER (WHERE place_hit),
               count(*) FILTER (WHERE NOT horse_history_available)
        FROM mart.feature_snapshot_place
        """
    ).fetchone()
    assert actual is not None
    if str(run[0]) != "COMPLETED" or tuple(map(int, run[1:])) != tuple(map(int, actual)):
        issues.append("FEATURE_SNAPSHOT_RUN_COUNT_MISMATCH")

    population = connection.execute(
        """
        SELECT
            (SELECT count(*)
             FROM canonical.runner_result rr
             JOIN analytics.fact_race r USING (race_id)
             WHERE r.is_market_eligible AND rr.is_valid_start),
            (SELECT count(*) FROM mart.feature_snapshot_place)
        """
    ).fetchone()
    assert population is not None
    if int(population[0]) != int(population[1]):
        issues.append("FEATURE_SNAPSHOT_POPULATION_MISMATCH")

    duplicate_keys = connection.execute(
        """
        SELECT count(*) - count(DISTINCT race_id || '|' || horse_id)
        FROM mart.feature_snapshot_place
        """
    ).fetchone()
    assert duplicate_keys is not None
    if int(duplicate_keys[0]):
        issues.append("DUPLICATE_FEATURE_SNAPSHOT_KEY")

    leakage = connection.execute(
        """
        SELECT count(*)
        FROM mart.feature_snapshot_place
        WHERE feature_as_of <> race_date
           OR source_max_event_date >= feature_as_of
        """
    ).fetchone()
    assert leakage is not None
    if int(leakage[0]):
        issues.append("FEATURE_SNAPSHOT_PIT_VIOLATION")

    source_mismatches = connection.execute(
        """
        SELECT count(*)
        FROM mart.feature_snapshot_place f
        JOIN canonical.runner_result rr
          ON rr.race_id = f.race_id AND rr.horse_id = f.horse_id
        JOIN staging.race_result s
          ON s.staging_row_id = rr.source_staging_row_id
        WHERE f.source_batch_id <> rr.source_batch_id
           OR f.policy_version <> rr.policy_version
           OR f.result_status <> rr.result_status
           OR f.is_valid_start <> rr.is_valid_start
           OR f.is_valid_finish <> rr.is_valid_finish
           OR f.rating IS DISTINCT FROM try_cast(s.rating AS INTEGER)
           OR f.place_hit <> EXISTS (
               SELECT 1
               FROM canonical.winning_payout wp
               WHERE wp.race_id = rr.race_id
                 AND wp.pool_code = '연식'
                 AND wp.selection_count = 1
                 AND wp.horse_no_1 = rr.gate_no
           )
        """
    ).fetchone()
    assert source_mismatches is not None
    if int(source_mismatches[0]):
        issues.append("FEATURE_SNAPSHOT_SOURCE_MISMATCH")

    status_mismatches = connection.execute(
        """
        SELECT
            count(*) FILTER (WHERE NOT is_valid_start OR result_status = 'DNS'),
            count(*) FILTER (WHERE result_status IN ('RACE_STOPPED', 'DISQUALIFIED'))
                - (SELECT count(*)
                   FROM canonical.runner_result rr
                   JOIN analytics.fact_race r USING (race_id)
                   WHERE r.is_market_eligible AND rr.is_valid_start
                     AND rr.result_status IN ('RACE_STOPPED', 'DISQUALIFIED'))
        FROM mart.feature_snapshot_place
        """
    ).fetchone()
    assert status_mismatches is not None
    if any(int(value) for value in status_mismatches):
        issues.append("FEATURE_SNAPSHOT_STATUS_POLICY_MISMATCH")

    invalid_features = connection.execute(
        """
        SELECT count(*)
        FROM mart.feature_snapshot_place
        WHERE horse_prior_finish_count > horse_prior_start_count
           OR horse_prior_plc_hit_count > horse_prior_start_count
           OR horse_recent5_start_count NOT BETWEEN 0 AND 5
           OR horse_same_distance_start_count > horse_prior_start_count
           OR horse_days_since_last_start <= 0
           OR horse_prior_finish_rate NOT BETWEEN 0 AND 1
           OR horse_prior_plc_hit_rate NOT BETWEEN 0 AND 1
           OR horse_recent5_finish_rate NOT BETWEEN 0 AND 1
           OR horse_recent5_plc_hit_rate NOT BETWEEN 0 AND 1
           OR horse_same_distance_plc_hit_rate NOT BETWEEN 0 AND 1
           OR jockey_prior_plc_hit_rate NOT BETWEEN 0 AND 1
           OR trainer_prior_plc_hit_rate NOT BETWEEN 0 AND 1
           OR (horse_prior_start_count = 0 AND (
                   horse_history_available
                OR horse_prior_finish_rate IS NOT NULL
                OR horse_prior_plc_hit_rate IS NOT NULL
                OR horse_days_since_last_start IS NOT NULL))
           OR (horse_prior_start_count > 0 AND (
                   NOT horse_history_available
                OR horse_prior_finish_rate IS NULL
                OR horse_prior_plc_hit_rate IS NULL
                OR horse_days_since_last_start IS NULL))
           OR (horse_prior_finish_count = 0 AND horse_prior_avg_finish_rank IS NOT NULL)
           OR (horse_prior_finish_count > 0 AND horse_prior_avg_finish_rank IS NULL)
           OR (horse_recent5_start_count = 0 AND (
                   horse_recent5_finish_rate IS NOT NULL
                OR horse_recent5_plc_hit_rate IS NOT NULL
                OR horse_recent5_avg_finish_rank IS NOT NULL))
           OR (horse_same_distance_start_count = 0
               AND horse_same_distance_plc_hit_rate IS NOT NULL)
           OR (jockey_id IS NULL AND (
                   jockey_prior_start_count IS NOT NULL
                OR jockey_prior_plc_hit_rate IS NOT NULL
                OR jockey_history_available))
           OR (trainer_id IS NULL AND (
                   trainer_prior_start_count IS NOT NULL
                OR trainer_prior_plc_hit_rate IS NOT NULL
                OR trainer_history_available))
           OR history_complete
           OR population_proxy <> 'POST_RACE_VALID_START_PROXY'
           OR population_exclusion_reason IS NOT NULL
        """
    ).fetchone()
    assert invalid_features is not None
    if int(invalid_features[0]):
        issues.append("INVALID_FEATURE_SNAPSHOT_VALUE")

    actual_features = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'mart'
              AND table_name = 'feature_snapshot_place'
            """
        ).fetchall()
    }
    if not set(MODEL_FEATURES).issubset(actual_features) or len(MODEL_FEATURES) != 29:
        issues.append("FEATURE_SNAPSHOT_SCHEMA_MISMATCH")
    return issues


def build_feature_snapshot(*, paths: ProjectPaths | None = None) -> FeatureSnapshotOutcome:
    project_paths = paths or ProjectPaths.from_root()
    initialize_database(paths=project_paths)
    script = (project_paths.sql / "transforms" / "003_build_feature_snapshot.sql").read_text(
        encoding="utf-8"
    )
    with connect_database(paths=project_paths) as connection:
        _require_completed_inputs(connection)
        connection.begin()
        try:
            connection.execute(
                """
                CREATE OR REPLACE TEMP TABLE feature_snapshot_context AS
                SELECT ?::VARCHAR AS snapshot_version,
                       ?::VARCHAR AS canonical_transform_version,
                       ?::VARCHAR AS star_transform_version,
                       ?::VARCHAR AS policy_version,
                       ?::TIMESTAMPTZ AS started_at
                """,
                [
                    SNAPSHOT_VERSION,
                    CANONICAL_TRANSFORM_VERSION,
                    STAR_TRANSFORM_VERSION,
                    POLICY_VERSION,
                    datetime.now(UTC),
                ],
            )
            connection.execute(script)
            issues = _audit_connection(connection)
            if issues:
                raise ValueError(f"Feature Snapshot audit failed: {issues}")
            row = connection.execute(
                """
                SELECT row_count, race_count, positive_count, no_horse_history_count
                FROM mart.feature_snapshot_run
                WHERE snapshot_version = ?
                """,
                [SNAPSHOT_VERSION],
            ).fetchone()
            assert row is not None
            counts = tuple(map(int, row))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return FeatureSnapshotOutcome(SNAPSHOT_VERSION, *counts)


def audit_feature_snapshot(*, paths: ProjectPaths | None = None) -> list[str]:
    project_paths = paths or ProjectPaths.from_root()
    with connect_database(paths=project_paths, read_only=True) as connection:
        return _audit_connection(connection)
