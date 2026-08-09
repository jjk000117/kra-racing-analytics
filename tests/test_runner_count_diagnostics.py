from __future__ import annotations

import pandas as pd
import pytest

from kra_analytics.runner_count_diagnostics import decompose_metric, summarize_segments


def test_symmetric_decomposition_reconciles_total_change() -> None:
    frame = pd.DataFrame(
        {
            "registered_runner_count": [8, 8, 10, 10, 8, 10, 10, 10],
            "period": ["STABLE"] * 4 + ["DEGRADED"] * 4,
            "log_loss": [0.4, 0.6, 0.5, 0.7, 0.7, 0.6, 0.8, 0.8],
            "brier": [0.1, 0.2, 0.2, 0.3, 0.3, 0.2, 0.3, 0.4],
        }
    )
    segments = summarize_segments(frame)

    result = decompose_metric(segments, "log_loss")

    assert result["total_change"] == pytest.approx(
        result["symmetric_composition_effect"]
        + result["symmetric_within_segment_effect"]
    )
    assert result["reconciliation_residual"] == pytest.approx(0.0, abs=1e-12)


def test_segment_summary_uses_race_shares() -> None:
    frame = pd.DataFrame(
        {
            "registered_runner_count": [8, 10, 8, 8],
            "period": ["STABLE", "STABLE", "DEGRADED", "DEGRADED"],
            "log_loss": [0.4, 0.6, 0.5, 0.7],
            "brier": [0.1, 0.2, 0.2, 0.3],
        }
    )

    segments = summarize_segments(frame)
    eight = next(row for row in segments if row["registered_runner_count"] == 8)

    assert eight["stable"]["share"] == 0.5
    assert eight["degraded"]["share"] == 1.0
