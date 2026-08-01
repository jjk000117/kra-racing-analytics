from __future__ import annotations

import json

import httpx

from kra_analytics.collectors.api179_1 import Api179Collector, audit_batch, validate_response
from kra_analytics.paths import ProjectPaths
from kra_analytics.staging import audit_staging_batch, load_staging_batch


def payload(*, year: int = 2024, meet: int = 1, total: int = 1) -> bytes:
    item = {
        "rcDate": f"{year}0101",
        "meet": str(meet),
        "rcNo": "1",
        "pool": "단승",
        "amt": "1000",
        "odds": "1-2.3",
    }
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": "00"},
                "body": {"totalCount": total, "items": {"item": item}},
            }
        }
    ).encode()


def test_validate_rejects_request_mismatch() -> None:
    result = validate_response(
        content=payload(year=2025), http_status=200, requested_year=2024, requested_meet=1
    )
    assert result.status == "REQUEST_MISMATCH"


def test_collect_writes_raw_and_manifest(tmp_path, monkeypatch) -> None:
    root = tmp_path / "project"
    (root / "sql" / "ddl").mkdir(parents=True)
    source_root = ProjectPaths.from_root().root
    for ddl in (source_root / "sql" / "ddl").glob("*.sql"):
        (root / "sql" / "ddl" / ddl.name).write_bytes(ddl.read_bytes())
    monkeypatch.setenv("KRA_API_KEY", "test-secret")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=payload(), request=request)
        )
    )
    paths = ProjectPaths.from_root(root)
    outcome = Api179Collector(paths=paths, client=client).collect(
        years=[2024], meets=[1], all_pages=True
    )
    client.close()
    assert outcome.success_count == 1
    assert audit_batch(batch_id=outcome.batch_id, paths=paths) == []
    first = load_staging_batch(outcome.batch_id, paths=paths)
    second = load_staging_batch(outcome.batch_id, paths=paths)
    assert first.staged_rows == 1
    assert first.inserted_rows == 1
    assert second.staged_rows == 1
    assert second.inserted_rows == 0
    assert audit_staging_batch(outcome.batch_id, paths=paths) == []
