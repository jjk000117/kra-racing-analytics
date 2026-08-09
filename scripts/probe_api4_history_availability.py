from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any

import httpx

from kra_analytics.collectors.api4_3 import BASE_URL, get_api_key
from kra_analytics.paths import ProjectPaths

YEARS = (2022, 2023)
MEETS = (1, 3)
SAMPLE_MONTHS = (1, 6, 12)
CRITICAL_FIELDS = (
    "rcDate",
    "meet",
    "rcNo",
    "hrNo",
    "hrName",
    "ord",
    "rcTime",
    "jkNo",
    "jkName",
    "trNo",
    "trName",
    "rating",
    "rcDist",
    "rank",
    "wgBudam",
    "age",
    "sex",
)


def extract(document: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    response = document["response"]
    if str(response["header"]["resultCode"]) != "00":
        raise ValueError(str(response["header"].get("resultMsg", "API error")))
    body = response["body"]
    total = int(body["totalCount"])
    if total == 0:
        return 0, []
    raw = body["items"]["item"]
    items = [raw] if isinstance(raw, dict) else raw
    return total, items


def request(
    client: httpx.Client, api_key: str, *, meet: int, rows: int, **filters: str
) -> tuple[int, list[dict[str, Any]]]:
    params = {
        "ServiceKey": api_key,
        "pageNo": "1",
        "numOfRows": str(rows),
        "meet": str(meet),
        "_type": "json",
        **filters,
    }
    response = client.get(BASE_URL, params=params)
    response.raise_for_status()
    return extract(response.json())


def current_field_set(paths: ProjectPaths) -> set[str]:
    candidates = sorted((paths.raw / "api4_3" / "2024").glob("meet_*/*.json"))
    if not candidates:
        raise FileNotFoundError("A trusted 2024 API4 Raw file is required for schema comparison")
    document = json.loads(candidates[0].read_text(encoding="utf-8"))
    _, items = extract(document)
    return set().union(*(item.keys() for item in items))


def main() -> None:
    paths = ProjectPaths.from_root()
    api_key = get_api_key(paths)
    reference_fields = current_field_set(paths)
    monthly: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    observed_fields: set[str] = set()

    with httpx.Client(timeout=30.0, transport=httpx.HTTPTransport(retries=2)) as client:
        for year in YEARS:
            for meet in MEETS:
                first_dates: dict[int, str] = {}
                for month in range(1, 13):
                    month_key = f"{year}{month:02d}"
                    total, items = request(
                        client, api_key, meet=meet, rows=1, rc_month=month_key
                    )
                    first_date = str(items[0]["rcDate"]) if items else ""
                    if first_date:
                        first_dates[month] = first_date
                    monthly.append(
                        {
                            "year": year,
                            "meet": meet,
                            "month": month_key,
                            "runner_rows": total,
                            "first_observed_race_date": first_date or None,
                        }
                    )

                for month in SAMPLE_MONTHS:
                    race_date = first_dates.get(month)
                    if race_date is None:
                        samples.append(
                            {
                                "year": year,
                                "meet": meet,
                                "target_month": month,
                                "status": "NO_MONTH_DATA",
                            }
                        )
                        continue
                    total, items = request(
                        client, api_key, meet=meet, rows=1000, rc_date=race_date
                    )
                    field_union = set().union(*(item.keys() for item in items))
                    observed_fields.update(field_union)
                    missing_critical = [
                        field
                        for field in CRITICAL_FIELDS
                        if any(field not in item for item in items)
                    ]
                    null_rates = {
                        field: sum(item.get(field) in (None, "") for item in items) / len(items)
                        for field in CRITICAL_FIELDS
                    }
                    race_keys = {
                        (str(item["rcDate"]), str(item["meet"]), str(item["rcNo"]))
                        for item in items
                    }
                    race_sizes = Counter(
                        (str(item["rcDate"]), str(item["meet"]), str(item["rcNo"]))
                        for item in items
                    )
                    ratings = [
                        int(str(item["rating"]))
                        for item in items
                        if str(item.get("rating", "")).strip()
                    ]
                    samples.append(
                        {
                            "year": year,
                            "meet": meet,
                            "target_month": month,
                            "race_date": race_date,
                            "status": "SUCCESS",
                            "runner_rows": total,
                            "returned_rows": len(items),
                            "race_count": len(race_keys),
                            "race_size_min": min(race_sizes.values()),
                            "race_size_median": median(race_sizes.values()),
                            "race_size_max": max(race_sizes.values()),
                            "field_count": len(field_union),
                            "missing_critical_fields": missing_critical,
                            "critical_field_null_rates": null_rates,
                            "ord_values": dict(Counter(str(item.get("ord")) for item in items)),
                            "race_grade_values": dict(
                                Counter(str(item.get("rank")) for item in items)
                            ),
                            "rating_min": min(ratings) if ratings else None,
                            "rating_max": max(ratings) if ratings else None,
                            "meet_values": sorted({str(item.get("meet")) for item in items}),
                            "fields_missing_vs_2024": sorted(reference_fields - field_union),
                            "fields_added_vs_2024": sorted(field_union - reference_fields),
                        }
                    )

    output = {
        "probe_version": "api4_history_availability_probe_v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "request_scope": {
            "years": YEARS,
            "meets": MEETS,
            "monthly_metadata_requests": len(YEARS) * len(MEETS) * 12,
            "full_day_sample_requests": len(YEARS) * len(MEETS) * len(SAMPLE_MONTHS),
            "raw_or_database_persistence": False,
        },
        "reference_2024_field_count": len(reference_fields),
        "observed_historical_field_count": len(observed_fields),
        "historical_fields_missing_vs_2024_union": sorted(reference_fields - observed_fields),
        "historical_fields_added_vs_2024_union": sorted(observed_fields - reference_fields),
        "monthly_continuity": monthly,
        "day_samples": samples,
        "api_key_stored_or_emitted": False,
    }
    output_directory = paths.exports / "validation" / "api4_history_availability_v1"
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / "probe_result.json"
    if output_path.exists():
        raise FileExistsError("Historical API4 probe result already exists")
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"monthly_metadata_requests={output['request_scope']['monthly_metadata_requests']}")
    print(f"full_day_sample_requests={output['request_scope']['full_day_sample_requests']}")
    print(f"result_path={output_path}")


if __name__ == "__main__":
    main()
