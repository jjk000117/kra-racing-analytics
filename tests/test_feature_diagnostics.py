from __future__ import annotations

import numpy as np
import pandas as pd

from kra_analytics.feature_diagnostics import (
    categorical_profile,
    corrected_cramers_v,
    correlation_components,
    high_correlation_pairs,
    numeric_profile,
)


def test_numeric_profile_distinguishes_zero_missing_and_near_constant() -> None:
    frame = pd.DataFrame({"value": [0.0] * 99 + [1.0, np.nan]})
    result = numeric_profile(frame, ("value",)).iloc[0]

    assert result["missing_count"] == 1
    assert result["zero_count"] == 99
    assert result["unique_count"] == 2
    assert bool(result["near_constant_99pct_flag"])


def test_categorical_profile_records_dominance_and_rare_categories() -> None:
    frame = pd.DataFrame({"category": ["A"] * 100 + ["B", None]})
    result = categorical_profile(frame, ("category",)).iloc[0]

    assert result["missing_count"] == 1
    assert result["unique_count"] == 2
    assert result["rare_category_count_lt_1pct"] == 1


def test_corrected_cramers_v_and_correlation_components() -> None:
    left = pd.Series(["A", "A", "B", "B"] * 50)
    right = pd.Series(["X", "X", "Y", "Y"] * 50)
    value, observations = corrected_cramers_v(left, right)
    assert observations == 200
    assert value > 0.99

    pearson = pd.DataFrame(
        [[1.0, 0.95, 0.1], [0.95, 1.0, 0.2], [0.1, 0.2, 1.0]],
        index=["a", "b", "c"],
        columns=["a", "b", "c"],
    )
    pairs = high_correlation_pairs(pearson, pearson)
    components = correlation_components(pairs)
    assert set(components["feature_name"]) == {"a", "b"}
