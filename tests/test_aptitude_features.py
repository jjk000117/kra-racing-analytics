from pathlib import Path

from kra_analytics.aptitude_features import (
    APTITUDE_FEATURES,
    _source_query,
    aptitude_feature_hash,
)
from kra_analytics.paths import ProjectPaths


def test_a1_registry_exactly_matches_seven_features() -> None:
    paths = ProjectPaths.from_root(Path(__file__).parents[1])
    assert len(APTITUDE_FEATURES) == len(set(APTITUDE_FEATURES)) == 7
    assert len(aptitude_feature_hash(paths)) == 64


def test_a1_sql_locks_pit_and_minimum_count_contract() -> None:
    sql = _source_query()
    assert sql.count("race_date<cur.feature_as_of") >= 3
    assert sql.count(">=3") >= 3
    assert "cur.distance_m-l.previous_distance_m" in sql
    assert "f.distance_m=cur.distance_m" in sql
