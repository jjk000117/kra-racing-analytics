from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast

from kra_analytics.database import connect_database
from kra_analytics.paths import ProjectPaths

RACE_REQUIRED = ("rcDate", "meet", "rcNo", "hrNo")
SALES_REQUIRED = ("rcDate", "meet", "rcNo", "pool", "amt", "odds")


def _items(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_bytes())
    value = document["response"]["body"]["items"]["item"]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return cast(list[dict[str, Any]], value)
    raise ValueError(f"Unexpected items.item shape in {path}")


def _meet_code(value: Any) -> str:
    text = str(value).strip()
    return {"서울": "1", "부산경남": "3"}.get(text, text)


def _race_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return str(item["rcDate"]), _meet_code(item["meet"]), str(int(item["rcNo"]))


def _full_batch_files(paths: ProjectPaths, api_name: str) -> tuple[str, list[Path]]:
    with connect_database(paths=paths, read_only=True) as connection:
        batch = connection.execute(
            """
            SELECT batch_id
            FROM raw.collection_batch
            WHERE api_name = ? AND status = 'COMPLETED'
            ORDER BY request_count DESC, completed_at DESC
            LIMIT 1
            """,
            [api_name],
        ).fetchone()
        if batch is None:
            raise RuntimeError(f"No completed collection batch for {api_name}")
        rows = connection.execute(
            """
            SELECT f.relative_path
            FROM raw.raw_file f
            JOIN raw.api_request r ON r.request_id = f.request_id
            WHERE r.batch_id = ?
            ORDER BY r.requested_at
            """,
            [batch[0]],
        ).fetchall()
    return str(batch[0]), [paths.root / str(row[0]) for row in rows]


def _profile_source(
    *, files: list[Path], required: tuple[str, ...], business_key: tuple[str, ...]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = [item for path in files for item in _items(path)]
    field_presence: Counter[str] = Counter()
    field_types: dict[str, Counter[str]] = defaultdict(Counter)
    blank_counts: Counter[str] = Counter()
    for row in rows:
        for field, value in row.items():
            field_presence[field] += 1
            field_types[field][type(value).__name__] += 1
            if value is None or (isinstance(value, str) and not value.strip()):
                blank_counts[field] += 1
    keys = [tuple(str(row.get(field, "")).strip() for field in business_key) for row in rows]
    key_counts = Counter(keys)
    exact_counts = Counter(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows)
    dates = [str(row["rcDate"]) for row in rows if row.get("rcDate")]
    profile = {
        "files": len(files),
        "rows": len(rows),
        "columns_union": len(field_presence),
        "columns_common": sum(count == len(rows) for count in field_presence.values()),
        "field_names": sorted(field_presence),
        "field_missing_counts": {
            field: len(rows) - count + blank_counts[field]
            for field, count in sorted(field_presence.items())
        },
        "field_types": {field: dict(counts) for field, counts in sorted(field_types.items())},
        "missing_required": {
            field: len(rows) - field_presence[field] + blank_counts[field] for field in required
        },
        "date_min": min(dates),
        "date_max": max(dates),
        "business_key_distinct": len(key_counts),
        "duplicate_business_key_rows": sum(count - 1 for count in key_counts.values()),
        "duplicate_business_keys": sum(count > 1 for count in key_counts.values()),
        "exact_duplicate_rows": sum(count - 1 for count in exact_counts.values()),
    }
    return profile, rows


def build_raw_profile(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    race_batch_id, race_files = _full_batch_files(project_paths, "API4_3")
    sales_batch_id, sales_files = _full_batch_files(project_paths, "API179_1")
    race, race_rows = _profile_source(
        files=race_files,
        required=RACE_REQUIRED,
        business_key=("rcDate", "meet", "rcNo", "hrNo"),
    )
    sales, sales_rows = _profile_source(
        files=sales_files,
        required=SALES_REQUIRED,
        business_key=("rcDate", "meet", "rcNo", "pool"),
    )

    race_keys = {_race_key(row) for row in race_rows}
    sales_keys = {_race_key(row) for row in sales_rows}
    shared = race_keys & sales_keys
    unmatched_race_rows: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in race_rows:
        key = _race_key(row)
        if key not in sales_keys:
            unmatched_race_rows[key].append(row)
    sales_pool_counts = Counter(str(row["pool"]).strip() for row in sales_rows)
    sales_amount_invalid = sum(
        1
        for row in sales_rows
        if not str(row.get("amt", "")).replace(",", "").isdigit()
        or int(str(row["amt"]).replace(",", "")) < 0
    )
    by_scope: dict[str, dict[str, int]] = defaultdict(lambda: {"race_rows": 0, "sales_rows": 0})
    for row in race_rows:
        by_scope[f"{str(row['rcDate'])[:4]}|{_meet_code(row['meet'])}"]["race_rows"] += 1
    for row in sales_rows:
        by_scope[f"{str(row['rcDate'])[:4]}|{_meet_code(row['meet'])}"]["sales_rows"] += 1

    return {
        "race_batch_id": race_batch_id,
        "sales_batch_id": sales_batch_id,
        "race": race,
        "sales": sales,
        "race_distinct_races": len(race_keys),
        "sales_distinct_races": len(sales_keys),
        "shared_races": len(shared),
        "race_without_sales": len(race_keys - sales_keys),
        "sales_without_race": len(sales_keys - race_keys),
        "race_without_sales_details": [
            {
                "race_key": "|".join(key),
                "runner_rows": len(rows),
                "rcName": sorted({str(row.get("rcName", "")) for row in rows}),
                "ord": sorted({str(row.get("ord", "")) for row in rows}),
                "rank": sorted({str(row.get("rank", "")) for row in rows}),
            }
            for key, rows in sorted(unmatched_race_rows.items())
        ],
        "race_join_rate": len(shared) / len(race_keys),
        "sales_join_rate": len(shared) / len(sales_keys),
        "sales_pools": dict(sorted(sales_pool_counts.items())),
        "sales_amount_invalid": sales_amount_invalid,
        "by_scope": dict(sorted(by_scope.items())),
    }
