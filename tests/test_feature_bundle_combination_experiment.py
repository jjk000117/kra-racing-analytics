from pathlib import Path

from kra_analytics.feature_bundle_combination_experiment import (
    CANDIDATES,
    _combined_contract,
)
from kra_analytics.paths import ProjectPaths


def test_combination_contract_adds_only_f1_and_f3() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    contracts = _combined_contract(paths)
    assert tuple(contracts) == CANDIDATES
    assert [len(contracts[name].inputs) for name in CANDIDATES] == [117, 123, 127, 133]
    assert len(set(contracts["F1+F3"].inputs)) == 133
    assert len(contracts["F1+F3"].zero_count) == len(contracts["F1"].zero_count)
