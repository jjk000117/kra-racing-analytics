from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

SEMANTIC_VERSION = "api4_runner_event_v2"

HORSE_WEIGHT_PATTERN = re.compile(r"^\s*(\d{2,3})\s*\(\s*([+-]?\d*)\s*\)\s*$")
TRACK_PATTERN = re.compile(r"^\s*(.*?)\s*(?:\(\s*(\d+)\s*%\s*\))?\s*$")


@dataclass(frozen=True)
class HorseWeight:
    weight_kg: int
    change_kg: int


@dataclass(frozen=True)
class TrackCondition:
    condition: str
    moisture_percent: int | None


def parse_race_time(value: str | None) -> Decimal | None:
    """Parse API4 elapsed seconds without losing the source's tenth-second precision."""
    if value is None or not value.strip():
        return None
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation:
        return None
    return parsed if parsed >= 0 else None


def parse_horse_weight(value: str | None) -> HorseWeight | None:
    """Parse API4 weight and its change; weighted empty parentheses mean zero."""
    if value is None:
        return None
    match = HORSE_WEIGHT_PATTERN.fullmatch(value)
    if match is None:
        return None
    change = int(match.group(2)) if match.group(2) else 0
    return HorseWeight(weight_kg=int(match.group(1)), change_kg=change)


def parse_track(value: str | None) -> TrackCondition | None:
    """Split track label and optional moisture percentage."""
    if value is None or not value.strip():
        return None
    match = TRACK_PATTERN.fullmatch(value)
    if match is None or not match.group(1).strip():
        return None
    moisture = int(match.group(2)) if match.group(2) is not None else None
    return TrackCondition(match.group(1).strip(), moisture)


def normalize_finish_sectional(
    *,
    meet_code: int,
    race_time: Decimal | None,
    accumulated_time: Decimal | None,
    direct_finish_time: Decimal | None,
) -> Decimal | None:
    """Map venue-specific API4 fields to elapsed seconds over a finish interval."""
    if meet_code == 1:
        if race_time is None or accumulated_time is None or race_time <= accumulated_time:
            return None
        return race_time - accumulated_time
    if meet_code == 3:
        return direct_finish_time if direct_finish_time and direct_finish_time > 0 else None
    return None
