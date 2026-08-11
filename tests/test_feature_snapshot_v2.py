from pathlib import Path

from kra_analytics.feature_snapshot_v2 import _build_sql, registry_feature_names


def test_v2_registry_has_125_unique_immediate_features() -> None:
    root = Path(__file__).parents[1]
    features = registry_feature_names(root)

    assert len(features) == 125
    assert len(set(features)) == 125
    for horizon in (3, 5):
        assert f"horse_recent{horizon}_g3f_count" in features
        assert f"horse_recent{horizon}_g1f_count" in features


def test_v2_sql_enforces_strict_historical_date_and_excludes_current_results() -> None:
    sql = _build_sql()

    assert "hist.race_date < cur.race_date" in sql
    assert "h.race_date < cur.race_date" in sql
    assert "current_finish_rank" not in sql
    assert "current_race_time" not in sql
    assert "current_win_odds" not in sql
    assert "current_place_odds" not in sql
