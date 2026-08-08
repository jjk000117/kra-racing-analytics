from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "warehouse" / "kra.duckdb"
BASE_URL = "https://apis.data.go.kr/B551015/API26_2/entrySheet_2"
API_NAME = "API26_2_PIT_VALIDATION"
PAGE_SIZE = 1000

CUMULATIVE_FIELDS = {
    "starts_lifetime": "rcCntT",
    "firsts_lifetime": "ord1CntT",
    "seconds_lifetime": "ord2CntT",
    "thirds_lifetime": "ord3CntT",
    "starts_recent_year": "rcCntY",
    "firsts_recent_year": "ord1CntY",
    "seconds_recent_year": "ord2CntY",
    "thirds_recent_year": "ord3CntY",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_items(document: dict[str, Any]) -> list[dict[str, Any]]:
    response = document.get("response", {})
    header = response.get("header", {})
    if str(header.get("resultCode")) != "00":
        raise RuntimeError(f"API error: {header.get('resultMsg', 'unknown error')}")
    raw = response.get("body", {}).get("items", {}).get("item", [])
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list) and all(isinstance(item, dict) for item in raw):
        return raw
    return []


def as_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def as_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def select_sample_horses(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        WITH candidates AS (
            SELECT r.meet_code, rr.horse_id, min(r.race_date) AS first_date,
                   max(r.race_date) AS last_date, count(*) AS start_count,
                   count(DISTINCT year(r.race_date)) AS year_count
            FROM canonical.runner_result rr
            JOIN canonical.race r USING (race_id)
            WHERE r.race_date BETWEEN DATE '2024-02-01' AND DATE '2025-12-31'
              AND rr.is_valid_start
            GROUP BY r.meet_code, rr.horse_id
            HAVING count(*) >= 8
               AND count_if(year(r.race_date) = 2024) >= 2
               AND count_if(year(r.race_date) = 2025) >= 2
        ), ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY meet_code ORDER BY first_date, start_count DESC, horse_id
            ) AS rn
            FROM candidates
        )
        SELECT meet_code, horse_id, first_date, last_date, start_count
        FROM ranked WHERE rn = 1 ORDER BY meet_code
        """
    ).fetchall()
    columns = ["meet_code", "horse_id", "first_date", "last_date", "start_count"]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def select_sample_dates(
    connection: duckdb.DuckDBPyConnection, horse_id: str
) -> list[date]:
    dates = [
        row[0]
        for row in connection.execute(
            """
            SELECT r.race_date
            FROM canonical.runner_result rr
            JOIN canonical.race r USING (race_id)
            WHERE rr.horse_id = ? AND rr.is_valid_start
              AND r.race_date BETWEEN DATE '2024-01-01' AND DATE '2025-12-31'
            ORDER BY r.race_date
            """,
            [horse_id],
        ).fetchall()
    ]
    indexes = sorted({0, len(dates) // 3, (2 * len(dates)) // 3, len(dates) - 1})
    return [dates[index] for index in indexes]


def history_stats(
    connection: duckdb.DuckDBPyConnection, horse_id: str, race_date: date
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
            count_if(rr.is_valid_start AND r.race_date < ?) AS prior_starts,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 1
                     AND r.race_date < ?) AS prior_firsts,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 2
                     AND r.race_date < ?) AS prior_seconds,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 3
                     AND r.race_date < ?) AS prior_thirds,
            count_if(rr.is_valid_start
                     AND r.race_date >= ? - INTERVAL 1 YEAR
                     AND r.race_date < ?) AS prior_year_starts,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 1
                     AND r.race_date >= ? - INTERVAL 1 YEAR
                     AND r.race_date < ?) AS prior_year_firsts,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 2
                     AND r.race_date >= ? - INTERVAL 1 YEAR
                     AND r.race_date < ?) AS prior_year_seconds,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 3
                     AND r.race_date >= ? - INTERVAL 1 YEAR
                     AND r.race_date < ?) AS prior_year_thirds,
            count_if(rr.is_valid_start AND r.race_date <= ?) AS inclusive_starts,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 1
                     AND r.race_date <= ?) AS inclusive_firsts,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 2
                     AND r.race_date <= ?) AS inclusive_seconds,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 3
                     AND r.race_date <= ?) AS inclusive_thirds,
            count_if(rr.is_valid_start) AS all_observed_starts,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 1) AS all_observed_firsts,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 2) AS all_observed_seconds,
            count_if(rr.is_valid_finish AND rr.official_finish_rank = 3) AS all_observed_thirds
        FROM canonical.runner_result rr
        JOIN canonical.race r USING (race_id)
        WHERE rr.horse_id = ?
        """,
        [
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            race_date,
            horse_id,
        ],
    ).fetchone()
    assert row is not None
    names = [
        "prior_starts",
        "prior_firsts",
        "prior_seconds",
        "prior_thirds",
        "prior_year_starts",
        "prior_year_firsts",
        "prior_year_seconds",
        "prior_year_thirds",
        "inclusive_starts",
        "inclusive_firsts",
        "inclusive_seconds",
        "inclusive_thirds",
        "all_observed_starts",
        "all_observed_firsts",
        "all_observed_seconds",
        "all_observed_thirds",
    ]
    return dict(zip(names, row, strict=True))


def current_race_values(
    connection: duckdb.DuckDBPyConnection, horse_id: str, race_date: date
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT rr.race_id, rr.gate_no, rr.carried_weight, r.runner_count,
               try_cast(s.rating AS INTEGER) AS rating
        FROM canonical.runner_result rr
        JOIN canonical.race r USING (race_id)
        JOIN staging.race_result s
          ON s.staging_row_id = rr.source_staging_row_id
        WHERE rr.horse_id = ? AND r.race_date = ?
        """,
        [horse_id, race_date],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Current race row not found: {horse_id} {race_date}")
    return dict(
        zip(
            ["race_id", "gate_no", "carried_weight", "runner_count", "rating"],
            row,
            strict=True,
        )
    )


def record_batch(
    connection: duckdb.DuckDBPyConnection,
    batch_id: str,
    scope: dict[str, Any],
    started_at: datetime,
) -> None:
    connection.execute(
        """
        INSERT INTO raw.collection_batch
            (batch_id, api_name, scope_json, started_at, status)
        VALUES (?, ?, ?, ?, 'RUNNING')
        """,
        [batch_id, API_NAME, json.dumps(scope, ensure_ascii=False, default=str), started_at],
    )


def record_request(
    connection: duckdb.DuckDBPyConnection,
    *,
    batch_id: str,
    request_id: str,
    meet: int,
    race_date: date,
    requested_at: datetime,
    completed_at: datetime,
    status_code: int,
    item_count: int,
    total_count: int,
    content: bytes,
    relative_path: Path,
) -> None:
    connection.execute(
        """
        INSERT INTO raw.api_request (
            request_id, batch_id, api_name, request_year, meet_code,
            page_no, page_size, requested_at, completed_at,
            request_url_redacted, http_status, api_status, result_code,
            total_count, item_count, error_message
        ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 'SUCCESS', '00', ?, ?, NULL)
        """,
        [
            request_id,
            batch_id,
            API_NAME,
            race_date.year,
            meet,
            PAGE_SIZE,
            requested_at,
            completed_at,
            f"{BASE_URL}?ServiceKey=REDACTED&pageNo=1&numOfRows={PAGE_SIZE}"
            f"&meet={meet}&rc_date={race_date:%Y%m%d}&_type=json",
            status_code,
            total_count,
            item_count,
        ],
    )
    connection.execute(
        """
        INSERT INTO raw.raw_file
            (raw_file_id, request_id, relative_path, sha256, size_bytes, written_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            str(uuid4()),
            request_id,
            relative_path.as_posix(),
            sha256(content).hexdigest(),
            len(content),
            completed_at,
        ],
    )


def main() -> None:
    load_dotenv(ROOT / ".env", override=False)
    api_key = os.getenv("KRA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("KRA_API_KEY is not configured")

    connection = duckdb.connect(str(DATABASE))
    samples = select_sample_horses(connection)
    if len(samples) != 2:
        raise RuntimeError(f"Expected one sample horse per meet, found {len(samples)}")

    requests_to_make: list[dict[str, Any]] = []
    for sample in samples:
        for sample_date in select_sample_dates(connection, sample["horse_id"]):
            requests_to_make.append(
                {
                    "meet_code": sample["meet_code"],
                    "horse_id": sample["horse_id"],
                    "race_date": sample_date,
                }
            )

    batch_id = str(uuid4())
    started_at = utc_now()
    scope = {"purpose": "API26_2 historical PIT validation", "samples": requests_to_make}
    record_batch(connection, batch_id, scope, started_at)

    observations: list[dict[str, Any]] = []
    raw_dir = ROOT / "data" / "raw" / "api26_2_pit_validation"
    raw_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=30.0) as client:
        for request in requests_to_make:
            meet = int(request["meet_code"])
            race_date = request["race_date"]
            horse_id = str(request["horse_id"])
            request_id = str(uuid4())
            requested_at = utc_now()
            response = client.get(
                BASE_URL,
                params={
                    "ServiceKey": api_key,
                    "pageNo": "1",
                    "numOfRows": str(PAGE_SIZE),
                    "meet": str(meet),
                    "rc_date": race_date.strftime("%Y%m%d"),
                    "_type": "json",
                },
            )
            completed_at = utc_now()
            response.raise_for_status()
            document = response.json()
            items = parse_items(document)
            total_count = int(document["response"]["body"].get("totalCount", len(items)))
            matching = [item for item in items if str(item.get("hrNo", "")) == horse_id]
            if len(matching) != 1:
                raise RuntimeError(
                    f"Expected one API26 item for horse {horse_id} on {race_date}, "
                    f"found {len(matching)}; response item count={len(items)}"
                )

            content = response.content
            filename = (
                f"api26_2_meet{meet}_{race_date:%Y%m%d}_"
                f"{completed_at:%Y%m%dT%H%M%S%fZ}_{request_id[:8]}.json"
            )
            absolute_path = raw_dir / filename
            with absolute_path.open("xb") as stream:
                stream.write(content)
            relative_path = absolute_path.relative_to(ROOT)
            record_request(
                connection,
                batch_id=batch_id,
                request_id=request_id,
                meet=meet,
                race_date=race_date,
                requested_at=requested_at,
                completed_at=completed_at,
                status_code=response.status_code,
                item_count=len(items),
                total_count=total_count,
                content=content,
                relative_path=relative_path,
            )

            item = matching[0]
            api_values = {
                logical_name: as_int(item.get(source_name))
                for logical_name, source_name in CUMULATIVE_FIELDS.items()
            }
            api_values.update(
                {
                    "rating": as_int(item.get("rating")),
                    "carried_weight": as_float(item.get("wgBudam")),
                    "runner_count": as_int(item.get("dusu")),
                    "gate_no": as_int(item.get("chulNo")),
                    "distance_m": as_int(item.get("rcDist")),
                    "grade": item.get("rank"),
                    "jockey_id": item.get("jkNo"),
                    "trainer_id": item.get("trNo"),
                }
            )
            observations.append(
                {
                    **request,
                    "request_id": request_id,
                    "api_item_keys": sorted(item.keys()),
                    "api": api_values,
                    "api4_history": history_stats(connection, horse_id, race_date),
                    "api4_current": current_race_values(connection, horse_id, race_date),
                }
            )

    completed_at = utc_now()
    connection.execute(
        """
        UPDATE raw.collection_batch
        SET completed_at = ?, status = 'COMPLETED', request_count = ?,
            success_count = ?, no_data_count = 0, failure_count = 0
        WHERE batch_id = ?
        """,
        [completed_at, len(observations), len(observations), batch_id],
    )
    connection.close()

    output = {
        "batch_id": batch_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "sample_horses": samples,
        "observations": observations,
    }
    output_path = ROOT / "data" / "exports" / "api26_pit_validation.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "batch_id": batch_id,
                "requests": len(observations),
                "sample_horses": samples,
                "output": str(output_path.relative_to(ROOT)),
            },
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
