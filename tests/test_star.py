from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
from pytest import MonkeyPatch

from kra_analytics.canonical import build_canonical
from kra_analytics.collectors.api4_3 import Api43Collector
from kra_analytics.collectors.api179_1 import Api179Collector
from kra_analytics.database import connect_database
from kra_analytics.paths import ProjectPaths
from kra_analytics.staging import load_staging_batch
from kra_analytics.star import audit_star, build_star


def _response(items: dict[str, str] | list[dict[str, str]]) -> bytes:
    count = len(items) if isinstance(items, list) else 1
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"totalCount": count, "items": {"item": items}},
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


def test_build_star_creates_complete_market_mart(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("KRA_API_KEY", "test-secret")
    paths = _project(tmp_path)
    race_item = {
        "rcDate": "20240105",
        "meet": "서울",
        "rcNo": "1",
        "hrNo": "H1",
        "ord": "1",
        "rcName": "일반",
        "rank": "국6등급",
        "rcDist": "1200",
    }
    pools = ["단식", "연식", "복식", "쌍식", "복연", "삼복", "삼쌍"]
    sales_items = [
        {
            "rcDate": "20240105",
            "meet": "1",
            "rcNo": "1",
            "pool": pool,
            "amt": str(index * 1000),
            "odds": "1-2.3",
        }
        for index, pool in enumerate(pools, start=1)
    ]
    race_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=_response(race_item), request=request)
        )
    )
    sales_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=_response(sales_items), request=request)
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
    build_canonical(
        race_batch_id=race_batch.batch_id,
        sales_batch_id=sales_batch.batch_id,
        paths=paths,
    )

    first = build_star(paths=paths)
    second = build_star(paths=paths)

    assert first == second
    assert first.race_count == 1
    assert first.sales_count == 7
    assert first.eligible_race_count == 1
    assert first.market_sales_count == 7
    assert audit_star(paths=paths) == []
    with connect_database(paths=paths, read_only=True) as connection:
        race = connection.execute(
            "SELECT pool_count, has_all_official_pools, is_market_eligible "
            "FROM analytics.fact_race"
        ).fetchone()
        pools_actual = connection.execute(
            "SELECT pool_code, pool_name_official FROM analytics.dim_pool ORDER BY display_order"
        ).fetchall()
        total_sales = connection.execute(
            "SELECT sum(sales_amount) FROM analytics.mart_market_sales"
        ).fetchone()
    assert race == (7, True, True)
    assert [row[0] for row in pools_actual] == [
        "WIN",
        "PLC",
        "QNL",
        "EXA",
        "QPL",
        "TLA",
        "TRI",
    ]
    assert total_sales == (28000,)
