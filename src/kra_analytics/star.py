from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from kra_analytics.canonical import TRANSFORM_VERSION as CANONICAL_TRANSFORM_VERSION
from kra_analytics.canonical import audit_canonical
from kra_analytics.database import connect_database, initialize_database
from kra_analytics.paths import ProjectPaths

TRANSFORM_VERSION = "star_v1"


@dataclass(frozen=True)
class StarOutcome:
    transform_version: str
    race_count: int
    sales_count: int
    eligible_race_count: int
    market_sales_count: int


def build_star(*, paths: ProjectPaths | None = None) -> StarOutcome:
    project_paths = paths or ProjectPaths.from_root()
    initialize_database(paths=project_paths)
    canonical_issues = audit_canonical(paths=project_paths)
    if canonical_issues:
        raise ValueError(f"Canonical audit failed: {canonical_issues}")

    script = (project_paths.sql / "transforms" / "002_build_star_schema.sql").read_text(
        encoding="utf-8"
    )
    with connect_database(paths=project_paths) as connection:
        connection.begin()
        try:
            connection.execute(
                """
                CREATE OR REPLACE TEMP TABLE star_context AS
                SELECT ?::VARCHAR AS transform_version,
                       ?::VARCHAR AS canonical_transform_version,
                       ?::TIMESTAMPTZ AS started_at
                """,
                [TRANSFORM_VERSION, CANONICAL_TRANSFORM_VERSION, datetime.now(UTC)],
            )
            connection.execute(script)
            row = connection.execute(
                """
                SELECT race_count, sales_count, eligible_race_count, market_sales_count
                FROM analytics.transform_run WHERE transform_version = ?
                """,
                [TRANSFORM_VERSION],
            ).fetchone()
            assert row is not None
            counts = tuple(map(int, row))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return StarOutcome(TRANSFORM_VERSION, *counts)


def audit_star(*, paths: ProjectPaths | None = None) -> list[str]:
    project_paths = paths or ProjectPaths.from_root()
    issues: list[str] = []
    with connect_database(paths=project_paths, read_only=True) as connection:
        run = connection.execute(
            """
            SELECT status, race_count, sales_count, eligible_race_count, market_sales_count
            FROM analytics.transform_run WHERE transform_version = ?
            """,
            [TRANSFORM_VERSION],
        ).fetchone()
        if run is None:
            return ["MISSING_STAR_RUN"]

        actual = connection.execute(
            """
            SELECT (SELECT count(*) FROM analytics.fact_race),
                   (SELECT count(*) FROM analytics.fact_sales),
                   (SELECT count(*) FROM analytics.mart_complete_race),
                   (SELECT count(*) FROM analytics.mart_market_sales)
            """
        ).fetchone()
        assert actual is not None
        if str(run[0]) != "COMPLETED" or tuple(map(int, run[1:])) != tuple(map(int, actual)):
            issues.append("STAR_RUN_COUNT_MISMATCH")

        source_counts = connection.execute(
            """
            SELECT (SELECT count(*) FROM canonical.race),
                   (SELECT count(*) FROM analytics.fact_race),
                   (SELECT count(*) FROM canonical.sales_dividend),
                   (SELECT count(*) FROM analytics.fact_sales)
            """
        ).fetchone()
        assert source_counts is not None
        if int(source_counts[0]) != int(source_counts[1]):
            issues.append("RACE_COUNT_MISMATCH")
        if int(source_counts[2]) != int(source_counts[3]):
            issues.append("SALES_COUNT_MISMATCH")

        mapping_gaps = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM canonical.race r
                 LEFT JOIN analytics.dim_race_grade g ON g.race_grade_raw = r.race_grade
                 WHERE g.grade_key IS NULL),
                (SELECT count(*) FROM canonical.sales_dividend s
                 LEFT JOIN analytics.dim_pool p ON p.pool_name_raw = s.pool_code
                 WHERE p.pool_key IS NULL)
            """
        ).fetchone()
        assert mapping_gaps is not None
        if int(mapping_gaps[0]):
            issues.append("UNMAPPED_RACE_GRADE")
        if int(mapping_gaps[1]):
            issues.append("UNMAPPED_POOL")

        broken_keys = connection.execute(
            """
            SELECT
                (SELECT count(*)
                 FROM analytics.fact_race f
                 LEFT JOIN canonical.race c ON c.race_id = f.race_id
                 LEFT JOIN analytics.dim_date d ON d.date_key = f.date_key
                 LEFT JOIN analytics.dim_meet m ON m.meet_key = f.meet_key
                 LEFT JOIN analytics.dim_race_grade g ON g.grade_key = f.grade_key
                 WHERE c.race_id IS NULL OR d.date_key IS NULL OR m.meet_key IS NULL
                    OR g.grade_key IS NULL),
                (SELECT count(*)
                 FROM analytics.fact_sales s
                 LEFT JOIN canonical.sales_dividend c ON c.sales_id = s.sales_id
                 LEFT JOIN analytics.dim_date d ON d.date_key = s.date_key
                 LEFT JOIN analytics.dim_meet m ON m.meet_key = s.meet_key
                 LEFT JOIN analytics.dim_race_grade g ON g.grade_key = s.grade_key
                 LEFT JOIN analytics.dim_pool p ON p.pool_key = s.pool_key
                 WHERE c.sales_id IS NULL OR d.date_key IS NULL OR m.meet_key IS NULL
                    OR g.grade_key IS NULL OR p.pool_key IS NULL)
            """
        ).fetchone()
        assert broken_keys is not None
        if any(int(value) for value in broken_keys):
            issues.append("BROKEN_STAR_LINEAGE_OR_DIMENSION_KEY")

        eligibility_errors = connection.execute(
            """
            SELECT count(*) FROM analytics.fact_race
            WHERE is_market_eligible <> (race_status = 'COMPLETED' AND has_all_official_pools)
               OR has_all_official_pools <> (pool_count = 7)
            """
        ).fetchone()
        assert eligibility_errors is not None
        if int(eligibility_errors[0]):
            issues.append("INVALID_MARKET_ELIGIBILITY")

        market_pool_errors = connection.execute(
            """
            SELECT count(*) FROM (
                SELECT race_id, count(*) AS row_count, count(DISTINCT pool_key) AS pool_count
                FROM analytics.mart_market_sales
                GROUP BY race_id
                HAVING row_count <> 7 OR pool_count <> 7
            )
            """
        ).fetchone()
        assert market_pool_errors is not None
        if int(market_pool_errors[0]):
            issues.append("INCOMPLETE_MARKET_POOL_SET")

        sales_totals = connection.execute(
            """
            SELECT (SELECT sum(sales_amount) FROM canonical.sales_dividend),
                   (SELECT sum(sales_amount) FROM analytics.fact_sales),
                   (SELECT sum(c.sales_amount)
                    FROM canonical.sales_dividend c
                    JOIN analytics.fact_race r ON r.race_id = c.race_id
                    WHERE r.is_market_eligible),
                   (SELECT sum(sales_amount) FROM analytics.mart_market_sales)
            """
        ).fetchone()
        assert sales_totals is not None
        if sales_totals[0] != sales_totals[1]:
            issues.append("SALES_TOTAL_MISMATCH")
        if sales_totals[2] != sales_totals[3]:
            issues.append("MARKET_SALES_TOTAL_MISMATCH")

        duplicate_keys = connection.execute(
            """
            SELECT
                (SELECT count(*) - count(DISTINCT race_id) FROM analytics.fact_race),
                (SELECT count(*) - count(DISTINCT sales_id) FROM analytics.fact_sales),
                (SELECT count(*) - count(DISTINCT race_id || '|' || pool_key)
                 FROM analytics.fact_sales)
            """
        ).fetchone()
        assert duplicate_keys is not None
        if any(int(value) for value in duplicate_keys):
            issues.append("DUPLICATE_STAR_KEY")
    return issues
