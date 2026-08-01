from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from kra_analytics.collectors.models import (
    ApiValidation,
    BatchOutcome,
    RawArtifact,
    RequestOutcome,
)
from kra_analytics.database import connect_database, initialize_database
from kra_analytics.logging import configure_logging
from kra_analytics.paths import ProjectPaths

API_NAME = "API4_3"
BASE_URL = "https://apis.data.go.kr/B551015/API4_3/raceResult_3"
DEFAULT_PAGE_SIZE = 1000
ALLOWED_MEETS = {1: "서울", 3: "부산경남"}
FAILURE_STATUSES = {
    "HTTP_ERROR",
    "EMPTY_BODY",
    "INVALID_JSON",
    "API_ERROR",
    "INVALID_SCHEMA",
    "REQUEST_MISMATCH",
    "REQUEST_ERROR",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def get_api_key(paths: ProjectPaths) -> str:
    load_dotenv(paths.root / ".env", override=False)
    api_key = os.getenv("KRA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "KRA_API_KEY is not configured. Set it in the process environment "
            "or an ignored .env file."
        )
    return api_key


def redacted_url(*, year: int, meet: int, page: int, page_size: int) -> str:
    return (
        f"{BASE_URL}?ServiceKey=REDACTED&pageNo={page}&numOfRows={page_size}"
        f"&meet={meet}&rc_year={year}&_type=json"
    )


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


def _extract_items(document: dict[str, Any]) -> list[dict[str, Any]] | None:
    try:
        raw_items = document["response"]["body"]["items"]["item"]
    except (KeyError, TypeError):
        return None
    if isinstance(raw_items, dict):
        return [raw_items]
    if isinstance(raw_items, list) and all(isinstance(item, dict) for item in raw_items):
        return raw_items
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
        return ApiValidation("INVALID_SCHEMA", None, None, 0, "Root JSON value is not an object")

    try:
        response = document["response"]
        header = response["header"]
        body = response["body"]
        result_code = str(header["resultCode"])
    except (KeyError, TypeError):
        return ApiValidation(
            "INVALID_SCHEMA", None, None, 0, "Required response structure is missing"
        )
    if result_code != "00":
        result_message = str(header.get("resultMsg", "API error"))
        return ApiValidation("API_ERROR", result_code, None, 0, result_message)

    try:
        total_count = int(body["totalCount"])
    except (KeyError, TypeError, ValueError):
        return ApiValidation(
            "INVALID_SCHEMA", result_code, None, 0, "totalCount is missing or invalid"
        )
    if total_count == 0:
        return ApiValidation("NO_DATA", result_code, 0, 0)

    items = _extract_items(document)
    if not items:
        return ApiValidation(
            "INVALID_SCHEMA", result_code, total_count, 0, "items.item is missing or empty"
        )
    required_fields = {"rcDate", "meet", "rcNo", "hrNo"}
    if any(not required_fields.issubset(item) for item in items):
        return ApiValidation(
            "INVALID_SCHEMA",
            result_code,
            total_count,
            len(items),
            "Required item fields are missing",
        )

    requested_meet_name = ALLOWED_MEETS[requested_meet]
    year_matches = all(str(item["rcDate"]).startswith(str(requested_year)) for item in items)
    meet_matches = all(
        str(item["meet"]) in {str(requested_meet), requested_meet_name} for item in items
    )
    if not year_matches or not meet_matches:
        return ApiValidation(
            "REQUEST_MISMATCH",
            result_code,
            total_count,
            len(items),
            "Response year or meet does not match the request",
        )
    return ApiValidation("SUCCESS", result_code, total_count, len(items))


def write_raw(
    *, content: bytes, paths: ProjectPaths, year: int, meet: int, page: int, request_id: str
) -> RawArtifact:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    relative = Path("data") / "raw" / "api4_3" / str(year) / f"meet_{meet}"
    filename = f"api4_3_{year}_meet{meet}_p{page:03d}_{timestamp}_{request_id[:8]}.json"
    absolute = paths.root / relative / filename
    absolute.parent.mkdir(parents=True, exist_ok=True)
    with absolute.open("xb") as stream:
        stream.write(content)
    return RawArtifact(
        relative_path=(relative / filename).as_posix(),
        absolute_path=absolute,
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
    )


def _insert_batch(*, paths: ProjectPaths, batch_id: str, scope: dict[str, Any]) -> None:
    with connect_database(paths=paths) as connection:
        connection.execute(
            """
            INSERT INTO raw.collection_batch
                (batch_id, api_name, scope_json, started_at, status)
            VALUES (?, ?, ?, ?, 'RUNNING')
            """,
            [batch_id, API_NAME, json.dumps(scope, ensure_ascii=False), utc_now()],
        )


def _record_request(
    *,
    paths: ProjectPaths,
    batch_id: str,
    request_id: str,
    year: int,
    meet: int,
    page: int,
    page_size: int,
    requested_at: datetime,
    completed_at: datetime,
    http_status: int | None,
    validation: ApiValidation,
    artifact: RawArtifact | None,
) -> None:
    with connect_database(paths=paths) as connection:
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
                    page_size,
                    requested_at,
                    completed_at,
                    redacted_url(year=year, meet=meet, page=page, page_size=page_size),
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
                    INSERT INTO raw.raw_file
                        (raw_file_id, request_id, relative_path, sha256, size_bytes, written_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        str(uuid4()),
                        request_id,
                        artifact.relative_path,
                        artifact.sha256,
                        artifact.size_bytes,
                        completed_at,
                    ],
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _complete_batch(*, paths: ProjectPaths, batch_id: str) -> BatchOutcome:
    with connect_database(paths=paths) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*),
                count_if(api_status = 'SUCCESS'),
                count_if(api_status = 'NO_DATA'),
                count_if(api_status NOT IN ('SUCCESS', 'NO_DATA'))
            FROM raw.api_request
            WHERE batch_id = ?
            """,
            [batch_id],
        ).fetchone()
        assert row is not None
        request_count, success_count, no_data_count, failure_count = map(int, row)
        status = "COMPLETED" if failure_count == 0 else "COMPLETED_WITH_ERRORS"
        connection.execute(
            """
            UPDATE raw.collection_batch
            SET completed_at = ?, status = ?, request_count = ?, success_count = ?,
                no_data_count = ?, failure_count = ?
            WHERE batch_id = ?
            """,
            [
                utc_now(),
                status,
                request_count,
                success_count,
                no_data_count,
                failure_count,
                batch_id,
            ],
        )
    return BatchOutcome(
        batch_id=batch_id,
        request_count=request_count,
        success_count=success_count,
        no_data_count=no_data_count,
        failure_count=failure_count,
    )


def audit_batch(*, batch_id: str, paths: ProjectPaths | None = None) -> list[str]:
    """Recompute Raw integrity evidence and return human-readable violations."""
    project_paths = paths or ProjectPaths.from_root()
    issues: list[str] = []
    with connect_database(paths=project_paths, read_only=True) as connection:
        batch = connection.execute(
            "SELECT request_count FROM raw.collection_batch WHERE batch_id = ?", [batch_id]
        ).fetchone()
        if batch is None:
            return [f"UNKNOWN_BATCH:{batch_id}"]
        request_count_row = connection.execute(
            "SELECT COUNT(*) FROM raw.api_request WHERE batch_id = ?", [batch_id]
        ).fetchone()
        if request_count_row is None:
            return [f"REQUEST_COUNT_UNAVAILABLE:{batch_id}"]
        request_count = int(request_count_row[0])
        if int(batch[0]) != request_count:
            issues.append("BATCH_REQUEST_COUNT_MISMATCH")
        rows = connection.execute(
            """
            SELECT r.request_id, r.request_url_redacted, f.relative_path, f.sha256, f.size_bytes
            FROM raw.api_request r
            LEFT JOIN raw.raw_file f ON f.request_id = r.request_id
            WHERE r.batch_id = ?
            ORDER BY r.requested_at
            """,
            [batch_id],
        ).fetchall()

    for request_id, url, relative_path, expected_sha256, expected_size in rows:
        if "ServiceKey=REDACTED" not in str(url):
            issues.append(f"URL_NOT_REDACTED:{request_id}")
        if relative_path is None:
            continue
        raw_path = project_paths.root / str(relative_path)
        if not raw_path.is_file():
            issues.append(f"RAW_MISSING:{request_id}")
            continue
        content = raw_path.read_bytes()
        if len(content) != int(expected_size):
            issues.append(f"RAW_SIZE_MISMATCH:{request_id}")
        if sha256(content).hexdigest() != str(expected_sha256):
            issues.append(f"RAW_SHA256_MISMATCH:{request_id}")
    return issues


class Api43Collector:
    def __init__(
        self,
        *,
        paths: ProjectPaths | None = None,
        client: httpx.Client | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        self.paths = paths or ProjectPaths.from_root()
        self.page_size = page_size
        self._client = client
        self.logger = configure_logging()

    def collect(
        self, *, years: list[int], meets: list[int], all_pages: bool, page: int = 1
    ) -> BatchOutcome:
        if not years or any(year < 2000 or year > 2100 for year in years):
            raise ValueError("years must contain plausible four-digit years")
        if not meets or any(meet not in ALLOWED_MEETS for meet in meets):
            raise ValueError("meets must contain only 1 (Seoul) or 3 (Busan-Gyeongnam)")
        if page < 1:
            raise ValueError("page must be positive")

        initialize_database(paths=self.paths)
        api_key = get_api_key(self.paths)
        batch_id = f"{utc_now().strftime('%Y%m%dT%H%M%S%fZ')}_{API_NAME.lower()}_{uuid4().hex[:8]}"
        scope = {
            "years": years,
            "meets": meets,
            "page": page,
            "page_size": self.page_size,
            "all_pages": all_pages,
        }
        _insert_batch(paths=self.paths, batch_id=batch_id, scope=scope)

        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=30.0, transport=httpx.HTTPTransport(retries=2)
        )
        try:
            for year in years:
                for meet in meets:
                    first = self._collect_page(
                        client=client,
                        api_key=api_key,
                        batch_id=batch_id,
                        year=year,
                        meet=meet,
                        page=page,
                    )
                    if (
                        all_pages
                        and first.api_status == "SUCCESS"
                        and first.total_count is not None
                    ):
                        final_page = math.ceil(first.total_count / self.page_size)
                        for next_page in range(page + 1, final_page + 1):
                            outcome = self._collect_page(
                                client=client,
                                api_key=api_key,
                                batch_id=batch_id,
                                year=year,
                                meet=meet,
                                page=next_page,
                            )
                            if outcome.api_status in FAILURE_STATUSES:
                                break
        finally:
            if owns_client:
                client.close()
        return _complete_batch(paths=self.paths, batch_id=batch_id)

    def _collect_page(
        self,
        *,
        client: httpx.Client,
        api_key: str,
        batch_id: str,
        year: int,
        meet: int,
        page: int,
    ) -> RequestOutcome:
        request_id = str(uuid4())
        requested_at = utc_now()
        artifact: RawArtifact | None = None
        http_status: int | None = None
        try:
            response = client.get(
                BASE_URL,
                params=request_params(
                    api_key=api_key,
                    year=year,
                    meet=meet,
                    page=page,
                    page_size=self.page_size,
                ),
            )
            http_status = response.status_code
            content = response.content
            artifact = write_raw(
                content=content,
                paths=self.paths,
                year=year,
                meet=meet,
                page=page,
                request_id=request_id,
            )
            validation = validate_response(
                content=content,
                http_status=http_status,
                requested_year=year,
                requested_meet=meet,
            )
        except httpx.HTTPError as error:
            validation = ApiValidation("REQUEST_ERROR", None, None, 0, str(error))

        completed_at = utc_now()
        _record_request(
            paths=self.paths,
            batch_id=batch_id,
            request_id=request_id,
            year=year,
            meet=meet,
            page=page,
            page_size=self.page_size,
            requested_at=requested_at,
            completed_at=completed_at,
            http_status=http_status,
            validation=validation,
            artifact=artifact,
        )
        self.logger.info(
            "api=%s year=%d meet=%d page=%d status=%s items=%d",
            API_NAME,
            year,
            meet,
            page,
            validation.status,
            validation.item_count,
        )
        return RequestOutcome(
            request_id=request_id,
            api_status=validation.status,
            total_count=validation.total_count,
            item_count=validation.item_count,
            raw_artifact=artifact,
        )
