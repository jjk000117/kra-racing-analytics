from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "warehouse" / "kra.duckdb"
EVIDENCE = ROOT / "data" / "exports" / "api26_pit_validation.json"
OUTPUT = ROOT / "data" / "exports" / "api26_pit_validation_summary.json"
RAW_DIR = ROOT / "data" / "raw" / "api26_2_pit_validation"


def parse_items(document: dict[str, Any]) -> list[dict[str, Any]]:
    raw = document["response"]["body"]["items"]["item"]
    return [raw] if isinstance(raw, dict) else raw


def current_values(
    connection: duckdb.DuckDBPyConnection, horse_id: str, race_date: date
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT r.meet_code, r.race_no, r.distance_m, r.race_grade, r.runner_count,
               rr.gate_no, rr.horse_sex, rr.horse_age, rr.carried_weight,
               rr.jockey_id, rr.trainer_id, rr.owner_id,
               try_cast(s.rating AS INTEGER)
        FROM canonical.runner_result rr
        JOIN canonical.race r USING (race_id)
        JOIN staging.race_result s
          ON s.staging_row_id = rr.source_staging_row_id
        WHERE rr.horse_id = ? AND r.race_date = ?
        """,
        [horse_id, race_date],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Missing API4 row for {horse_id} on {race_date}")
    names = [
        "meet_code",
        "race_no",
        "distance_m",
        "race_grade",
        "runner_count",
        "gate_no",
        "horse_sex",
        "horse_age",
        "carried_weight",
        "jockey_id",
        "trainer_id",
        "owner_id",
        "rating",
    ]
    return dict(zip(names, row, strict=True))


def normalize(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        return str(float(text))
    except ValueError:
        return text


def normalize_meet(value: Any) -> str | None:
    mapping = {"서울": "1", "부산경남": "3", "1": "1", "3": "3"}
    return mapping.get(str(value).strip()) if value is not None else None


def main() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    connection = duckdb.connect(str(DATABASE), read_only=True)
    detail: list[dict[str, Any]] = []

    field_map = {
        "meet_code": "meet",
        "race_no": "rcNo",
        "distance_m": "rcDist",
        "race_grade": "rank",
        "runner_count": "dusu",
        "gate_no": "chulNo",
        "horse_sex": "sex",
        "horse_age": "age",
        "carried_weight": "wgBudam",
        "jockey_id": "jkNo",
        "trainer_id": "trNo",
        "owner_id": "owNo",
        "rating": "rating",
    }

    for observation in evidence["observations"]:
        request_prefix = observation["request_id"][:8]
        matching_files = list(RAW_DIR.glob(f"*{request_prefix}.json"))
        if len(matching_files) != 1:
            raise RuntimeError(f"Expected one Raw file for request {request_prefix}")
        document = json.loads(matching_files[0].read_text(encoding="utf-8"))
        items = parse_items(document)
        item = next(
            row
            for row in items
            if str(row.get("hrNo")) == str(observation["horse_id"])
        )
        race_date = date.fromisoformat(observation["race_date"])
        api4 = current_values(connection, observation["horse_id"], race_date)
        matches = {}
        for logical, api_field in field_map.items():
            if logical == "meet_code":
                matches[logical] = normalize_meet(item.get(api_field)) == normalize_meet(
                    api4[logical]
                )
            else:
                matches[logical] = normalize(item.get(api_field)) == normalize(api4[logical])
        detail.append(
            {
                "horse_id": observation["horse_id"],
                "race_date": observation["race_date"],
                "api26": {logical: item.get(api_field) for logical, api_field in field_map.items()},
                "api4": api4,
                "matches": matches,
                "api26_ilsu": item.get("ilsu"),
                "cumulative_api26": observation["api"],
                "history_api4": observation["api4_history"],
            }
        )

    match_summary = {
        logical: {
            "matches": sum(row["matches"][logical] for row in detail),
            "samples": len(detail),
        }
        for logical in field_map
    }
    cumulative_distinct_by_horse: dict[str, dict[str, int]] = {}
    for horse_id in sorted({row["horse_id"] for row in detail}):
        horse_rows = [row for row in detail if row["horse_id"] == horse_id]
        cumulative_distinct_by_horse[horse_id] = {
            field: len({row["cumulative_api26"][field] for row in horse_rows})
            for field in (
                "starts_lifetime",
                "firsts_lifetime",
                "seconds_lifetime",
                "thirds_lifetime",
                "starts_recent_year",
                "firsts_recent_year",
                "seconds_recent_year",
                "thirds_recent_year",
            )
        }

    manifest_rows = connection.execute(
        """
        SELECT f.relative_path, f.sha256, f.size_bytes
        FROM raw.api_request r
        JOIN raw.raw_file f USING (request_id)
        WHERE r.batch_id = ?
        ORDER BY f.relative_path
        """,
        [evidence["batch_id"]],
    ).fetchall()
    manifest_hash_matches = 0
    for relative_path, expected_hash, expected_size in manifest_rows:
        content = (ROOT / relative_path).read_bytes()
        if sha256(content).hexdigest() == expected_hash and len(content) == expected_size:
            manifest_hash_matches += 1

    connection.close()
    summary = {
        "source_batch_id": evidence["batch_id"],
        "sample_count": len(detail),
        "match_summary": match_summary,
        "cumulative_distinct_by_horse": cumulative_distinct_by_horse,
        "manifest": {
            "requests_with_raw": len(manifest_rows),
            "hash_and_size_matches": manifest_hash_matches,
        },
        "detail": detail,
    }
    OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "detail"}))


if __name__ == "__main__":
    main()
