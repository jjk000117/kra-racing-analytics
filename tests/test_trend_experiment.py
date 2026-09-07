from pathlib import Path

from kra_analytics.paths import ProjectPaths
from kra_analytics.trend_experiment import (
    CANDIDATES,
    EXPECTED_L133_HASH,
    _contracts,
    _decision,
)
from kra_analytics.trend_features import TREND_FEATURES


def test_t1_contract_adds_only_four_sealed_trend_features() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    contracts = _contracts(paths)
    assert tuple(contracts) == CANDIDATES
    assert len(contracts["L133"].inputs) == 133
    assert contracts["L133"].feature_hash == EXPECTED_L133_HASH
    assert len(contracts["LT1"].inputs) == 137
    assert contracts["LT1"].inputs[-4:] == tuple(TREND_FEATURES)
    assert len(set(contracts["LT1"].inputs)) == 137
    assert set(TREND_FEATURES).issubset(contracts["LT1"].numeric)
    assert not set(TREND_FEATURES).intersection(contracts["LT1"].zero_count)


def _summary(name: str, log_loss: float, brier: float) -> dict[str, float | str]:
    return {
        "experiment_id": name,
        "macro_log_loss_mean": log_loss,
        "macro_brier_mean": brier,
    }


def _delta(log_loss: float, brier: float) -> dict[str, float]:
    return {"delta_macro_log_loss": log_loss, "delta_macro_brier": brier}


def test_t1_decision_requires_repeated_improvement_in_both_primary_metrics() -> None:
    summaries = [_summary("L133", 0.53, 0.18), _summary("LT1", 0.52, 0.17)]
    assert (
        _decision(summaries, [_delta(-0.01, -0.01)] * 3 + [_delta(0.01, 0.01)])["judgement"]
        == "KEEP_T1"
    )
    assert (
        _decision(summaries, [_delta(-0.01, -0.01)] * 2 + [_delta(0.01, 0.01)] * 2)["judgement"]
        == "DROP_T1"
    )
