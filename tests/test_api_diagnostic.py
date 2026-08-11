from __future__ import annotations

import json

from scripts.diagnose_kra_api_availability import _parse_json


def test_parse_json_accepts_string_error_body() -> None:
    content = json.dumps(
        {
            "response": {
                "header": {"resultCode": "99", "resultMsg": "application error"},
                "body": "error detail",
            }
        }
    ).encode()

    code, message, total_count, item_count = _parse_json(content)

    assert code == "99"
    assert message == "application error"
    assert total_count is None
    assert item_count == 0
