from __future__ import annotations

from typing import Any

import pandas as pd

from kra_analytics.near_constant_finish_rate_ablation import (
    CHALLENGER_HASH,
    CHALLENGER_NAME,
    REMOVED_FEATURES,
    candidate_contracts,
    decide_simplification,
    identify_flagged_finish_rates,
    load_ablation_contract,
    validate_diagnostic_evidence,
)
from kra_analytics.paths import ProjectPaths


def _summaries(ll_delta: float, brier_delta: float) -> list[dict[str, Any]]:
    return [
        {"candidate": "LR1", "macro_log_loss_mean": 0.53, "macro_brier_mean": 0.18},
        {
            "candidate": CHALLENGER_NAME,
            "macro_log_loss_mean": 0.53 + ll_delta,
            "macro_brier_mean": 0.18 + brier_delta,
        },
    ]


def _deltas(values: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"delta_macro_log_loss": ll, "delta_macro_brier": brier} for ll, brier in values]


def test_identification_requires_finish_rate_flag_and_threshold() -> None:
    profile = pd.DataFrame(
        [
            {
                "feature_name": "a_finish_rate",
                "near_constant_99pct_flag": True,
                "dominant_value_rate_non_null": 0.99,
            },
            {
                "feature_name": "b_finish_rate",
                "near_constant_99pct_flag": False,
                "dominant_value_rate_non_null": 0.999,
            },
            {
                "feature_name": "c_count",
                "near_constant_99pct_flag": True,
                "dominant_value_rate_non_null": 0.999,
            },
        ]
    )
    contract = pd.DataFrame(
        {"position": [3, 1, 2], "feature_name": ["c_count", "a_finish_rate", "b_finish_rate"]}
    )
    assert identify_flagged_finish_rates(profile, contract) == ("a_finish_rate",)


def test_sealed_diagnostics_identify_only_five_finish_rates() -> None:
    paths = ProjectPaths.from_root()
    payload = load_ablation_contract(paths)
    evidence = validate_diagnostic_evidence(paths, payload)
    assert set(evidence["identified_features"]) == set(REMOVED_FEATURES)
    assert len(evidence["profile"]) == 5


def test_sealed_contract_derives_only_five_removals() -> None:
    contracts = candidate_contracts(ProjectPaths.from_root())
    baseline = contracts["LR1"]
    challenger = contracts[CHALLENGER_NAME]
    assert len(baseline.inputs) == 144
    assert len(challenger.inputs) == 139
    assert challenger.feature_hash == CHALLENGER_HASH
    assert set(baseline.inputs) - set(challenger.inputs) == set(REMOVED_FEATURES)


def test_keep_requires_both_means_and_three_joint_folds() -> None:
    decision = decide_simplification(
        _summaries(-0.001, -0.001),
        _deltas([(-0.1, -0.1), (-0.1, -0.1), (0.0, 0.0), (0.1, 0.1)]),
    )
    assert decision["judgement"] == "KEEP_NEAR_CONSTANT_FINISH_RATE_SIMPLIFICATION"


def test_drop_when_a_primary_mean_worsens() -> None:
    decision = decide_simplification(_summaries(-0.001, 0.001), _deltas([(-0.1, -0.1)] * 4))
    assert decision["judgement"] == "DROP_NEAR_CONSTANT_FINISH_RATE_SIMPLIFICATION"
