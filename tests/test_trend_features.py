from pathlib import Path

import pytest

from kra_analytics.paths import ProjectPaths
from kra_analytics.trend_features import TREND_FEATURES, sequence_slope, trend_feature_hash


def test_t1_registry_exactly_matches_four_implementation_features() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    assert len(TREND_FEATURES) == len(set(TREND_FEATURES)) == 4
    assert len(trend_feature_hash(paths)) == 64


def test_sequence_slope_requires_three_observations() -> None:
    assert sequence_slope([]) is None
    assert sequence_slope([1.0, 2.0]) is None


def test_sequence_slope_direction_and_flat_values() -> None:
    assert sequence_slope([0.1, 0.2, 0.3]) == pytest.approx(0.1)
    assert sequence_slope([0.3, 0.2, 0.1]) == pytest.approx(-0.1)
    assert sequence_slope([2.0, 2.0, 2.0, 2.0]) == pytest.approx(0.0)


def test_sectional_improvement_is_negative_raw_seconds_slope() -> None:
    improving_seconds = [14.0, 13.8, 13.6]
    worsening_seconds = [13.6, 13.8, 14.0]
    assert -sequence_slope(improving_seconds) > 0  # type: ignore[operator]
    assert -sequence_slope(worsening_seconds) < 0  # type: ignore[operator]
