from __future__ import annotations

from typing import Any

import pandas as pd

from kra_analytics.exact_count_ablation import (
    CHALLENGER_HASH,
    CHALLENGER_NAME,
    REMOVED_FEATURES,
    SEALED_GROUPS,
    candidate_contracts,
    decide_simplification,
    exact_duplicate_components,
    load_ablation_contract,
    reconstruct_exact_groups,
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


def test_exact_components_require_value_and_null_identity() -> None:
    pairs = pd.DataFrame(
        [
            {
                "feature_left": "a_count",
                "feature_right": "b_count",
                "exact_value_and_null_pattern": True,
            },
            {
                "feature_left": "b_count",
                "feature_right": "c_count",
                "exact_value_and_null_pattern": True,
            },
            {
                "feature_left": "c_count",
                "feature_right": "d_count",
                "exact_value_and_null_pattern": False,
            },
        ]
    )
    contract = pd.DataFrame(
        {
            "feature_name": ["a_count", "b_count", "c_count", "d_count"],
            "feature_type": ["numeric"] * 4,
        }
    )
    assert exact_duplicate_components(pairs, contract) == (("a_count", "b_count", "c_count"),)


def test_sealed_diagnostic_artifacts_reconstruct_three_groups() -> None:
    paths = ProjectPaths.from_root()
    payload = load_ablation_contract(paths)
    result = reconstruct_exact_groups(paths, payload)
    assert tuple(tuple(group) for group in result["groups"]) == tuple(sorted(SEALED_GROUPS))
    assert result["exact_pair_rows"] == 13


def test_sealed_contract_derives_only_exact_count_removals() -> None:
    paths = ProjectPaths.from_root()
    contracts = candidate_contracts(paths)
    baseline = contracts["LR1"]
    challenger = contracts[CHALLENGER_NAME]
    assert len(baseline.inputs) == 144
    assert len(challenger.inputs) == 137
    assert challenger.feature_hash == CHALLENGER_HASH
    assert set(baseline.inputs) - set(challenger.inputs) == set(REMOVED_FEATURES)


def test_keep_requires_both_means_and_three_joint_folds() -> None:
    decision = decide_simplification(
        _summaries(-0.001, -0.001),
        _deltas([(-0.1, -0.1), (-0.1, -0.1), (0.0, 0.0), (0.1, 0.1)]),
    )
    assert decision["judgement"] == "KEEP_EXACT_COUNT_SIMPLIFICATION"


def test_drop_when_a_primary_mean_worsens() -> None:
    decision = decide_simplification(_summaries(-0.001, 0.001), _deltas([(-0.1, -0.1)] * 4))
    assert decision["judgement"] == "DROP_EXACT_COUNT_SIMPLIFICATION"
