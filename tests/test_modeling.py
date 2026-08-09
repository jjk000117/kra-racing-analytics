from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from kra_analytics.feature_snapshot import MODEL_FEATURES
from kra_analytics.modeling import (
    AUDIT_ONLY_FEATURE,
    MODEL_INPUTS,
    assign_splits,
    calibration_intercept_slope,
    evaluate_probabilities,
    expanding_window_oof,
    validate_development_frame,
)


def _model_frame(months: int = 12) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    month_starts = pd.date_range("2024-10-01", periods=months, freq="MS")
    for month_number, month_start in enumerate(month_starts):
        for horse_number in range(4):
            row: dict[str, object] = {
                "race_id": f"R{month_number:02d}",
                "horse_id": f"H{horse_number}",
                "race_date": month_start.date(),
                "place_hit": horse_number == 0,
                "meet_code": 1 if month_number % 2 == 0 else 3,
                "race_grade": "국6등급",
                "horse_sex": "수",
            }
            for feature in MODEL_FEATURES:
                row.setdefault(feature, 1.0)
            row["horse_history_available"] = True
            row["jockey_history_available"] = True
            row["trainer_history_available"] = True
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame["split"] = assign_splits(frame)
    return frame


def test_model_input_contract_excludes_only_audit_hit_count() -> None:
    assert len(MODEL_FEATURES) == 29
    assert len(MODEL_INPUTS) == 28
    assert AUDIT_ONLY_FEATURE in MODEL_FEATURES
    assert AUDIT_ONLY_FEATURE not in MODEL_INPUTS
    assert "horse_prior_start_count" in MODEL_INPUTS
    assert "horse_prior_plc_hit_rate" in MODEL_INPUTS


def test_development_contract_rejects_final_test_rows() -> None:
    frame = _model_frame(1)
    frame.loc[:, "race_date"] = date(2026, 1, 1)
    frame.loc[:, "split"] = assign_splits(frame)

    with pytest.raises(ValueError, match="Final Test"):
        validate_development_frame(frame)


def test_expanding_window_oof_uses_strictly_prior_three_month_blocks() -> None:
    frame = _model_frame(12)

    predictions, folds = expanding_window_oof(frame)

    assert len(folds) == 3
    assert len(predictions) == 36
    assert [fold.prediction_start[:7] for fold in folds] == [
        "2025-01",
        "2025-04",
        "2025-07",
    ]
    assert all(fold.train_end < fold.prediction_start for fold in folds)
    assert [fold.train_rows for fold in folds] == [12, 24, 36]


def test_calibration_intercept_slope_has_explicit_logit_definition() -> None:
    probabilities = np.array([0.2] * 10 + [0.8] * 10)
    targets = np.array([1, 1] + [0] * 8 + [1] * 8 + [0, 0])

    intercept, slope = calibration_intercept_slope(targets, probabilities)

    assert intercept == pytest.approx(0.0, abs=1e-5)
    assert slope == pytest.approx(1.0, abs=1e-5)


def test_calibration_slope_is_undefined_for_constant_probabilities() -> None:
    targets = np.array([1, 0, 0, 0])

    intercept, slope = calibration_intercept_slope(targets, np.full(4, 0.25))

    assert intercept == pytest.approx(np.log(0.25 / 0.75))
    assert slope is None


def test_macro_metrics_give_each_race_equal_weight() -> None:
    frame = pd.DataFrame(
        {
            "race_id": ["R1", "R1", "R2", "R2", "R2", "R2"],
            "place_hit": [1, 0, 1, 0, 0, 0],
        }
    )
    probabilities = np.array([0.8, 0.2, 0.4, 0.4, 0.4, 0.4])

    result = evaluate_probabilities(frame, probabilities)

    race1_brier = ((0.8 - 1) ** 2 + (0.2 - 0) ** 2) / 2
    race2_brier = ((0.4 - 1) ** 2 + 3 * (0.4 - 0) ** 2) / 4
    assert result.macro_brier == pytest.approx((race1_brier + race2_brier) / 2)
    assert result.micro_brier != pytest.approx(result.macro_brier)
