from __future__ import annotations

import pandas as pd

from kra_analytics.logistic_structure_diagnostics import (
    _group_summary,
    _safe_quantile_bin,
)


def test_safe_quantile_bin_preserves_missing_and_bounds() -> None:
    values = pd.Series([1.0, 2.0, 3.0, 4.0, None])
    result = _safe_quantile_bin(values, bins=4)
    assert result.dropna().between(1, 4).all()
    assert pd.isna(result.iloc[-1])


def test_group_summary_uses_runner_residual_definition() -> None:
    frame = pd.DataFrame(
        {
            "fold_id": ["fold_1", "fold_1"],
            "race_id": ["r1", "r1"],
            "target": [1, 0],
            "prediction": [0.8, 0.3],
            "residual": [0.2, -0.3],
            "squared_error": [0.04, 0.09],
        }
    )
    result = _group_summary(frame, ["fold_id"])
    assert result.loc[0, "rows"] == 2
    assert result.loc[0, "races"] == 1
    assert abs(result.loc[0, "mean_residual"] + 0.05) < 1e-12
    assert abs(result.loc[0, "mean_brier"] - 0.065) < 1e-12
