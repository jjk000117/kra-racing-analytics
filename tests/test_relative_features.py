from pathlib import Path

import numpy as np
import pandas as pd

from kra_analytics.paths import ProjectPaths
from kra_analytics.relative_features import (
    RELATIVE_FEATURES,
    SOURCE_FEATURES,
    _source_query,
    average_rank_percentiles,
    relative_feature_hash,
)


def test_r1_registry_and_sql_contract() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    assert len(RELATIVE_FEATURES) == len(set(RELATIVE_FEATURES)) == 7
    assert len(SOURCE_FEATURES) == len(set(SOURCE_FEATURES)) == 7
    assert len(relative_feature_hash(paths)) == 64
    sql = _source_query().lower()
    assert "place_hit" not in sql
    assert "payout" not in sql
    assert "race_time_seconds" not in sql
    assert sql.count("count(") >= 7
    assert sql.count(">= 3") >= 7


def test_average_rank_percentile_ties_null_and_bounds() -> None:
    values = pd.Series([1.0, 2.0, 2.0, 4.0, np.nan, 8.0, 10.0])
    actual = average_rank_percentiles(values)
    expected = pd.Series([0.0, 0.3, 0.3, 0.6, np.nan, 0.8, 1.0])
    pd.testing.assert_series_equal(actual, expected)
    assert actual.dropna().between(0, 1).all()


def test_average_rank_percentile_two_runner_null_three_runner_available() -> None:
    two = average_rank_percentiles(pd.Series([1.0, 2.0, np.nan]))
    assert two.isna().all()
    three = average_rank_percentiles(pd.Series([1.0, 2.0, 3.0]))
    pd.testing.assert_series_equal(three, pd.Series([0.0, 0.5, 1.0]))


def test_average_rank_percentile_seven_runner_contract() -> None:
    actual = average_rank_percentiles(pd.Series([1, 2, 3, 4, 5, 6, 7]))
    assert actual.iloc[0] == 0.0
    assert actual.iloc[-1] == 1.0
    assert actual.iloc[3] == 0.5
