from pathlib import Path

from kra_analytics.aptitude_experiment import (
    COUNT_FEATURES,
    EXPECTED_A1_HASH,
    EXPECTED_LT1_HASH,
    _contracts,
)
from kra_analytics.aptitude_features import APTITUDE_FEATURES, aptitude_feature_hash
from kra_analytics.paths import ProjectPaths


def test_la1_contract_adds_only_sealed_a1() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    contracts = _contracts(paths)
    assert contracts["LT1"].feature_hash == EXPECTED_LT1_HASH
    assert aptitude_feature_hash(paths) == EXPECTED_A1_HASH
    assert contracts["LA1"].inputs == contracts["LT1"].inputs + APTITUDE_FEATURES
    assert len(contracts["LA1"].inputs) == len(set(contracts["LA1"].inputs)) == 144
    assert set(COUNT_FEATURES) <= set(contracts["LA1"].zero_count)
