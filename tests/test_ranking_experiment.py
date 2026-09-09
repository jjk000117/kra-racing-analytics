from __future__ import annotations

import pandas as pd
import pytest

from kra_analytics.ranking_experiment import decision, disagreement


def test_sealed_decision_requires_mean_three_folds_and_recall_guardrail() -> None:
    rows = []
    for fold, delta in zip(range(1, 5), [0.01, 0.01, 0.01, -0.01], strict=True):
        rows.extend(
            [
                {
                    "fold_id": f"fold_{fold}",
                    "model": "L133",
                    "macro_ndcg_at_3": 0.5,
                    "macro_recall_at_3": 0.5,
                },
                {
                    "fold_id": f"fold_{fold}",
                    "model": "LambdaRank",
                    "macro_ndcg_at_3": 0.5 + delta,
                    "macro_recall_at_3": 0.5,
                },
            ]
        )
    assert decision(pd.DataFrame(rows))["decision"] == "KEEP_RANKING_V1"
    rows[-1]["macro_recall_at_3"] = 0.45
    assert decision(pd.DataFrame(rows))["decision"] == "DROP_RANKING_V1"


def test_disagreement_four_way_counts_and_oracle_label() -> None:
    joined = pd.DataFrame(
        {
            "race_id": ["A"] * 3 + ["B"] * 3,
            "horse_id": ["1", "2", "3"] * 2,
            "race_date": ["2023-07-01"] * 6,
            "fold_id": ["fold_1"] * 6,
            "place_hit": [1, 0, 0, 0, 1, 0],
            "plc_within_race_rank": [1, 2, 3, 1, 2, 3],
            "ranking_within_race_rank": [2, 1, 3, 2, 1, 3],
        }
    )
    races, summary = disagreement(joined)
    assert races.top1_class.tolist() == ["plc_only", "ranking_only"]
    assert summary["top1"]["plc_only"]["races"] == 1
    assert summary["top1"]["ranking_only"]["races"] == 1
    assert summary["top1"]["oracle_descriptive_upper_bound"] == 1
    assert summary["oracle_caveat"].startswith("oracle descriptive upper bound")
    assert summary["mean_top3_same_set"] == 1


def test_decision_rejects_incomplete_fold_matrix() -> None:
    with pytest.raises(ValueError, match="INVALID"):
        decision(
            pd.DataFrame(
                [
                    {
                        "fold_id": "fold_1",
                        "model": "L133",
                        "macro_ndcg_at_3": 0.5,
                        "macro_recall_at_3": 0.5,
                    }
                ]
            )
        )
