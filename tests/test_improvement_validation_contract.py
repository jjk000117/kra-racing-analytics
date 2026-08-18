from pathlib import Path

from kra_analytics.improvement_validation_contract import (
    EXPECTED_FEATURE_HASH,
    build_improvement_validation_contract,
)
from kra_analytics.paths import ProjectPaths


def test_validation_contract_seals_candidate_without_access() -> None:
    root = Path(__file__).parents[1]
    paths = ProjectPaths.from_root(root)
    contract = build_improvement_validation_contract(paths)
    candidate = contract["candidate"]
    assert candidate["total_feature_count"] == 133
    assert candidate["base_feature_count"] == 117
    assert candidate["f1_feature_count"] == 6
    assert candidate["f3_feature_count"] == 10
    assert candidate["feature_hash"] == EXPECTED_FEATURE_HASH
    assert contract["validation_access_budget"]["current_access_count"] == 0
    assert contract["date_contract"]["post_selection_access_allowed_now"] is False
    assert contract["calibration"]["other_calibration_methods_allowed"] is False
