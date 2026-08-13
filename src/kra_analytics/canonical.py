from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd
from duckdb import DuckDBPyConnection

from kra_analytics.database import connect_database, initialize_database
from kra_analytics.odds_profiling import ORDERED_POOLS, profile_confirmed_odds
from kra_analytics.paths import ProjectPaths
from kra_analytics.staging import audit_staging_batch

TRANSFORM_VERSION = "canonical_v2"
POLICY_VERSION = "race_status_v1"
PAYOUT_PARSER_VERSION = "winning_payout_v1"


@dataclass(frozen=True)
class CanonicalOutcome:
    transform_version: str
    race_count: int
    runner_count: int
    sales_count: int
    winning_payout_count: int
    issue_count: int


def _build_winning_payouts(connection: DuckDBPyConnection) -> int:
    source = connection.execute(
        """
        SELECT sales_id, race_id, pool_code, confirmed_odds_raw,
               source_staging_row_id, source_batch_id
        FROM canonical.sales_dividend
        ORDER BY sales_id
        """
    ).df()
    parsed, parse_issues = profile_confirmed_odds(source)

    if not parse_issues.empty:
        issue_records = parse_issues.merge(
            source[["sales_id", "source_staging_row_id"]], on="sales_id", how="left"
        )
        issue_records["transform_version"] = TRANSFORM_VERSION
        issue_records["policy_version"] = POLICY_VERSION
        connection.register("winning_payout_parse_issues", issue_records)
        connection.execute(
            """
            INSERT INTO quality.data_issue
            SELECT md5('INVALID_WINNING_PAYOUT|' || sales_id),
                   'INVALID_WINNING_PAYOUT', 'ERROR', 'canonical.sales_dividend',
                   source_staging_row_id, sales_id, confirmed_odds_raw,
                   issue, now(), transform_version, policy_version
            FROM winning_payout_parse_issues
            """
        )
        connection.unregister("winning_payout_parse_issues")

    if parsed.empty:
        return 0

    records = parsed.merge(
        source[
            [
                "sales_id",
                "confirmed_odds_raw",
                "source_staging_row_id",
                "source_batch_id",
            ]
        ],
        on="sales_id",
        how="left",
        validate="many_to_one",
    )
    canonical_numbers = records["horse_numbers_canonical"]
    records["selection_count"] = canonical_numbers.map(len)
    records["horse_no_1"] = canonical_numbers.map(lambda values: values[0])
    records["horse_no_2"] = canonical_numbers.map(
        lambda values: values[1] if len(values) >= 2 else pd.NA
    )
    records["horse_no_3"] = canonical_numbers.map(
        lambda values: values[2] if len(values) >= 3 else pd.NA
    )
    records["combination_key"] = canonical_numbers.map(
        lambda values: "-".join(map(str, values))
    )
    records["order_matters"] = records["pool_code"].isin(ORDERED_POOLS)
    records["parser_version"] = PAYOUT_PARSER_VERSION
    connection.register("winning_payout_records", records)
    connection.execute(
        """
        INSERT INTO canonical.winning_payout
        SELECT md5(sales_id || '|' || source_order::VARCHAR),
               sales_id, race_id, pool_code, source_order, selection_count,
               horse_no_1, horse_no_2, horse_no_3, combination_key,
               order_matters, confirmed_odds, confirmed_odds_raw, 'PARSED',
               parser_version, source_staging_row_id, source_batch_id, now()
        FROM winning_payout_records
        """
    )
    connection.unregister("winning_payout_records")
    return len(records)


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
    *,
    race_batch_id: str | None = None,
    sales_batch_id: str | None = None,
    race_batch_ids: Sequence[str] | None = None,
    sales_batch_ids: Sequence[str] | None = None,
    paths: ProjectPaths | None = None,
) -> CanonicalOutcome:
    project_paths = paths or ProjectPaths.from_root()
    initialize_database(paths=project_paths)
    if race_batch_id is not None and race_batch_ids is not None:
        raise ValueError("Use race_batch_id or race_batch_ids, not both")
    if sales_batch_id is not None and sales_batch_ids is not None:
        raise ValueError("Use sales_batch_id or sales_batch_ids, not both")
    race_scope = tuple(race_batch_ids or (() if race_batch_id is None else (race_batch_id,)))
    sales_scope = tuple(sales_batch_ids or (() if sales_batch_id is None else (sales_batch_id,)))
    if not race_scope or not sales_scope:
        raise ValueError("At least one race and sales batch is required")
    if len(set(race_scope)) != len(race_scope) or len(set(sales_scope)) != len(sales_scope):
        raise ValueError("Duplicate batch id in canonical scope")
    for batch_id in race_scope:
        _validate_batch(project_paths, batch_id, "API4_3")
    for batch_id in sales_scope:
        _validate_batch(project_paths, batch_id, "API179_1")
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
                    json.dumps(race_scope),
                    json.dumps(sales_scope),
                    POLICY_VERSION,
                    datetime.now(UTC),
                ],
            )
            connection.execute(
                "CREATE OR REPLACE TEMP TABLE canonical_race_batch_scope "
                "(batch_id VARCHAR PRIMARY KEY)"
            )
            connection.executemany(
                "INSERT INTO canonical_race_batch_scope VALUES (?)",
                [(batch_id,) for batch_id in race_scope],
            )
            connection.execute(
                "CREATE OR REPLACE TEMP TABLE canonical_sales_batch_scope "
                "(batch_id VARCHAR PRIMARY KEY)"
            )
            connection.executemany(
                "INSERT INTO canonical_sales_batch_scope VALUES (?)",
                [(batch_id,) for batch_id in sales_scope],
            )
            connection.execute(script)
            payout_count = _build_winning_payouts(connection)
            connection.execute(
                """
                UPDATE canonical.transform_run
                SET winning_payout_count = ?,
                    issue_count = (SELECT count(*) FROM quality.data_issue)
                WHERE transform_version = ?
                """,
                [payout_count, TRANSFORM_VERSION],
            )
            row = connection.execute(
                """
                SELECT race_count, runner_count, sales_count,
                       winning_payout_count, issue_count
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
            SELECT status, race_count, runner_count, sales_count,
                   winning_payout_count, issue_count
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
                   (SELECT count(*) FROM canonical.winning_payout),
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
        payout_integrity = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM canonical.sales_dividend s
                 LEFT JOIN canonical.winning_payout p ON p.sales_id = s.sales_id
                 WHERE p.sales_id IS NULL),
                (SELECT count(*) FROM canonical.winning_payout p
                 LEFT JOIN canonical.sales_dividend s ON s.sales_id = p.sales_id
                 LEFT JOIN canonical.race r ON r.race_id = p.race_id
                 LEFT JOIN staging.sales_dividend st
                   ON st.staging_row_id = p.source_staging_row_id
                 WHERE s.sales_id IS NULL OR r.race_id IS NULL
                    OR st.staging_row_id IS NULL
                    OR p.race_id <> s.race_id
                    OR p.pool_code <> s.pool_code
                    OR p.confirmed_odds_raw <> s.confirmed_odds_raw),
                (SELECT count(*) FROM canonical.winning_payout
                 WHERE parse_status <> 'PARSED'
                    OR parser_version <> ?
                    OR confirmed_odds <= 0
                    OR combination_no < 1
                    OR selection_count NOT BETWEEN 1 AND 3
                    OR horse_no_1 NOT BETWEEN 1 AND 16
                    OR (selection_count >= 2 AND horse_no_2 NOT BETWEEN 1 AND 16)
                    OR (selection_count = 3 AND horse_no_3 NOT BETWEEN 1 AND 16)
                    OR (selection_count = 1 AND (horse_no_2 IS NOT NULL
                                                OR horse_no_3 IS NOT NULL))
                    OR (selection_count = 2 AND (horse_no_2 IS NULL
                                                OR horse_no_3 IS NOT NULL))
                    OR (selection_count = 3 AND horse_no_3 IS NULL))
            """,
            [PAYOUT_PARSER_VERSION],
        ).fetchone()
        assert payout_integrity is not None
        if int(payout_integrity[0]):
            issues.append("SALES_WITHOUT_WINNING_PAYOUT")
        if int(payout_integrity[1]):
            issues.append("BROKEN_WINNING_PAYOUT_LINEAGE")
        if int(payout_integrity[2]):
            issues.append("INVALID_WINNING_PAYOUT")
        missing_horses = connection.execute(
            """
            SELECT count(*) FROM (
                SELECT race_id, horse_no_1 AS horse_no
                FROM canonical.winning_payout
                UNION ALL
                SELECT race_id, horse_no_2
                FROM canonical.winning_payout WHERE horse_no_2 IS NOT NULL
                UNION ALL
                SELECT race_id, horse_no_3
                FROM canonical.winning_payout WHERE horse_no_3 IS NOT NULL
            ) p
            LEFT JOIN canonical.runner_result r
              ON r.race_id = p.race_id AND r.gate_no = p.horse_no
            WHERE r.runner_result_id IS NULL OR NOT r.is_valid_start
            """
        ).fetchone()
        assert missing_horses is not None
        if int(missing_horses[0]):
            issues.append("WINNING_PAYOUT_HORSE_NOT_VALID_STARTER")
        result_rule_mismatches = connection.execute(
            """
            WITH race_ranks AS (
                SELECT race_id,
                       count(*) FILTER (WHERE official_finish_rank = 1) AS rank_1,
                       count(*) FILTER (WHERE official_finish_rank = 2) AS rank_2,
                       count(*) FILTER (WHERE official_finish_rank = 3) AS rank_3
                FROM canonical.runner_result
                GROUP BY race_id
            ), payout_counts AS (
                SELECT race_id, pool_code, count(*) AS actual_count
                FROM canonical.winning_payout
                GROUP BY race_id, pool_code
            ), expected AS (
                SELECT p.*, r.rank_1, r.rank_2, r.rank_3,
                       CASE p.pool_code
                           WHEN '단식' THEN r.rank_1
                           WHEN '연식' THEN NULL
                           WHEN '복식' THEN CASE WHEN r.rank_2 = 0
                               THEN r.rank_1 * (r.rank_1 - 1) / 2
                               ELSE r.rank_1 * r.rank_2 END
                           WHEN '쌍식' THEN CASE WHEN r.rank_2 = 0
                               THEN r.rank_1 * (r.rank_1 - 1)
                               ELSE r.rank_1 * r.rank_2 END
                           WHEN '복연' THEN (r.rank_1 + r.rank_2 + r.rank_3) *
                               (r.rank_1 + r.rank_2 + r.rank_3 - 1) / 2
                           WHEN '삼복' THEN CASE
                               WHEN r.rank_2 = 0
                                   THEN r.rank_1 * (r.rank_1 - 1) / 2 * r.rank_3
                               WHEN r.rank_3 = 0
                                   THEN r.rank_1 * r.rank_2 * (r.rank_2 - 1) / 2
                               ELSE r.rank_1 * r.rank_2 * r.rank_3 END
                           WHEN '삼쌍' THEN CASE
                               WHEN r.rank_2 = 0
                                   THEN r.rank_1 * (r.rank_1 - 1) * r.rank_3
                               WHEN r.rank_3 = 0
                                   THEN r.rank_1 * r.rank_2 * (r.rank_2 - 1)
                               ELSE r.rank_1 * r.rank_2 * r.rank_3 END
                       END AS expected_count
                FROM payout_counts p
                JOIN race_ranks r USING (race_id)
            )
            SELECT count(*) FROM expected
            WHERE (pool_code = '연식' AND actual_count NOT IN (
                       rank_1 + rank_2,
                       rank_1 + rank_2 + rank_3
                   ))
               OR (pool_code <> '연식' AND actual_count <> expected_count)
            """
        ).fetchone()
        assert result_rule_mismatches is not None
        if int(result_rule_mismatches[0]):
            issues.append("WINNING_PAYOUT_RESULT_RULE_MISMATCH")
        error_count = connection.execute(
            "SELECT count(*) FROM quality.data_issue WHERE severity = 'ERROR'"
        ).fetchone()
        assert error_count is not None
        if int(error_count[0]):
            issues.append("QUALITY_ERRORS_PRESENT")
    return issues
