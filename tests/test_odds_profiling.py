from __future__ import annotations

import pandas as pd
import pytest

from kra_analytics.odds_profiling import parse_confirmed_odds_raw, profile_confirmed_odds


def test_parse_multiple_payouts_and_horse_16() -> None:
    items = parse_confirmed_odds_raw("복연", "(16)⑪-18.8  (16)⑦-46.9  ⑪⑦-56.9")
    assert len(items) == 3
    assert items[0].horse_tokens == ("(16)", "⑪")
    assert items[0].confirmed_odds == 18.8


def test_profile_preserves_order_only_for_ordered_pool() -> None:
    source = pd.DataFrame(
        [
            {"sales_id": "qnl", "race_id": "r1", "pool_code": "복식", "confirmed_odds_raw": "③①-7"},
            {"sales_id": "exa", "race_id": "r1", "pool_code": "쌍식", "confirmed_odds_raw": "③①-9"},
        ]
    )
    parsed, issues = profile_confirmed_odds(source)
    assert issues.empty
    assert parsed.loc[0, "horse_numbers_canonical"] == (1, 3)
    assert parsed.loc[1, "horse_numbers_canonical"] == (3, 1)


def test_parse_rejects_wrong_selection_count() -> None:
    with pytest.raises(ValueError, match="Expected 2 selections"):
        parse_confirmed_odds_raw("복식", "①-2.3")
