from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
from pytest import MonkeyPatch

from kra_analytics.collectors.api4_3 import Api43Collector, audit_batch, validate_response
from kra_analytics.database import connect_database
from kra_analytics.paths import ProjectPaths


def api_document(*, items: list[dict[str, str]], total_count: int) -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {"items": {"item": items}, "totalCount": total_count},
            }
        },
        ensure_ascii=False,
    ).encode()


def item(*, horse_id: str) -> dict[str, str]:
    return {
        "rcDate": "20240105",
        "meet": "서울",
        "rcNo": "1",
        "hrNo": horse_id,
    }


def make_project(tmp_path: Path) -> ProjectPaths:
    repository_root = Path(__file__).parents[1]
    ddl = tmp_path / "sql" / "ddl"
    ddl.mkdir(parents=True)
    for source in (repository_root / "sql" / "ddl").glob("*.sql"):
        shutil.copyfile(source, ddl / source.name)
    return ProjectPaths(
        root=tmp_path,
        raw=tmp_path / "data" / "raw",
        quarantine=tmp_path / "data" / "quarantine",
        warehouse=tmp_path / "data" / "warehouse",
        exports=tmp_path / "data" / "exports",
        logs=tmp_path / "logs",
        sql=tmp_path / "sql",
        database=tmp_path / "data" / "warehouse" / "test.duckdb",
    )


def test_validate_response_rejects_request_mismatch() -> None:
    content = api_document(
        items=[{"rcDate": "20230101", "meet": "서울", "rcNo": "1", "hrNo": "1"}],
        total_count=1,
    )

    result = validate_response(
        content=content,
        http_status=200,
        requested_year=2024,
        requested_meet=1,
    )

    assert result.status == "REQUEST_MISMATCH"


def test_collect_all_pages_writes_raw_and_manifest(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("KRA_API_KEY", "unit-test-secret")
    paths = make_project(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["pageNo"])
        content = (
            api_document(items=[item(horse_id="1"), item(horse_id="2")], total_count=3)
            if page == 1
            else api_document(items=[item(horse_id="3")], total_count=3)
        )
        return httpx.Response(200, content=content, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        outcome = Api43Collector(paths=paths, client=client, page_size=2).collect(
            years=[2024], meets=[1], all_pages=True
        )
    finally:
        client.close()

    assert outcome.request_count == 2
    assert outcome.success_count == 2
    assert outcome.failure_count == 0
    raw_files = list(paths.raw.rglob("*.json"))
    assert len(raw_files) == 2

    with connect_database(paths=paths, read_only=True) as connection:
        requests = connection.execute(
            "SELECT api_status, request_url_redacted FROM raw.api_request ORDER BY page_no"
        ).fetchall()
        files = connection.execute(
            "SELECT relative_path, sha256, size_bytes FROM raw.raw_file"
        ).fetchall()
    assert requests == [
        ("SUCCESS", requests[0][1]),
        ("SUCCESS", requests[1][1]),
    ]
    assert all("REDACTED" in request[1] for request in requests)
    assert all("unit-test-secret" not in request[1] for request in requests)
    assert len(files) == 2
    assert all(len(file[1]) == 64 and file[2] > 0 for file in files)
    assert audit_batch(batch_id=outcome.batch_id, paths=paths) == []


def test_failed_json_is_saved_and_recorded(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("KRA_API_KEY", "unit-test-secret")
    paths = make_project(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        outcome = Api43Collector(paths=paths, client=client).collect(
            years=[2024], meets=[1], all_pages=False
        )
    finally:
        client.close()

    assert outcome.failure_count == 1
    assert len(list(paths.raw.rglob("*.json"))) == 1
    with connect_database(paths=paths, read_only=True) as connection:
        status = connection.execute("SELECT api_status FROM raw.api_request").fetchone()
    assert status == ("INVALID_JSON",)
