from __future__ import annotations

import pandas as pd

from kra_analytics.modeling_v2 import (
    EXCLUDED_LOGICAL,
    EXCLUDED_STRUCTURAL,
    POST_SELECTION_START,
    V2FeatureContract,
    choose_probability_procedure,
    expanding_temporal_oof_v2,
    load_feature_contract,
)
from kra_analytics.paths import ProjectPaths


def test_v2_inventory_has_exactly_117_inputs_and_no_exclusions() -> None:
    paths = ProjectPaths.from_root()
    contract = load_feature_contract(paths)

    assert len(contract.inputs) == 117
    assert not ((EXCLUDED_LOGICAL | EXCLUDED_STRUCTURAL) & set(contract.inputs))
    assert len(contract.feature_hash) == 64


def test_v2_oof_uses_strictly_prior_fold_training() -> None:
    inputs = ("numeric", "category")
    contract = V2FeatureContract(
        inputs=inputs,
        categorical=("category",),
        numeric=("numeric",),
        zero_count=(),
        feature_hash="dummy",
    )
    rows: list[dict[str, object]] = []
    for month_index, month in enumerate(pd.date_range("2023-01-01", periods=9, freq="MS")):
        for horse_index in range(6):
            rows.append(
                {
                    "race_id": f"R{month_index:02d}",
                    "horse_id": f"H{horse_index}",
                    "race_date": month.date(),
                    "numeric": float(month_index + horse_index),
                    "category": "A" if horse_index % 2 else "B",
                    "place_hit": horse_index < 2,
                }
            )
    frame = pd.DataFrame(rows)

    predictions, folds = expanding_temporal_oof_v2(frame, contract)

    assert len(predictions) == 36
    assert len(folds) == 2
    assert all(fold["train_end"] < fold["prediction_start"] for fold in folds)
    assert all(fold["preprocessing_fit_scope"] == "fold_train_only" for fold in folds)


def test_v2_selection_prefers_raw_unless_both_macro_metrics_improve() -> None:
    raw = {"macro_log_loss": 0.5, "macro_brier": 0.17}
    not_clear = {"macro_log_loss": 0.499, "macro_brier": 0.171}
    clear = {"macro_log_loss": 0.499, "macro_brier": 0.169}

    selected, _ = choose_probability_procedure(
        {"logistic_raw": raw, "logistic_sigmoid": not_clear}
    )
    assert selected == "logistic_raw"

    selected, _ = choose_probability_procedure(
        {"logistic_raw": raw, "logistic_sigmoid": clear}
    )
    assert selected == "logistic_sigmoid"


def test_post_selection_boundary_is_after_validation() -> None:
    assert str(POST_SELECTION_START) == "2025-07-01"
