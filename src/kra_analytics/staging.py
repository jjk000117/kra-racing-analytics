from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pandas as pd

from kra_analytics.database import connect_database, initialize_database
from kra_analytics.paths import ProjectPaths

TRANSFORM_VERSION = "staging_v1"
API_TABLES = {"API4_3": "staging.race_result", "API179_1": "staging.sales_dividend"}
RACE_FIELDS = (
    "age",
    "ageCond",
    "buG1fAccTime",
    "buG1fOrd",
    "buG2fAccTime",
    "buG2fOrd",
    "buG3fAccTime",
    "buG3fOrd",
    "buG4fAccTime",
    "buG4fOrd",
    "buG6fAccTime",
    "buG6fOrd",
    "buG8fAccTime",
    "buG8fOrd",
    "buS1fAccTime",
    "buS1fOrd",
    "buS1fTime",
    "bu_10_8fTime",
    "bu_1fGTime",
    "bu_2fGTime",
    "bu_3fGTime",
    "bu_4_2fTime",
    "bu_6_4fTime",
    "bu_8_6fTime",
    "budam",
    "buga1",
    "buga2",
    "buga3",
    "chaksun1",
    "chaksun2",
    "chaksun3",
    "chaksun4",
    "chaksun5",
    "chulNo",
    "diffUnit",
    "hrName",
    "hrNameEn",
    "hrNo",
    "ilsu",
    "jeG1fTime",
    "jeG3fTime",
    "jeS1fTime",
    "je_1cTime",
    "je_2cTime",
    "je_3cTime",
    "je_4cTime",
    "jkName",
    "jkNameEn",
    "jkNo",
    "meet",
    "name",
    "ord",
    "owName",
    "owNameEn",
    "owNo",
    "plcOdds",
    "prizeCond",
    "rank",
    "rating",
    "rcDate",
    "rcDay",
    "rcDist",
    "rcName",
    "rcNo",
    "rcTime",
    "seG1fAccTime",
    "seG3fAccTime",
    "seS1fAccTime",
    "se_1cAccTime",
    "se_2cAccTime",
    "se_3cAccTime",
    "se_4cAccTime",
    "sex",
    "sexCond",
    "sjG1fOrd",
    "sjG3fOrd",
    "sjS1fOrd",
    "sj_1cOrd",
    "sj_2cOrd",
    "sj_3cOrd",
    "sj_4cOrd",
    "trName",
    "trNameEn",
    "trNo",
    "track",
    "weather",
    "wgBudam",
    "wgHr",
    "winOdds",
)
SALES_FIELDS = ("amt", "meet", "odds", "pool", "rcDate", "rcNo")


@dataclass(frozen=True)
class StagingOutcome:
    batch_id: str
    api_name: str
    expected_rows: int
    staged_rows: int
    inserted_rows: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _items(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_bytes())
    value = document["response"]["body"]["items"]["item"]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return cast(list[dict[str, Any]], value)
    raise ValueError(f"Unexpected items.item shape: {path}")


def _integer(value: str | None) -> tuple[int | None, bool]:
    if value is None or not value.strip():
        return None, False
    try:
        return int(value), True
    except ValueError:
        return None, False


def _amount(value: str | None) -> tuple[Decimal | None, bool]:
    if value is None or not value.strip():
        return None, False
    try:
        parsed = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None, False
    if parsed < 0 or parsed != parsed.to_integral_value():
        return None, False
    return parsed, True


def _lineage_rows(paths: ProjectPaths, batch_id: str) -> tuple[str, list[tuple[Any, ...]]]:
    with connect_database(paths=paths, read_only=True) as connection:
        batch = connection.execute(
            "SELECT api_name, status FROM raw.collection_batch WHERE batch_id = ?", [batch_id]
        ).fetchone()
        if batch is None:
            raise ValueError(f"Unknown batch: {batch_id}")
        api_name, status = map(str, batch)
        if api_name not in API_TABLES:
            raise ValueError(f"Unsupported API: {api_name}")
        if status != "COMPLETED":
            raise ValueError(f"Batch is not completed successfully: {status}")
        rows = connection.execute(
            """
            SELECT r.request_id, f.raw_file_id, f.relative_path, f.sha256, r.item_count
            FROM raw.api_request r
            JOIN raw.raw_file f ON f.request_id = r.request_id
            WHERE r.batch_id = ? AND r.api_status = 'SUCCESS'
            ORDER BY r.request_year, r.meet_code, r.page_no, r.requested_at
            """,
            [batch_id],
        ).fetchall()
    return api_name, rows


def load_staging_batch(batch_id: str, *, paths: ProjectPaths | None = None) -> StagingOutcome:
    project_paths = paths or ProjectPaths.from_root()
    initialize_database(paths=project_paths)
    api_name, lineage = _lineage_rows(project_paths, batch_id)
    expected_rows = sum(int(row[4]) for row in lineage)
    table = API_TABLES[api_name]
    with connect_database(paths=project_paths, read_only=True) as connection:
        completed = connection.execute(
            """
            SELECT staged_rows
            FROM staging.load_run
            WHERE batch_id = ? AND transform_version = ?
              AND status = 'COMPLETED' AND expected_rows = staged_rows
            """,
            [batch_id, TRANSFORM_VERSION],
        ).fetchone()
        existing = connection.execute(
            f"SELECT count(*) FROM {table} WHERE batch_id = ?", [batch_id]
        ).fetchone()
    assert existing is not None
    if completed is not None and int(completed[0]) == expected_rows == int(existing[0]):
        return StagingOutcome(batch_id, api_name, expected_rows, expected_rows, 0)
    fields = RACE_FIELDS if api_name == "API4_3" else SALES_FIELDS
    loaded_at = utc_now()
    records: list[list[Any]] = []
    for request_id, raw_file_id, relative_path, raw_sha256, item_count in lineage:
        items = _items(project_paths.root / str(relative_path))
        if len(items) != int(item_count):
            raise ValueError(f"Manifest item count mismatch: {relative_path}")
        for row_number, item in enumerate(items, start=1):
            source_json = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            staging_id = sha256(f"{raw_file_id}:{row_number}".encode()).hexdigest()
            values = [_text(item.get(field)) for field in fields]
            derived: list[Any]
            if api_name == "API4_3":
                derived = list(_integer(_text(item.get("ord"))))
            else:
                derived = list(_amount(_text(item.get("amt"))))
            records.append(
                [
                    staging_id,
                    batch_id,
                    request_id,
                    raw_file_id,
                    raw_sha256,
                    row_number,
                    loaded_at,
                    TRANSFORM_VERSION,
                    source_json,
                    *values,
                    *derived,
                ]
            )

    derived_columns = (
        ("ord_numeric", "ord_parse_valid")
        if api_name == "API4_3"
        else ("amt_numeric", "amt_parse_valid")
    )
    columns = [
        "staging_row_id",
        "batch_id",
        "request_id",
        "raw_file_id",
        "raw_sha256",
        "source_row_number",
        "loaded_at",
        "transform_version",
        "source_item_json",
        *fields,
        *derived_columns,
    ]
    before = 0
    after = 0
    with connect_database(paths=project_paths) as connection:
        connection.begin()
        try:
            before_row = connection.execute(
                f"SELECT count(*) FROM {table} WHERE batch_id = ?", [batch_id]
            ).fetchone()
            assert before_row is not None
            before = int(before_row[0])
            connection.execute(
                """
                INSERT INTO staging.load_run
                    (batch_id, api_name, transform_version, started_at, status, expected_rows)
                VALUES (?, ?, ?, ?, 'RUNNING', ?)
                ON CONFLICT (batch_id, transform_version) DO UPDATE SET
                    started_at = excluded.started_at, completed_at = NULL,
                    status = 'RUNNING', expected_rows = excluded.expected_rows,
                    error_message = NULL
                """,
                [batch_id, api_name, TRANSFORM_VERSION, loaded_at, expected_rows],
            )
            frame = pd.DataFrame.from_records(records, columns=columns)
            connection.register("staging_input", frame)
            connection.execute(
                f"""
                INSERT INTO {table} ({", ".join(columns)})
                SELECT {", ".join(columns)} FROM staging_input
                ON CONFLICT DO NOTHING
                """
            )
            connection.unregister("staging_input")
            after_row = connection.execute(
                f"SELECT count(*) FROM {table} WHERE batch_id = ?", [batch_id]
            ).fetchone()
            assert after_row is not None
            after = int(after_row[0])
            if after != expected_rows:
                raise ValueError(
                    f"Staging row count mismatch: expected={expected_rows} actual={after}"
                )
            connection.execute(
                """
                UPDATE staging.load_run
                SET completed_at = ?, status = 'COMPLETED', staged_rows = ?, inserted_rows = ?
                WHERE batch_id = ? AND transform_version = ?
                """,
                [utc_now(), after, after - before, batch_id, TRANSFORM_VERSION],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return StagingOutcome(batch_id, api_name, expected_rows, after, after - before)


def audit_staging_batch(batch_id: str, *, paths: ProjectPaths | None = None) -> list[str]:
    project_paths = paths or ProjectPaths.from_root()
    api_name, _ = _lineage_rows(project_paths, batch_id)
    table = API_TABLES[api_name]
    issues: list[str] = []
    with connect_database(paths=project_paths, read_only=True) as connection:
        run = connection.execute(
            """
            SELECT status, expected_rows, staged_rows
            FROM staging.load_run
            WHERE batch_id = ? AND transform_version = ?
            """,
            [batch_id, TRANSFORM_VERSION],
        ).fetchone()
        if run is None:
            return [f"MISSING_LOAD_RUN:{batch_id}"]
        status, expected_rows, staged_rows = run
        if str(status) != "COMPLETED":
            issues.append("LOAD_RUN_NOT_COMPLETED")
        count_row = connection.execute(
            f"SELECT count(*) FROM {table} WHERE batch_id = ?", [batch_id]
        ).fetchone()
        assert count_row is not None
        table_count = int(count_row[0])
        if table_count != int(expected_rows) or table_count != int(staged_rows):
            issues.append("STAGING_ROW_COUNT_MISMATCH")
        orphan_row = connection.execute(
            f"""
            SELECT count(*)
            FROM {table} s
            LEFT JOIN raw.raw_file f ON f.raw_file_id = s.raw_file_id
            LEFT JOIN raw.api_request r ON r.request_id = s.request_id
            WHERE s.batch_id = ?
              AND (f.raw_file_id IS NULL OR r.request_id IS NULL
                   OR r.batch_id <> s.batch_id OR f.sha256 <> s.raw_sha256)
            """,
            [batch_id],
        ).fetchone()
        assert orphan_row is not None
        if int(orphan_row[0]):
            issues.append("BROKEN_RAW_LINEAGE")
        sequence_row = connection.execute(
            f"""
            WITH staged AS (
                SELECT raw_file_id, count(*) AS rows_loaded,
                    min(source_row_number) AS first_row,
                    max(source_row_number) AS last_row
                FROM {table} WHERE batch_id = ? GROUP BY raw_file_id
            )
            SELECT count(*)
            FROM staged s
            JOIN raw.raw_file f ON f.raw_file_id = s.raw_file_id
            JOIN raw.api_request r ON r.request_id = f.request_id
            WHERE s.rows_loaded <> r.item_count OR s.first_row <> 1
               OR s.last_row <> r.item_count
            """,
            [batch_id],
        ).fetchone()
        assert sequence_row is not None
        if int(sequence_row[0]):
            issues.append("SOURCE_ROW_SEQUENCE_MISMATCH")
        parse_sql = (
            """
            SELECT count(*) FROM staging.race_result
            WHERE batch_id = ?
              AND ord_parse_valid <> (try_cast(ord AS INTEGER) IS NOT NULL)
            """
            if api_name == "API4_3"
            else """
            SELECT count(*) FROM staging.sales_dividend
            WHERE batch_id = ? AND amt_parse_valid <> (
                try_cast(replace(amt, ',', '') AS DECIMAL(20, 0)) IS NOT NULL
            )
            """
        )
        parse_row = connection.execute(parse_sql, [batch_id]).fetchone()
        assert parse_row is not None
        if int(parse_row[0]):
            issues.append("PARSE_FLAG_MISMATCH")
    return issues
