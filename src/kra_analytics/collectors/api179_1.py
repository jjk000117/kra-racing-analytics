from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from kra_analytics.collectors.api4_3 import (
    ALLOWED_MEETS,
    FAILURE_STATUSES,
    audit_batch,
    get_api_key,
)
from kra_analytics.collectors.models import ApiValidation, BatchOutcome, RawArtifact
from kra_analytics.database import connect_database, initialize_database
from kra_analytics.logging import configure_logging, safe_exception_message
from kra_analytics.paths import ProjectPaths

API_NAME = "API179_1"
BASE_URL = "https://apis.data.go.kr/B551015/API179_1/salesAndDividendRate_1"
DEFAULT_PAGE_SIZE = 1000


def utc_now() -> datetime:
    return datetime.now(UTC)


def request_params(
    *, api_key: str, year: int, meet: int, page: int, page_size: int
) -> dict[str, str]:
    return {
        "ServiceKey": api_key,
        "pageNo": str(page),
        "numOfRows": str(page_size),
        "meet": str(meet),
        "rc_year": str(year),
        "_type": "json",
    }


def redacted_url(*, year: int, meet: int, page: int, page_size: int) -> str:
    return (
        f"{BASE_URL}?ServiceKey=REDACTED&pageNo={page}&numOfRows={page_size}"
        f"&meet={meet}&rc_year={year}&_type=json"
    )


def _items(document: dict[str, Any]) -> list[dict[str, Any]] | None:
    try:
        value = document["response"]["body"]["items"]["item"]
    except (KeyError, TypeError):
        return None
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    return None


def validate_response(
    *, content: bytes, http_status: int, requested_year: int, requested_meet: int
) -> ApiValidation:
    if not 200 <= http_status < 300:
        return ApiValidation("HTTP_ERROR", None, None, 0, f"HTTP status {http_status}")
    if not content.strip():
        return ApiValidation("EMPTY_BODY", None, None, 0, "Response body is empty")
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return ApiValidation("INVALID_JSON", None, None, 0, str(error))
    if not isinstance(document, dict):
        return ApiValidation("INVALID_SCHEMA", None, None, 0, "Root JSON is not an object")
    try:
        header = document["response"]["header"]
        body = document["response"]["body"]
        result_code = str(header["resultCode"])
    except (KeyError, TypeError):
        return ApiValidation("INVALID_SCHEMA", None, None, 0, "Response structure is missing")
    if result_code != "00":
        return ApiValidation("API_ERROR", result_code, None, 0, str(header.get("resultMsg")))
    try:
        total_count = int(body["totalCount"])
    except (KeyError, TypeError, ValueError):
        return ApiValidation("INVALID_SCHEMA", result_code, None, 0, "Invalid totalCount")
    if total_count == 0:
        return ApiValidation("NO_DATA", result_code, 0, 0)
    items = _items(document)
    required = {"rcDate", "meet", "rcNo", "pool", "amt", "odds"}
    if not items or any(not required.issubset(item) for item in items):
        return ApiValidation(
            "INVALID_SCHEMA",
            result_code,
            total_count,
            len(items or []),
            "Required sales fields are missing",
        )
    meet_name = ALLOWED_MEETS[requested_meet]
    matches = all(
        str(item["rcDate"]).startswith(str(requested_year))
        and str(item["meet"]) in {str(requested_meet), meet_name}
        for item in items
    )
    if not matches:
        return ApiValidation(
            "REQUEST_MISMATCH",
            result_code,
            total_count,
            len(items),
            "Response scope differs from request",
        )
    return ApiValidation("SUCCESS", result_code, total_count, len(items))


def _write_raw(
    *, content: bytes, paths: ProjectPaths, year: int, meet: int, page: int, request_id: str
) -> RawArtifact:
    stamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    relative = Path("data") / "raw" / "api179_1" / str(year) / f"meet_{meet}"
    filename = f"api179_1_{year}_meet{meet}_p{page:03d}_{stamp}_{request_id[:8]}.json"
    absolute = paths.root / relative / filename
    absolute.parent.mkdir(parents=True, exist_ok=True)
    with absolute.open("xb") as stream:
        stream.write(content)
    return RawArtifact(
        (relative / filename).as_posix(), absolute, sha256(content).hexdigest(), len(content)
    )


class Api179Collector:
    def __init__(
        self,
        *,
        paths: ProjectPaths | None = None,
        client: httpx.Client | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        self.paths = paths or ProjectPaths.from_root()
        self.client = client
        self.page_size = page_size
        self.logger = configure_logging()

    def collect(
        self, *, years: list[int], meets: list[int], all_pages: bool, page: int = 1
    ) -> BatchOutcome:
        if not years or any(year < 2000 or year > 2100 for year in years):
            raise ValueError("years must contain plausible four-digit years")
        if not meets or any(meet not in ALLOWED_MEETS for meet in meets):
            raise ValueError("meets must contain only 1 or 3")
        initialize_database(paths=self.paths)
        key = get_api_key(self.paths)
        batch_id = f"{utc_now().strftime('%Y%m%dT%H%M%S%fZ')}_{API_NAME.lower()}_{uuid4().hex[:8]}"
        with connect_database(paths=self.paths) as connection:
            connection.execute(
                """
                INSERT INTO raw.collection_batch
                    (batch_id, api_name, scope_json, started_at, status)
                VALUES (?, ?, ?, ?, 'RUNNING')
                """,
                [
                    batch_id,
                    API_NAME,
                    json.dumps(
                        {
                            "years": years,
                            "meets": meets,
                            "page": page,
                            "page_size": self.page_size,
                            "all_pages": all_pages,
                        }
                    ),
                    utc_now(),
                ],
            )
        owns_client = self.client is None
        client = self.client or httpx.Client(timeout=30.0, transport=httpx.HTTPTransport(retries=2))
        try:
            for year in years:
                for meet in meets:
                    first_status, total = self._collect_page(
                        client, key, batch_id, year, meet, page
                    )
                    if all_pages and first_status == "SUCCESS" and total is not None:
                        for next_page in range(page + 1, math.ceil(total / self.page_size) + 1):
                            status, _ = self._collect_page(
                                client, key, batch_id, year, meet, next_page
                            )
                            if status in FAILURE_STATUSES:
                                break
        finally:
            if owns_client:
                client.close()
        return self._complete(batch_id)

    def _collect_page(
        self, client: httpx.Client, key: str, batch_id: str, year: int, meet: int, page: int
    ) -> tuple[str, int | None]:
        request_id = str(uuid4())
        started = utc_now()
        artifact: RawArtifact | None = None
        http_status: int | None = None
        try:
            response = client.get(
                BASE_URL,
                params=request_params(
                    api_key=key, year=year, meet=meet, page=page, page_size=self.page_size
                ),
            )
            http_status = response.status_code
            artifact = _write_raw(
                content=response.content,
                paths=self.paths,
                year=year,
                meet=meet,
                page=page,
                request_id=request_id,
            )
            validation = validate_response(
                content=response.content,
                http_status=http_status,
                requested_year=year,
                requested_meet=meet,
            )
        except httpx.HTTPError as error:
            validation = ApiValidation(
                "REQUEST_ERROR",
                None,
                None,
                0,
                safe_exception_message(error, secrets=(key,)),
            )
        completed = utc_now()
        with connect_database(paths=self.paths) as connection:
            connection.begin()
            try:
                connection.execute(
                    """
                    INSERT INTO raw.api_request (
                        request_id, batch_id, api_name, request_year, meet_code,
                        page_no, page_size, requested_at, completed_at,
                        request_url_redacted, http_status, api_status, result_code,
                        total_count, item_count, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        request_id,
                        batch_id,
                        API_NAME,
                        year,
                        meet,
                        page,
                        self.page_size,
                        started,
                        completed,
                        redacted_url(year=year, meet=meet, page=page, page_size=self.page_size),
                        http_status,
                        validation.status,
                        validation.result_code,
                        validation.total_count,
                        validation.item_count,
                        validation.error_message,
                    ],
                )
                if artifact:
                    connection.execute(
                        """
                        INSERT INTO raw.raw_file (
                            raw_file_id, request_id, relative_path, sha256,
                            size_bytes, written_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        [
                            str(uuid4()),
                            request_id,
                            artifact.relative_path,
                            artifact.sha256,
                            artifact.size_bytes,
                            completed,
                        ],
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        self.logger.info(
            "api=%s year=%d meet=%d page=%d status=%s items=%d",
            API_NAME,
            year,
            meet,
            page,
            validation.status,
            validation.item_count,
        )
        return validation.status, validation.total_count

    def _complete(self, batch_id: str) -> BatchOutcome:
        with connect_database(paths=self.paths) as connection:
            row = connection.execute(
                """
                SELECT count(1), count_if(api_status = 'SUCCESS'),
                    count_if(api_status = 'NO_DATA'),
                    count_if(api_status NOT IN ('SUCCESS', 'NO_DATA'))
                FROM raw.api_request WHERE batch_id = ?
                """,
                [batch_id],
            ).fetchone()
            assert row is not None
            counts = tuple(map(int, row))
            connection.execute(
                """
                UPDATE raw.collection_batch
                SET completed_at = ?, status = ?, request_count = ?,
                    success_count = ?, no_data_count = ?, failure_count = ?
                WHERE batch_id = ?
                """,
                [
                    utc_now(),
                    "COMPLETED" if counts[3] == 0 else "COMPLETED_WITH_ERRORS",
                    *counts,
                    batch_id,
                ],
            )
        return BatchOutcome(batch_id, *counts)


__all__ = ["Api179Collector", "audit_batch", "validate_response"]
