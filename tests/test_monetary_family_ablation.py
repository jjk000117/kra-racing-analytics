from __future__ import annotations

from typing import Any

from kra_analytics.monetary_family_ablation import (
    BASELINE_NAME,
    CHALLENGER_HASH,
    CHALLENGER_NAME,
    REMOVED_FEATURES,
    REQUIRED_RETAINED_FEATURES,
    candidate_contracts,
    decide_simplification,
    load_ablation_contract,
    validate_upstream_evidence,
)
from kra_analytics.paths import ProjectPaths


def _summaries(ll_delta: float, brier_delta: float) -> list[dict[str, Any]]:
    return [
        {"candidate": BASELINE_NAME, "macro_log_loss_mean": 0.53, "macro_brier_mean": 0.18},
        {
            "candidate": CHALLENGER_NAME,
            "macro_log_loss_mean": 0.53 + ll_delta,
            "macro_brier_mean": 0.18 + brier_delta,
        },
    ]


def _deltas(values: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [
        {"delta_macro_log_loss": ll, "delta_macro_brier": brier}
        for ll, brier in values
    ]


def test_sealed_contract_and_upstream_hashes() -> None:
    paths = ProjectPaths.from_root()
    contract = load_ablation_contract(paths)
    validate_upstream_evidence(paths, contract)


def test_sealed_contract_derives_129_from_kept_137() -> None:
    contracts = candidate_contracts(ProjectPaths.from_root())
    baseline = contracts[BASELINE_NAME]
    challenger = contracts[CHALLENGER_NAME]
    assert len(baseline.inputs) == 137
    assert len(challenger.inputs) == 129
    assert challenger.feature_hash == CHALLENGER_HASH
    assert set(baseline.inputs) - set(challenger.inputs) == set(REMOVED_FEATURES)
    assert set(REQUIRED_RETAINED_FEATURES).issubset(challenger.inputs)


def test_keep_requires_both_means_and_three_joint_folds() -> None:
    decision = decide_simplification(
        _summaries(-0.001, -0.001),
        _deltas([(-0.1, -0.1), (-0.1, -0.1), (0.0, 0.0), (0.1, 0.1)]),
    )
    assert decision["judgement"] == "KEEP_MONETARY_FAMILY_REMOVAL"


def test_drop_when_a_primary_mean_worsens() -> None:
    decision = decide_simplification(
        _summaries(-0.001, 0.001), _deltas([(-0.1, -0.1)] * 4)
    )
    assert decision["judgement"] == "DROP_MONETARY_FAMILY_REMOVAL"
