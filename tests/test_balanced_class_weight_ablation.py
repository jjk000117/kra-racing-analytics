from __future__ import annotations

from typing import Any

import pandas as pd

from kra_analytics.balanced_class_weight_ablation import (
    BASELINE_NAME,
    CHALLENGER_NAME,
    FEATURE_HASH,
    class_balance,
    decide_balanced,
    feature_contract,
    load_ablation_contract,
    validate_upstream_evidence,
)
from kra_analytics.paths import ProjectPaths


def _summaries(ll_delta: float, brier_delta: float) -> list[dict[str, Any]]:
    return [
        {
            "candidate": BASELINE_NAME,
            "calibrated_macro_log_loss_mean": 0.53,
            "calibrated_macro_brier_mean": 0.18,
        },
        {
            "candidate": CHALLENGER_NAME,
            "calibrated_macro_log_loss_mean": 0.53 + ll_delta,
            "calibrated_macro_brier_mean": 0.18 + brier_delta,
        },
    ]


def _deltas(values: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [
        {
            "delta_calibrated_macro_log_loss": ll,
            "delta_calibrated_macro_brier": brier,
        }
        for ll, brier in values
    ]


def test_sealed_contract_and_upstream_hashes() -> None:
    paths = ProjectPaths.from_root()
    contract = load_ablation_contract(paths)
    validate_upstream_evidence(paths, contract)


def test_feature_contract_is_identical_137() -> None:
    contract = feature_contract(ProjectPaths.from_root())
    assert len(contract.inputs) == 137
    assert contract.feature_hash == FEATURE_HASH


def test_class_balance_uses_sklearn_balanced_formula() -> None:
    frame = pd.DataFrame({"place_hit": [0, 0, 0, 1]})
    balance = class_balance(frame)
    assert balance["positive_prevalence"] == 0.25
    assert balance["balanced_weight_negative"] == 4 / 6
    assert balance["balanced_weight_positive"] == 2.0


def test_keep_requires_both_means_and_three_joint_folds() -> None:
    decision = decide_balanced(
        _summaries(-0.001, -0.001),
        _deltas([(-0.1, -0.1), (-0.1, -0.1), (0.0, 0.0), (0.1, 0.1)]),
    )
    assert decision["judgement"] == "KEEP_BALANCED"


def test_drop_when_one_primary_mean_worsens() -> None:
    decision = decide_balanced(
        _summaries(-0.001, 0.001), _deltas([(-0.1, -0.1)] * 4)
    )
    assert decision["judgement"] == "DROP_BALANCED"
