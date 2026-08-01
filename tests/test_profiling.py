from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from kra_analytics.database import connect_database, initialize_database
from kra_analytics.paths import ProjectPaths
from kra_analytics.profiling import build_raw_profile


def _write(path: Path, item: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"response": {"body": {"items": {"item": item}}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_build_raw_profile_reconciles_races(tmp_path) -> None:
    paths = ProjectPaths.from_root(tmp_path)
    (tmp_path / "sql" / "ddl").mkdir(parents=True)
    source_root = ProjectPaths.from_root().root
    for ddl in (source_root / "sql" / "ddl").glob("*.sql"):
        (tmp_path / "sql" / "ddl" / ddl.name).write_bytes(ddl.read_bytes())
    initialize_database(paths=paths)
    _write(
        paths.raw / "api4_3" / "race.json",
        {"rcDate": "20240101", "meet": "서울", "rcNo": "1", "hrNo": "H1"},
    )
    with connect_database(paths=paths) as connection:
        now = datetime.now(UTC)
        for batch_id, api_name, relative_path in (
            ("race-batch", "API4_3", "data/raw/api4_3/race.json"),
            ("sales-batch", "API179_1", "data/raw/api179_1/sales.json"),
        ):
            request_id = f"{batch_id}-request"
            connection.execute(
                """
                INSERT INTO raw.collection_batch (
                    batch_id, api_name, scope_json, started_at, completed_at,
                    status, request_count, success_count
                ) VALUES (?, ?, '{}', ?, ?, 'COMPLETED', 1, 1)
                """,
                [batch_id, api_name, now, now],
            )
            connection.execute(
                """
                INSERT INTO raw.api_request (
                    request_id, batch_id, api_name, request_year, meet_code,
                    page_no, page_size, requested_at, completed_at,
                    request_url_redacted, http_status, api_status, item_count
                ) VALUES (
                    ?, ?, ?, 2024, 1, 1, 1000, ?, ?,
                    'ServiceKey=REDACTED', 200, 'SUCCESS', 1
                )
                """,
                [request_id, batch_id, api_name, now, now],
            )
            connection.execute(
                """
                INSERT INTO raw.raw_file (
                    raw_file_id, request_id, relative_path, sha256,
                    size_bytes, written_at
                ) VALUES (?, ?, ?, 'hash', 1, ?)
                """,
                [f"{batch_id}-file", request_id, relative_path, now],
            )
    _write(
        paths.raw / "api179_1" / "sales.json",
        {
            "rcDate": "20240101",
            "meet": "1",
            "rcNo": "1",
            "pool": "단승",
            "amt": "1,000",
            "odds": "1-2.3",
        },
    )
    result = build_raw_profile(paths)
    assert result["shared_races"] == 1
    assert result["race_join_rate"] == 1
    assert result["sales_amount_invalid"] == 0
