from pathlib import Path

from kra_analytics.feature_bundle_experiment import (
    BUNDLE_COUNT_FEATURES,
    BUNDLE_IDS,
    _candidate_contracts,
)
from kra_analytics.paths import ProjectPaths


def test_candidate_contracts_add_only_sealed_bundle_features() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    contracts = _candidate_contracts(paths)
    assert tuple(contracts) == BUNDLE_IDS
    assert [len(contracts[name].inputs) for name in BUNDLE_IDS] == [117, 123, 125, 127]
    assert len({contracts[name].feature_hash for name in BUNDLE_IDS}) == 4


def test_bundle_counts_use_zero_imputation_contract() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    contracts = _candidate_contracts(paths)
    assert BUNDLE_COUNT_FEATURES <= set(contracts["F1"].zero_count + contracts["F2"].zero_count)
