from pathlib import Path

import pytest

from kra_analytics.improvement_validation import (
    EXPECTED_CONTRACT_SHA256,
    _preflight,
)
from kra_analytics.paths import ProjectPaths


def test_validation_preflight_does_not_consume_access() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    access_path = paths.root / (
        "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/"
        "validation_access.json"
    )
    if access_path.exists():
        pytest.skip("One-time access was already consumed by the real execution")
    contract, checks = _preflight(paths)
    assert checks["contract_sha256"] == EXPECTED_CONTRACT_SHA256
    assert checks["feature_count"] == 133
    assert checks["validation_access_count_before"] == 0
    assert contract["status"] == "SEALED_BEFORE_ONE_TIME_VALIDATION"
    assert not access_path.exists()
