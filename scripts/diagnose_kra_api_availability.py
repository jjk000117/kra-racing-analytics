from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from argparse import ArgumentParser
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv

from kra_analytics.logging import safe_exception_message

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DiagnosticResult:
    api_name: str
    endpoint: str
    operation: str
    http_status: int | None
    response_format: str | None
    elapsed_seconds: float
    result_code: str | None
    result_message: str | None
    total_count: int | None
    item_count: int | None
    data_returned: bool
    failure_layer: str
    error: str | None = None


def _parse_json(content: bytes) -> tuple[str | None, str | None, int | None, int | None]:
    document = json.loads(content)
    if not isinstance(document, dict):
        raise TypeError("JSON root is not an object")
    response = document.get("response", document)
    if not isinstance(response, dict):
        raise TypeError("response is not an object")
    header = response.get("header", {})
    body = response.get("body", {})
    if not isinstance(header, dict):
        header = {}
    if not isinstance(body, dict):
        body = {}
    items = body.get("items", {})
    raw_items = items.get("item", []) if isinstance(items, dict) else items
    if isinstance(raw_items, dict):
        item_count = 1
    elif isinstance(raw_items, list):
        item_count = len(raw_items)
    else:
        item_count = 0
    total = body.get("totalCount")
    return (
        str(header.get("resultCode")) if header.get("resultCode") is not None else None,
        str(header.get("resultMsg")) if header.get("resultMsg") is not None else None,
        int(total) if total is not None and str(total).isdigit() else None,
        item_count,
    )


def _parse_xml(content: bytes) -> tuple[str | None, str | None, int | None, int | None]:
    root = ET.fromstring(content)
    code = root.findtext(".//resultCode")
    message = root.findtext(".//resultMsg")
    total_text = root.findtext(".//totalCount")
    total = int(total_text) if total_text and total_text.isdigit() else None
    return code, message, total, len(root.findall(".//item"))


def call_once(
    *,
    client: httpx.Client,
    api_name: str,
    endpoint: str,
    operation: str,
    params: dict[str, str],
    api_key: str,
) -> DiagnosticResult:
    started = time.perf_counter()
    try:
        response = client.get(endpoint, params=params)
        elapsed = time.perf_counter() - started
        content = response.content
        stripped = content.lstrip()
        response_format = "JSON" if stripped.startswith((b"{", b"[")) else "XML"
        try:
            parsed = _parse_json(content) if response_format == "JSON" else _parse_xml(content)
            result_code, result_message, total_count, item_count = parsed
        except (
            AttributeError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            ET.ParseError,
        ) as error:
            return DiagnosticResult(
                api_name,
                endpoint,
                operation,
                response.status_code,
                response_format,
                round(elapsed, 3),
                None,
                None,
                None,
                None,
                False,
                "RESPONSE_PARSE",
                safe_exception_message(error, secrets=(api_key,)),
            )
        success_code = result_code in {"00", "0", "NORMAL_SERVICE"}
        failure_layer = (
            "HTTP" if not 200 <= response.status_code < 300 else
            "NONE" if success_code else
            "API_APPLICATION"
        )
        return DiagnosticResult(
            api_name,
            endpoint,
            operation,
            response.status_code,
            response_format,
            round(elapsed, 3),
            result_code,
            result_message,
            total_count,
            item_count,
            bool(success_code and item_count),
            failure_layer,
        )
    except httpx.HTTPError as error:
        return DiagnosticResult(
            api_name,
            endpoint,
            operation,
            None,
            None,
            round(time.perf_counter() - started, 3),
            None,
            None,
            None,
            None,
            False,
            "TRANSPORT",
            safe_exception_message(error, secrets=(api_key,)),
        )


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument(
        "--apis",
        nargs="+",
        choices=("API4_3", "API156", "API155"),
        default=("API4_3", "API156", "API155"),
    )
    selected = set(parser.parse_args().apis)
    load_dotenv(ROOT / ".env", override=False)
    api_key = os.getenv("KRA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("KRA_API_KEY is not configured")

    calls: list[tuple[str, str, str, str, dict[str, str]]] = [
        (
            "API4_3",
            "한국마사회 경주기록 정보",
            "https://apis.data.go.kr/B551015/API4_3/raceResult_3",
            "GET /raceResult_3",
            {"meet": "1", "rc_year": "2022"},
        ),
        (
            "API156",
            "한국마사회 AI기반연구용 경주결과상세",
            "https://apis.data.go.kr/B551015/API156/raceRsutDtl",
            "GET /raceRsutDtl",
            {},
        ),
        (
            "API155",
            "한국마사회 AI학습용 경주결과",
            "https://apis.data.go.kr/B551015/API155/raceResult",
            "GET /raceResult",
            {"rccrs_cd": "1", "race_dt": "20220108"},
        ),
    ]
    common = {"ServiceKey": api_key, "pageNo": "1", "numOfRows": "1", "_type": "json"}
    with httpx.Client(timeout=30.0, transport=httpx.HTTPTransport(retries=0)) as client:
        results = [
            call_once(
                client=client,
                api_name=name,
                endpoint=endpoint,
                operation=operation,
                params={**common, **specific},
                api_key=api_key,
            )
            for code, name, endpoint, operation, specific in calls
            if code in selected
        ]
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
