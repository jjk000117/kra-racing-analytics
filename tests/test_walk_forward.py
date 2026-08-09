from __future__ import annotations

from kra_analytics.walk_forward import (
    add_auxiliary_three_month_averages,
    evaluation_months,
)


def test_walk_forward_has_ten_monthly_folds() -> None:
    months = evaluation_months()

    assert len(months) == 10
    assert str(months[0]) == "2025-10"
    assert str(months[-1]) == "2026-07"
    assert [str(month) for month in months] == [
        "2025-10",
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
    ]


def test_three_month_average_is_auxiliary_and_requires_three_rows() -> None:
    rows = [
        {
            "model_macro_log_loss": value,
            "model_macro_brier": value / 2,
            "calibration_intercept": value / 10,
            "calibration_slope": 1 + value / 10,
        }
        for value in (0.3, 0.6, 0.9)
    ]

    add_auxiliary_three_month_averages(rows)

    assert rows[0]["auxiliary_3m_mean_model_macro_log_loss"] is None
    assert rows[1]["auxiliary_3m_mean_model_macro_log_loss"] is None
    assert rows[2]["auxiliary_3m_mean_model_macro_log_loss"] == 0.6
