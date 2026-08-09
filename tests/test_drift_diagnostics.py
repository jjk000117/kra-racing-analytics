from __future__ import annotations

import pandas as pd
import pytest

from kra_analytics.drift_diagnostics import summarize_categorical, summarize_numeric


def test_numeric_summary_preserves_quantiles_and_null_rate() -> None:
    frame = pd.DataFrame(
        {
            "period": ["STABLE", "STABLE", "DEGRADED", "DEGRADED"],
            "value": [1.0, None, 2.0, 4.0],
        }
    )

    result = summarize_numeric(frame, ("value",))[0]

    assert result["stable"]["p50"] == 1.0
    assert result["degraded"]["p50"] == 3.0
    assert result["stable"]["null_rate"] == 0.5
    assert result["degraded_minus_stable"]["p50"] == 2.0


def test_categorical_summary_reports_percentage_point_change() -> None:
    frame = pd.DataFrame(
        {
            "period": ["STABLE", "STABLE", "DEGRADED", "DEGRADED"],
            "category": ["A", "B", "A", "A"],
        }
    )

    result = summarize_categorical(frame, ("category",), grain="RACE")
    category_a = next(row for row in result if row["category"] == "A")

    assert category_a["stable"]["share"] == 0.5
    assert category_a["degraded"]["share"] == 1.0
    assert category_a["share_change_percentage_points"] == pytest.approx(50.0)
