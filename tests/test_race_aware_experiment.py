from __future__ import annotations

import numpy as np
import pandas as pd

from kra_analytics.race_aware_experiment import (
    build_pair_batch,
    decide_ra1,
    ranking_metrics,
)


def test_pair_batch_creates_reverse_pairs_and_equal_race_weights() -> None:
    frame = pd.DataFrame(
        {
            "race_id": ["r1"] * 4 + ["r2"] * 3,
            "horse_id": ["h1", "h2", "h3", "h4", "h5", "h6", "h7"],
            "place_hit": [1, 1, 0, 0, 1, 0, 0],
        }
    )
    matrix = np.arange(21, dtype=float).reshape(7, 3)
    batch = build_pair_batch(matrix, frame)
    assert batch.audit.directed_pairs == 12
    assert batch.audit.reverse_pair_violations == 0
    assert batch.audit.cross_race_pairs == 0
    assert batch.audit.race_weight_sum_min == 1.0
    assert batch.audit.race_weight_sum_max == 1.0
    dense = batch.differences.toarray()
    np.testing.assert_allclose(dense[0], -dense[1])
    assert batch.targets[:2].tolist() == [1, 0]


def test_pair_batch_excludes_single_label_race() -> None:
    frame = pd.DataFrame(
        {
            "race_id": ["r1", "r1", "r2", "r2"],
            "horse_id": ["a", "b", "c", "d"],
            "place_hit": [1, 0, 1, 1],
        }
    )
    batch = build_pair_batch(np.eye(4), frame)
    assert batch.audit.eligible_races == 1
    assert batch.audit.single_label_races == 1
    assert batch.audit.directed_pairs == 2


def test_ranking_metrics_use_deterministic_score_then_horse_order() -> None:
    frame = pd.DataFrame(
        {
            "race_id": ["r1"] * 4,
            "horse_id": ["b", "a", "c", "d"],
            "place_hit": [0, 1, 1, 0],
        }
    )
    result = ranking_metrics(frame, np.array([0.9, 0.9, 0.8, 0.1]))
    assert result["top1_plc_hit_rate"] == 1.0
    assert result["micro_recall_at_1"] == 0.5
    assert result["micro_recall_at_3"] == 1.0
    assert result["race_any_hit_at_2"] == 1.0


def _summary(
    model: str, ll: float, brier: float, ndcg: float, recall: float
) -> dict[str, float | str]:
    return {
        "model_id": model,
        "macro_log_loss_mean": ll,
        "macro_brier_mean": brier,
        "macro_ndcg_at_3_mean": ndcg,
        "micro_recall_at_3_mean": recall,
    }


def test_decide_ra1_promotes_only_when_all_strict_conditions_pass() -> None:
    summaries = [
        _summary("L133", 0.50, 0.17, 0.70, 0.50),
        _summary("RA1", 0.49, 0.16, 0.71, 0.51),
    ]
    deltas = [{"delta_macro_ndcg_at_3": 0.01, "delta_micro_recall_at_3": 0.01} for _ in range(4)]
    assert decide_ra1(summaries, deltas)["judgement"] == "PROMOTE_RACE_AWARE"


def test_decide_ra1_drops_when_ranking_mean_does_not_improve() -> None:
    summaries = [
        _summary("L133", 0.50, 0.17, 0.70, 0.50),
        _summary("RA1", 0.49, 0.16, 0.69, 0.51),
    ]
    deltas = [{"delta_macro_ndcg_at_3": -0.01, "delta_micro_recall_at_3": 0.01} for _ in range(4)]
    assert decide_ra1(summaries, deltas)["judgement"] == "DROP_RACE_AWARE"
