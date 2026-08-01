from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from kra_analytics.database import connect_database, initialize_database
from kra_analytics.paths import ProjectPaths
from kra_analytics.staging import audit_staging_batch

TRANSFORM_VERSION = "canonical_v1"
POLICY_VERSION = "race_status_v1"


@dataclass(frozen=True)
class CanonicalOutcome:
    transform_version: str
    race_count: int
    runner_count: int
    sales_count: int
    issue_count: int


def _validate_batch(paths: ProjectPaths, batch_id: str, expected_api: str) -> None:
    with connect_database(paths=paths, read_only=True) as connection:
        row = connection.execute(
            "SELECT api_name, status FROM raw.collection_batch WHERE batch_id = ?", [batch_id]
        ).fetchone()
    if row is None or str(row[0]) != expected_api or str(row[1]) != "COMPLETED":
        raise ValueError(f"Invalid {expected_api} batch: {batch_id}")
    issues = audit_staging_batch(batch_id, paths=paths)
    if issues:
        raise ValueError(f"Staging audit failed for {batch_id}: {issues}")


def build_canonical(
    *, race_batch_id: str, sales_batch_id: str, paths: ProjectPaths | None = None
) -> CanonicalOutcome:
    project_paths = paths or ProjectPaths.from_root()
    initialize_database(paths=project_paths)
    _validate_batch(project_paths, race_batch_id, "API4_3")
    _validate_batch(project_paths, sales_batch_id, "API179_1")
    script = (project_paths.sql / "transforms" / "001_build_canonical.sql").read_text(
        encoding="utf-8"
    )
    with connect_database(paths=project_paths) as connection:
        connection.begin()
        try:
            connection.execute(
                """
                CREATE OR REPLACE TEMP TABLE canonical_context AS
                SELECT ?::VARCHAR AS transform_version,
                       ?::VARCHAR AS race_batch_id,
                       ?::VARCHAR AS sales_batch_id,
                       ?::VARCHAR AS policy_version,
                       ?::TIMESTAMPTZ AS started_at
                """,
                [
                    TRANSFORM_VERSION,
                    race_batch_id,
                    sales_batch_id,
                    POLICY_VERSION,
                    datetime.now(UTC),
                ],
            )
            connection.execute(script)
            row = connection.execute(
                """
                SELECT race_count, runner_count, sales_count, issue_count
                FROM canonical.transform_run WHERE transform_version = ?
                """,
                [TRANSFORM_VERSION],
            ).fetchone()
            assert row is not None
            counts = tuple(map(int, row))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return CanonicalOutcome(TRANSFORM_VERSION, *counts)


def audit_canonical(*, paths: ProjectPaths | None = None) -> list[str]:
    project_paths = paths or ProjectPaths.from_root()
    issues: list[str] = []
    with connect_database(paths=project_paths, read_only=True) as connection:
        run = connection.execute(
            """
            SELECT status, race_count, runner_count, sales_count, issue_count
            FROM canonical.transform_run WHERE transform_version = ?
            """,
            [TRANSFORM_VERSION],
        ).fetchone()
        if run is None:
            return ["MISSING_CANONICAL_RUN"]
        actual = connection.execute(
            """
            SELECT (SELECT count(*) FROM canonical.race),
                   (SELECT count(*) FROM canonical.runner_result),
                   (SELECT count(*) FROM canonical.sales_dividend),
                   (SELECT count(*) FROM quality.data_issue)
            """
        ).fetchone()
        assert actual is not None
        if str(run[0]) != "COMPLETED" or tuple(map(int, run[1:])) != tuple(map(int, actual)):
            issues.append("CANONICAL_RUN_COUNT_MISMATCH")
        invalid_finish = connection.execute(
            """
            SELECT count(*) FROM canonical.runner_result
            WHERE official_finish_rank IS NOT NULL
              AND official_finish_rank NOT BETWEEN 1 AND 16
            """
        ).fetchone()
        assert invalid_finish is not None
        if int(invalid_finish[0]):
            issues.append("INVALID_OFFICIAL_FINISH")
        broken_runner = connection.execute(
            """
            SELECT count(*) FROM canonical.runner_result rr
            LEFT JOIN canonical.race r ON r.race_id = rr.race_id
            LEFT JOIN staging.race_result s
              ON s.staging_row_id = rr.source_staging_row_id
            WHERE r.race_id IS NULL OR s.staging_row_id IS NULL
            """
        ).fetchone()
        broken_sales = connection.execute(
            """
            SELECT count(*) FROM canonical.sales_dividend sd
            LEFT JOIN canonical.race r ON r.race_id = sd.race_id
            LEFT JOIN staging.sales_dividend s
              ON s.staging_row_id = sd.source_staging_row_id
            WHERE r.race_id IS NULL OR s.staging_row_id IS NULL
            """
        ).fetchone()
        assert broken_runner is not None and broken_sales is not None
        if int(broken_runner[0]) or int(broken_sales[0]):
            issues.append("BROKEN_CANONICAL_LINEAGE")
        error_count = connection.execute(
            "SELECT count(*) FROM quality.data_issue WHERE severity = 'ERROR'"
        ).fetchone()
        assert error_count is not None
        if int(error_count[0]):
            issues.append("QUALITY_ERRORS_PRESENT")
    return issues
