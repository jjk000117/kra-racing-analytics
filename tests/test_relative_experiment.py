from pathlib import Path

from kra_analytics.paths import ProjectPaths
from kra_analytics.relative_experiment import (
    EXPECTED_LR1_HASH,
    EXPECTED_R1_HASH,
    _contracts,
)


def test_r1_experiment_contract_is_exactly_lt1_plus_seven() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    contracts = _contracts(paths)
    assert len(contracts["LT1"].inputs) == 137
    assert len(contracts["LR1"].inputs) == 144
    assert contracts["LR1"].inputs[:137] == contracts["LT1"].inputs
    assert contracts["LR1"].feature_hash == EXPECTED_LR1_HASH
    assert len(EXPECTED_R1_HASH) == 64


def test_r1_experiment_keeps_model_and_preprocessing_family() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    contracts = _contracts(paths)
    assert contracts["LR1"].categorical == contracts["LT1"].categorical
    assert contracts["LR1"].zero_count == contracts["LT1"].zero_count
    assert len(contracts["LR1"].numeric) == len(contracts["LT1"].numeric) + 7
