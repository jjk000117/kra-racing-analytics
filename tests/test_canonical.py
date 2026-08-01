from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
from pytest import MonkeyPatch

from kra_analytics.canonical import audit_canonical, build_canonical
from kra_analytics.collectors.api4_3 import Api43Collector
from kra_analytics.collectors.api179_1 import Api179Collector
from kra_analytics.database import connect_database
from kra_analytics.paths import ProjectPaths
from kra_analytics.staging import load_staging_batch


def _response(item: dict[str, str] | list[dict[str, str]]) -> bytes:
    count = len(item) if isinstance(item, list) else 1
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"totalCount": count, "items": {"item": item}},
            }
        },
        ensure_ascii=False,
    ).encode()


def _project(tmp_path: Path) -> ProjectPaths:
    root = Path(__file__).parents[1]
    for directory in ("ddl", "transforms"):
        target = tmp_path / "sql" / directory
        target.mkdir(parents=True)
        for source in (root / "sql" / directory).glob("*.sql"):
            shutil.copyfile(source, target / source.name)
    return ProjectPaths.from_root(tmp_path)


def test_build_canonical_creates_separate_idempotent_tables(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("KRA_API_KEY", "test-secret")
    paths = _project(tmp_path)
    race_item = [
        {
            "rcDate": "20240105",
            "meet": "서울",
            "rcNo": "1",
            "hrNo": "H1",
            "ord": "1",
            "rcName": "일반",
            "rank": "국6등급",
        },
        {
            "rcDate": "20240105",
            "meet": "서울",
            "rcNo": "1",
            "hrNo": "H2",
            "ord": "94",
            "rcTime": "0",
            "rcName": "일반",
            "rank": "국6등급",
        },
    ]
    sales_item = {
        "rcDate": "20240105",
        "meet": "1",
        "rcNo": "1",
        "pool": "단식",
        "amt": "1000",
        "odds": "1-2.3",
    }
    race_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=_response(race_item), request=request)
        )
    )
    sales_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=_response(sales_item), request=request)
        )
    )
    try:
        race_batch = Api43Collector(paths=paths, client=race_client).collect(
            years=[2024], meets=[1], all_pages=True
        )
        sales_batch = Api179Collector(paths=paths, client=sales_client).collect(
            years=[2024], meets=[1], all_pages=True
        )
    finally:
        race_client.close()
        sales_client.close()
    load_staging_batch(race_batch.batch_id, paths=paths)
    load_staging_batch(sales_batch.batch_id, paths=paths)

    first = build_canonical(
        race_batch_id=race_batch.batch_id,
        sales_batch_id=sales_batch.batch_id,
        paths=paths,
    )
    second = build_canonical(
        race_batch_id=race_batch.batch_id,
        sales_batch_id=sales_batch.batch_id,
        paths=paths,
    )

    assert first == second
    assert first.race_count == 1
    assert first.runner_count == 2
    assert first.sales_count == 1
    assert first.issue_count == 1
    assert audit_canonical(paths=paths) == []
    with connect_database(paths=paths, read_only=True) as connection:
        dns = connection.execute(
            "SELECT result_status, is_valid_start, is_valid_finish "
            "FROM canonical.runner_result WHERE ord_raw = '94'"
        ).fetchone()
    assert dns == ("DNS", False, False)
