from pathlib import Path

from kra_analytics.feature_bundles import (
    ALL_BUNDLE_FEATURES,
    F1_FEATURES,
    F2_FEATURES,
    F3_FEATURES,
    bundle_feature_hash,
)
from kra_analytics.paths import ProjectPaths


def test_sealed_bundle_feature_counts_and_names() -> None:
    assert len(F1_FEATURES) == 6
    assert len(F2_FEATURES) == 8
    assert len(F3_FEATURES) == 10
    assert len(ALL_BUNDLE_FEATURES) == len(set(ALL_BUNDLE_FEATURES)) == 24
    assert not any("best" in name or "rank" in name for name in ALL_BUNDLE_FEATURES)


def test_registry_exactly_matches_implementation() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    assert len(bundle_feature_hash(paths)) == 64
