from __future__ import annotations

import pandas as pd
import pytest

from kra_analytics.exploratory_betting_backtest import (
    _join_and_audit_settlement,
    longest_losing_streak,
    max_drawdown,
    select_top1,
    summarize_bets,
)


def test_select_top1_uses_probability_then_gate_then_horse() -> None:
    frame = pd.DataFrame(
        {
            "race_id": ["R1", "R1", "R2", "R2"],
            "horse_id": ["H2", "H1", "H4", "H3"],
            "race_date": ["2023-07-01"] * 4,
            "gate_no": [2, 1, 1, 1],
            "place_hit": [0, 1, 0, 1],
            "sigmoid_probability": [0.6, 0.6, 0.5, 0.5],
            "confirmed_odds": [float("nan"), 2.0, float("nan"), 1.8],
        }
    )
    selected = select_top1(frame)
    assert selected["horse_id"].tolist() == ["H1", "H3"]
    assert selected["gross_return"].tolist() == [2.0, 1.8]
    assert selected["profit"].tolist() == [1.0, 0.8]


def test_betting_summary_uses_one_unit_and_gross_odds_include_stake() -> None:
    bets = pd.DataFrame(
        {
            "race_id": ["R1", "R2", "R3"],
            "race_date": ["2023-07-01", "2023-07-02", "2023-07-03"],
            "place_hit": [1, 0, 1],
            "stake": [1.0, 1.0, 1.0],
            "confirmed_odds": [2.3, float("nan"), 1.5],
            "gross_return": [2.3, 0.0, 1.5],
            "profit": [1.3, -1.0, 0.5],
        }
    )
    summary = summarize_bets(bets)
    assert summary["total_stake"] == 3.0
    assert summary["gross_return"] == pytest.approx(3.8)
    assert summary["net_profit"] == pytest.approx(0.8)
    assert summary["roi"] == pytest.approx(0.8 / 3.0)


def test_risk_helpers() -> None:
    assert longest_losing_streak(pd.Series([0, 0, 1, 0, 0, 0, 1])) == 3
    assert max_drawdown(pd.Series([1.0, -1.0, -1.0, 2.0])) == pytest.approx(2.0)


def test_settlement_audit_fails_closed_at_race_level() -> None:
    predictions = pd.DataFrame(
        {
            "race_id": ["R1", "R1", "R2", "R2"],
            "horse_id": ["H1", "H2", "H3", "H4"],
            "gate_no": [1, 2, 1, 2],
            "place_hit": [1, 0, 1, 0],
            "sigmoid_probability": [0.6, 0.4, 0.7, 0.3],
        }
    )
    runner_odds = pd.DataFrame(
        {
            "race_id": ["R1", "R1", "R2", "R2"],
            "horse_id": ["H1", "H2", "H3", "H4"],
            "final_place_odds": [1.5, 2.0, 1.4, 2.5],
        }
    )
    payouts = pd.DataFrame(
        {
            "race_id": ["R1"],
            "gate_no": [1],
            "confirmed_odds": [1.5],
        }
    )
    eligible, audit = _join_and_audit_settlement(predictions, runner_odds, payouts)
    assert eligible["race_id"].unique().tolist() == ["R1"]
    assert audit["target_payout_mismatch_rows"] == 1
    assert audit["excluded_races"] == 1
