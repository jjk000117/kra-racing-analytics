from __future__ import annotations

from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.h133_experiment import H133_SETTINGS, decide_h133, validate_h133_contract
from kra_analytics.paths import ProjectPaths


def test_h133_contract_is_the_promoted_133_feature_set() -> None:
    paths = ProjectPaths.from_root()
    contract = _combined_contract(paths)["F1+F3"]
    audit = validate_h133_contract(contract)
    assert audit["feature_count"] == 133
    assert audit["categorical_count"] == 11
    assert audit["numeric_count"] == 122
    assert H133_SETTINGS["max_leaf_nodes"] == 15
    assert H133_SETTINGS["l2_regularization"] == 1.0


def test_h133_decision_requires_both_macro_metrics_and_three_folds() -> None:
    summaries = [
        {"model_id": "L133", "macro_log_loss_mean": 0.53, "macro_brier_mean": 0.18},
        {"model_id": "H133", "macro_log_loss_mean": 0.52, "macro_brier_mean": 0.17},
    ]
    deltas = [
        {"delta_macro_log_loss": -0.01, "delta_macro_brier": -0.01},
        {"delta_macro_log_loss": -0.01, "delta_macro_brier": -0.01},
        {"delta_macro_log_loss": -0.01, "delta_macro_brier": -0.01},
        {"delta_macro_log_loss": 0.01, "delta_macro_brier": 0.01},
    ]
    assert decide_h133(summaries, deltas)["judgement"] == "KEEP_NONLINEAR"

    deltas[2]["delta_macro_brier"] = 0.01
    assert decide_h133(summaries, deltas)["judgement"] == "MIXED"
