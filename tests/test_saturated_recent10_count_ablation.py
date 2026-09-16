from __future__ import annotations

from typing import Any

import pandas as pd

from kra_analytics.paths import ProjectPaths
from kra_analytics.saturated_recent10_count_ablation import (
    BASELINE_NAME,
    CHALLENGER_HASH,
    CHALLENGER_NAME,
    REMOVED_FEATURES,
    candidate_contracts,
    decide_simplification,
    identify_saturated_recent10_counts,
    load_ablation_contract,
    validate_diagnostic_evidence,
)


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
    return [{"delta_macro_log_loss": ll, "delta_macro_brier": brier} for ll, brier in values]


def test_identification_requires_named_flagged_counts_at_cap() -> None:
    profile = pd.DataFrame(
        [
            {
                "feature_name": "jockey_recent10_start_count",
                "near_constant_99pct_flag": True,
                "dominant_value_rate_non_null": 0.995,
                "median": 10,
            },
            {
                "feature_name": "trainer_recent10_start_count",
                "near_constant_99pct_flag": False,
                "dominant_value_rate_non_null": 0.999,
                "median": 10,
            },
            {
                "feature_name": "other_recent10_start_count",
                "near_constant_99pct_flag": True,
                "dominant_value_rate_non_null": 0.999,
                "median": 10,
            },
        ]
    )
    contract = pd.DataFrame({"position": [1, 2, 3], "feature_name": profile["feature_name"]})
    assert identify_saturated_recent10_counts(profile, contract) == ("jockey_recent10_start_count",)


def test_sealed_diagnostics_identify_two_counts() -> None:
    paths = ProjectPaths.from_root()
    evidence = validate_diagnostic_evidence(paths, load_ablation_contract(paths))
    assert set(evidence["identified_features"]) == set(REMOVED_FEATURES)
    assert len(evidence["profile"]) == 2


def test_sealed_contract_derives_137_from_kept_139() -> None:
    contracts = candidate_contracts(ProjectPaths.from_root())
    baseline = contracts[BASELINE_NAME]
    challenger = contracts[CHALLENGER_NAME]
    assert len(baseline.inputs) == 139
    assert len(challenger.inputs) == 137
    assert challenger.feature_hash == CHALLENGER_HASH
    assert set(baseline.inputs) - set(challenger.inputs) == set(REMOVED_FEATURES)


def test_keep_requires_both_means_and_three_joint_folds() -> None:
    decision = decide_simplification(
        _summaries(-0.001, -0.001),
        _deltas([(-0.1, -0.1), (-0.1, -0.1), (0.0, 0.0), (0.1, 0.1)]),
    )
    assert decision["judgement"] == "KEEP_SATURATED_RECENT10_COUNT_SIMPLIFICATION"


def test_drop_when_a_primary_mean_worsens() -> None:
    decision = decide_simplification(_summaries(-0.001, 0.001), _deltas([(-0.1, -0.1)] * 4))
    assert decision["judgement"] == "DROP_SATURATED_RECENT10_COUNT_SIMPLIFICATION"
