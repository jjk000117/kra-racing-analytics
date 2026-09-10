from __future__ import annotations

from typing import Any

from kra_analytics.paths import ProjectPaths
from kra_analytics.prize_bonus_ablation import (
    CHALLENGER_HASH,
    REMOVED_FEATURES,
    candidate_contracts,
    decide_simplification,
    load_ablation_contract,
)


def _summaries(ll_delta: float, brier_delta: float) -> list[dict[str, Any]]:
    return [
        {"candidate": "LR1", "macro_log_loss_mean": 0.53, "macro_brier_mean": 0.18},
        {
            "candidate": "LR1_PRIZE_BONUS_SIMPLIFIED",
            "macro_log_loss_mean": 0.53 + ll_delta,
            "macro_brier_mean": 0.18 + brier_delta,
        },
    ]


def _deltas(values: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [
        {"delta_macro_log_loss": ll, "delta_macro_brier": brier}
        for ll, brier in values
    ]


def test_keep_requires_both_mean_non_worse_and_three_stable_folds() -> None:
    decision = decide_simplification(
        _summaries(-0.001, -0.001),
        _deltas([(-0.1, -0.1), (-0.1, -0.1), (0.0, 0.0), (0.1, 0.1)]),
    )
    assert decision["judgement"] == "KEEP_PRIZE_BONUS_SIMPLIFICATION"


def test_drop_when_only_two_folds_are_jointly_non_worse() -> None:
    decision = decide_simplification(
        _summaries(-0.001, -0.001),
        _deltas([(-0.1, -0.1), (-0.1, -0.1), (0.1, -0.1), (-0.1, 0.1)]),
    )
    assert decision["judgement"] == "DROP_PRIZE_BONUS_SIMPLIFICATION"


def test_drop_when_a_primary_mean_worsens() -> None:
    decision = decide_simplification(
        _summaries(-0.001, 0.001),
        _deltas([(-0.1, -0.1)] * 4),
    )
    assert decision["judgement"] == "DROP_PRIZE_BONUS_SIMPLIFICATION"


def test_sealed_contract_derives_only_the_six_removals() -> None:
    paths = ProjectPaths.from_root()
    payload = load_ablation_contract(paths)
    contracts = candidate_contracts(paths)
    baseline = contracts["LR1"]
    challenger = contracts["LR1_PRIZE_BONUS_SIMPLIFIED"]

    assert len(baseline.inputs) == 144
    assert len(challenger.inputs) == 138
    assert challenger.feature_hash == CHALLENGER_HASH
    assert set(baseline.inputs) - set(challenger.inputs) == set(REMOVED_FEATURES)
    assert payload["scope"]["validation_access_allowed"] is False
