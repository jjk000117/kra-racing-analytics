from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

import pandas as pd

HORSE_TOKEN_PATTERN: Final[str] = r"(?:[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]|\(16\))"
PAYOUT_ITEM_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"(?P<combination>{HORSE_TOKEN_PATTERN}+)-(?P<confirmed_odds>\d+(?:\.\d+)?)"
)
ITEM_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s{2,}")
SELECTION_COUNT_BY_POOL: Final[dict[str, int]] = {
    "단식": 1,
    "연식": 1,
    "복식": 2,
    "쌍식": 2,
    "복연": 2,
    "삼복": 3,
    "삼쌍": 3,
}
ORDERED_POOLS: Final[frozenset[str]] = frozenset({"쌍식", "삼쌍"})


@dataclass(frozen=True)
class ParsedPayoutItem:
    source_order: int
    horse_tokens: tuple[str, ...]
    confirmed_odds: float


def horse_token_to_number(token: str) -> int:
    if token == "(16)":
        return 16
    circled_numbers = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
    try:
        return circled_numbers.index(token) + 1
    except ValueError as error:
        raise ValueError(f"Unsupported horse token: {token}") from error


def parse_confirmed_odds_raw(pool_code: str, raw_value: str) -> list[ParsedPayoutItem]:
    if pool_code not in SELECTION_COUNT_BY_POOL:
        raise ValueError(f"Unsupported pool code: {pool_code}")
    if not raw_value or not raw_value.strip():
        raise ValueError("confirmed_odds_raw is blank")

    parsed_items: list[ParsedPayoutItem] = []
    for source_order, item in enumerate(ITEM_SEPARATOR_PATTERN.split(raw_value.strip()), start=1):
        match = PAYOUT_ITEM_PATTERN.fullmatch(item)
        if match is None:
            raise ValueError(f"Unsupported payout item format: {item}")
        horse_tokens = tuple(re.findall(HORSE_TOKEN_PATTERN, match.group("combination")))
        expected_count = SELECTION_COUNT_BY_POOL[pool_code]
        if len(horse_tokens) != expected_count:
            raise ValueError(
                f"Expected {expected_count} selections for {pool_code}, got {len(horse_tokens)}"
            )
        if len(set(horse_tokens)) != len(horse_tokens):
            raise ValueError(f"Duplicate horse in payout item: {item}")
        parsed_items.append(
            ParsedPayoutItem(
                source_order=source_order,
                horse_tokens=horse_tokens,
                confirmed_odds=float(match.group("confirmed_odds")),
            )
        )
    return parsed_items


def profile_confirmed_odds(source: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"sales_id", "race_id", "pool_code", "confirmed_odds_raw"}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    parsed_rows: list[dict[str, object]] = []
    issue_rows: list[dict[str, object]] = []
    for row in source.itertuples(index=False):
        pool_code = str(row.pool_code)
        raw_value = str(row.confirmed_odds_raw)
        try:
            items = parse_confirmed_odds_raw(pool_code, raw_value)
        except ValueError as error:
            issue_rows.append(
                {
                    "sales_id": row.sales_id,
                    "race_id": row.race_id,
                    "pool_code": pool_code,
                    "confirmed_odds_raw": raw_value,
                    "issue": str(error),
                }
            )
            continue

        for item in items:
            horse_numbers = tuple(map(horse_token_to_number, item.horse_tokens))
            canonical_numbers = (
                horse_numbers if pool_code in ORDERED_POOLS else tuple(sorted(horse_numbers))
            )
            parsed_rows.append(
                {
                    "sales_id": row.sales_id,
                    "race_id": row.race_id,
                    "pool_code": pool_code,
                    "source_order": item.source_order,
                    "horse_numbers_source": horse_numbers,
                    "horse_numbers_canonical": canonical_numbers,
                    "confirmed_odds": item.confirmed_odds,
                }
            )
    return pd.DataFrame(parsed_rows), pd.DataFrame(issue_rows)
