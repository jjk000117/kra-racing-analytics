from decimal import Decimal

from kra_analytics.api4_semantics import (
    HorseWeight,
    TrackCondition,
    normalize_finish_sectional,
    parse_horse_weight,
    parse_race_time,
    parse_track,
)


def test_parse_race_time_preserves_tenth_seconds() -> None:
    assert parse_race_time("75.9") == Decimal("75.9")
    assert parse_race_time("0") == Decimal("0")
    assert parse_race_time("bad") is None


def test_parse_horse_weight_and_change() -> None:
    assert parse_horse_weight("502(-2)") == HorseWeight(502, -2)
    assert parse_horse_weight("388(+1)") == HorseWeight(388, 1)
    assert parse_horse_weight("480()") == HorseWeight(480, 0)
    assert parse_horse_weight("()") is None
    assert parse_horse_weight("502") is None


def test_parse_track_condition_and_moisture() -> None:
    assert parse_track("건조 (2%)") == TrackCondition("건조", 2)
    assert parse_track("다습(12%)") == TrackCondition("다습", 12)
    assert parse_track("  ") is None


def test_normalize_finish_sectional_uses_venue_specific_source() -> None:
    assert normalize_finish_sectional(
        meet_code=1,
        race_time=Decimal("72.4"),
        accumulated_time=Decimal("33.1"),
        direct_finish_time=None,
    ) == Decimal("39.3")
    assert normalize_finish_sectional(
        meet_code=3,
        race_time=Decimal("72.4"),
        accumulated_time=Decimal("33.1"),
        direct_finish_time=Decimal("39.3"),
    ) == Decimal("39.3")
    assert normalize_finish_sectional(
        meet_code=1,
        race_time=Decimal("30.0"),
        accumulated_time=Decimal("33.1"),
        direct_finish_time=None,
    ) is None
