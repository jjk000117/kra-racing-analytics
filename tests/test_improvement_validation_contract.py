from pathlib import Path

from kra_analytics.improvement_validation_contract import (
    CONTRACT_PATH,
    EXPECTED_FEATURE_HASH,
    validate_improvement_validation_contract,
)
from kra_analytics.paths import ProjectPaths


def test_validation_contract_seals_candidate_without_access() -> None:
    root = Path(__file__).parents[1]
    paths = ProjectPaths.from_root(root)
    contract_path = paths.root / CONTRACT_PATH
    before = contract_path.read_bytes()
    contract = validate_improvement_validation_contract(paths)
    assert contract_path.read_bytes() == before
    candidate = contract["candidate"]
    assert candidate["total_feature_count"] == 133
    assert candidate["base_feature_count"] == 117
    assert candidate["f1_feature_count"] == 6
    assert candidate["f3_feature_count"] == 10
    assert candidate["feature_hash"] == EXPECTED_FEATURE_HASH
    assert contract["validation_access_budget"]["current_access_count"] == 0
    assert contract["date_contract"]["post_selection_access_allowed_now"] is False
    assert contract["calibration"]["other_calibration_methods_allowed"] is False
