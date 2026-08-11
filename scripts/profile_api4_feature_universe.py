from __future__ import annotations

import argparse
import csv
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import duckdb

from kra_analytics.feature_snapshot import MODEL_FEATURES
from kra_analytics.paths import ProjectPaths
from kra_analytics.staging import RACE_FIELDS

VERSION = "api4_feature_universe_v2"

POST_RACE_FIELDS = {
    "diffUnit",
    "ord",
    "plcOdds",
    "rcTime",
    "winOdds",
    *[
        name
        for name in RACE_FIELDS
        if name.startswith(
            ("buG", "buS", "bu_", "jeG", "jeS", "je_", "seG", "seS", "se_", "sjG", "sjS", "sj_")
        )
    ],
}
CURRENT_APPROVED_FIELDS = {
    "age",
    "chulNo",
    "hrNo",
    "jkNo",
    "meet",
    "rank",
    "rating",
    "rcDate",
    "rcDist",
    "rcNo",
    "sex",
    "trNo",
    "wgBudam",
}
CURRENT_CONDITION_FIELDS = {
    "ageCond",
    "budam",
    "buga1",
    "buga2",
    "buga3",
    "chaksun1",
    "chaksun2",
    "chaksun3",
    "chaksun4",
    "chaksun5",
    "prizeCond",
    "rcName",
    "sexCond",
}
UNVERIFIED_CURRENT_FIELDS = {"track", "weather", "wgHr"}
DISPLAY_FIELDS = {
    "hrName",
    "hrNameEn",
    "jkName",
    "jkNameEn",
    "name",
    "owName",
    "owNameEn",
    "rcDay",
    "trName",
    "trNameEn",
}
CANONICAL_MAP = {
    "age": "canonical.runner_result.horse_age",
    "chulNo": "canonical.runner_result.gate_no",
    "hrName": "canonical.runner_result.horse_name",
    "hrNo": "canonical.runner_result.horse_id",
    "jkName": "canonical.runner_result.jockey_name",
    "jkNo": "canonical.runner_result.jockey_id",
    "meet": "canonical.race.meet_code/meet_name",
    "ord": "canonical.runner_result.ord_raw/official_finish_rank/result_status",
    "owName": "canonical.runner_result.owner_name",
    "owNo": "canonical.runner_result.owner_id",
    "plcOdds": "canonical.runner_result.place_odds",
    "rank": "canonical.race.race_grade",
    "rcDate": "canonical.race.race_date",
    "rcDist": "canonical.race.distance_m",
    "rcName": "canonical.race.race_name",
    "rcNo": "canonical.race.race_no",
    "rcTime": "canonical.runner_result.race_time (INTEGER; precision loss)",
    "sex": "canonical.runner_result.horse_sex",
    "trName": "canonical.runner_result.trainer_name",
    "trNo": "canonical.runner_result.trainer_id",
    "track": "canonical.race.track_condition (raw combined label)",
    "weather": "canonical.race.weather",
    "wgBudam": "canonical.runner_result.carried_weight",
    "wgHr": "canonical.runner_result.horse_weight (current parse fails)",
    "winOdds": "canonical.runner_result.win_odds",
}


def metadata_from_docx(path: Path) -> dict[str, dict[str, str]]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    metadata: dict[str, dict[str, str]] = {}
    for table in root.findall(".//w:tbl", namespace):
        for row in table.findall("./w:tr", namespace)[1:]:
            cells = []
            for cell in row.findall("./w:tc", namespace):
                texts = [value.text or "" for value in cell.findall(".//w:t", namespace)]
                cells.append("".join(texts).strip())
            if len(cells) < 6 or cells[0] not in RACE_FIELDS:
                continue
            metadata[cells[0]] = {
                "official_name": cells[1],
                "official_size": cells[2],
                "official_required": cells[3],
                "official_sample": cells[4],
                "official_description": cells[5],
            }
    return metadata


def sample_values(connection: duckdb.DuckDBPyConnection, field: str) -> list[str]:
    rows = connection.execute(
        f"""SELECT \"{field}\", count(*) AS n
            FROM staging.race_result
            WHERE nullif(trim(\"{field}\"), '') IS NOT NULL
            GROUP BY \"{field}\" ORDER BY n DESC, \"{field}\" LIMIT 3"""
    ).fetchall()
    return [str(row[0]) for row in rows]


def classify_field(field: str) -> tuple[str, str, str, str, str]:
    if field in POST_RACE_FIELDS:
        return (
            "CURRENT_RESULT_OR_POST_RACE",
            "POST_RACE_ONLY",
            "YES",
            "PROHIBITED_CURRENT; historical source allowed",
            "YES",
        )
    if field in CURRENT_APPROVED_FIELDS:
        return ("IDENTIFIER_OR_CURRENT_PRERACE", "AVAILABLE", "YES", "APPROVED", "NO")
    if field in CURRENT_CONDITION_FIELDS:
        return ("CURRENT_RACE_CONDITION", "AVAILABLE_BY_MEANING", "YES", "APPROVED", "NO")
    if field in UNVERIFIED_CURRENT_FIELDS:
        return (
            "ENVIRONMENT_OR_MEASUREMENT",
            "UNVERIFIED_AT_PREDICTION_TIME",
            "YES",
            "NEEDS_VALIDATION",
            "NO",
        )
    if field in DISPLAY_FIELDS:
        return ("DISPLAY", "NOT_A_MODEL_FEATURE", "NO", "DEFERRED", "NO")
    if field == "ilsu":
        return ("NEEDS_VALIDATION", "NOT_HORSE_REST_DAYS", "NO", "PROHIBITED", "NO")
    if field in {"hrNameEn", "jkNameEn", "owNameEn", "trNameEn"}:
        return ("DISPLAY", "NOT_A_MODEL_FEATURE", "NO", "DEFERRED", "NO")
    return ("IDENTIFIER_OR_AUXILIARY", "UNVERIFIED", "YES", "NEEDS_VALIDATION", "NO")


def information_loss(field: str) -> tuple[str, str]:
    if field == "rcTime":
        return ("YES", "Canonical INTEGER conversion loses tenth-second precision")
    if field == "wgHr":
        return ("YES", "Canonical direct decimal cast yields NULL for weight(change)")
    if field in CANONICAL_MAP:
        return ("NO_OR_INTENTIONAL_CAST", f"Mapped to {CANONICAL_MAP[field]}")
    return ("NOT_CARRIED_FORWARD", "Raw value remains recoverable from Staging/source_item_json")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def add_feature(
    rows: list[dict[str, str]],
    name: str,
    category: str,
    sources: str,
    definition: str,
    window: str,
    availability: str,
    missing: str,
    minimum_history: str,
    leakage: str,
    redundancy: str,
    status: str,
    group: str,
) -> None:
    rows.append(
        {
            "feature_name": name,
            "category": category,
            "source_fields": sources,
            "calculation_definition": definition,
            "historical_window_or_condition": window,
            "pit_rule": "historical.race_date < feature_as_of"
            if window != "CURRENT"
            else "current-race pre-off only",
            "prediction_time_availability": availability,
            "missing_or_structural_missing": missing,
            "minimum_history_and_companion_count": minimum_history,
            "leakage_risk": leakage,
            "expected_redundancy": redundancy,
            "status": status,
            "recommendation_group": group,
        }
    )


def build_feature_registry() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current = [
        ("meet_code", "meet"),
        ("race_grade", "rank"),
        ("distance_m", "rcDist"),
        ("registered_runner_count", "API4 race rows"),
        ("gate_no", "chulNo"),
        ("horse_sex", "sex"),
        ("horse_age", "age"),
        ("carried_weight", "wgBudam"),
        ("rating", "rating"),
    ]
    for name, source in current:
        add_feature(
            rows,
            name,
            "CURRENT_PRERACE",
            source,
            "Current-race declared value",
            "CURRENT",
            "validated historical race-level value",
            "NULL means source missing",
            "none",
            "LOW",
            "may correlate with other race conditions",
            "APPROVED",
            "IMMEDIATE_BASELINE",
        )

    for name, source, status in [
        ("race_age_condition", "ageCond", "APPROVED"),
        ("race_weight_condition", "budam", "APPROVED"),
        ("race_prize_condition", "prizeCond", "APPROVED"),
        ("race_sex_condition", "sexCond", "APPROVED"),
        ("race_type", "rcName", "APPROVED"),
        ("race_day_of_week", "rcDate", "APPROVED"),
        ("race_first_prize", "chaksun1", "APPROVED"),
        ("race_second_prize", "chaksun2", "APPROVED"),
        ("race_third_prize", "chaksun3", "APPROVED"),
        ("race_fourth_prize", "chaksun4", "APPROVED"),
        ("race_fifth_prize", "chaksun5", "APPROVED"),
        ("race_bonus_1", "buga1", "NEEDS_VALIDATION"),
        ("race_bonus_2", "buga2", "NEEDS_VALIDATION"),
        ("race_bonus_3", "buga3", "NEEDS_VALIDATION"),
    ]:
        group = "IMMEDIATE_BASELINE" if status == "APPROVED" else "VALIDATE_BEFORE_INCLUDE"
        add_feature(
            rows,
            name,
            "CURRENT_RACE_CONDITION",
            source,
            "Declared race condition/value",
            "CURRENT",
            "fixed before race; production publication timing needs an operational check",
            "NULL/unknown category retained",
            "none",
            "LOW",
            "may overlap grade/distance/prize class",
            status,
            group,
        )

    existing_history = [
        name for name in MODEL_FEATURES if name not in {item[0] for item in current}
    ]
    for name in existing_history:
        status = "DEFERRED" if name == "horse_prior_plc_hit_count" else "APPROVED_WITH_FLAG"
        group = "FOLLOW_UP" if status == "DEFERRED" else "IMMEDIATE_BASELINE"
        add_feature(
            rows,
            name,
            "HISTORICAL_EXISTING",
            "API4 prior runner events",
            "Existing place_feature_snapshot_v1 definition",
            "ALL or recent5/same-distance as named",
            "historical only",
            "left-censoring or no history",
            "existing count/availability companion",
            "LOW",
            "hit count is exact function of count and rate"
            if name == "horse_prior_plc_hit_count"
            else "related history summaries",
            status,
            group,
        )

    for name, definition in [
        ("horse_prior_win_count", "historical official rank 1 count"),
        ("horse_prior_win_rate", "historical official rank 1 / starts"),
        ("horse_prior_top3_count", "historical official rank <=3 count"),
        ("horse_prior_top3_rate", "historical official rank <=3 / starts"),
        ("horse_prior_best_finish_rank", "minimum historical valid finish rank"),
        ("horse_prior_finish_rank_std", "standard deviation of valid finish rank"),
        ("horse_prior_rating_mean", "mean historical rating"),
        ("horse_last_rating", "latest historical rating"),
        (
            "horse_rating_change_last_start",
            "current pre-race rating minus latest historical rating",
        ),
        ("horse_prior_carried_weight_mean", "mean historical carried weight"),
    ]:
        add_feature(
            rows,
            name,
            "LONG_TERM_PERFORMANCE",
            "ord,rating,wgBudam",
            definition,
            "ALL",
            "historical only except current rating in explicit delta",
            "NULL when no eligible history",
            "horse_prior_start_count",
            "LOW",
            "related counts/rates retained for later ablation",
            "APPROVED_WITH_FLAG",
            "IMMEDIATE_BASELINE",
        )

    for horizon in (3, 5, 10):
        for metric, definition in [
            ("finish_rate", "valid finishes / starts"),
            ("win_rate", "official rank 1 / starts"),
            ("top3_rate", "official rank <=3 / starts"),
            ("avg_finish_rank", "mean rank among valid finishes"),
            ("best_finish_rank", "minimum rank among valid finishes"),
            ("avg_rating", "mean historical rating"),
            ("rating_change", "latest minus earliest rating in window"),
        ]:
            add_feature(
                rows,
                f"horse_recent{horizon}_{metric}",
                "RECENT_FORM",
                "rcDate,ord,rating",
                definition,
                f"last {horizon} starts",
                "historical only",
                "NULL when no eligible observation",
                f"horse_recent{horizon}_start_count",
                "LOW",
                "overlaps other recent windows",
                "APPROVED_WITH_FLAG",
                "IMMEDIATE_BASELINE",
            )
        add_feature(
            rows,
            f"horse_recent{horizon}_start_count",
            "RECENT_FORM",
            "rcDate",
            "eligible observations in window",
            f"last {horizon} starts",
            "historical only",
            "0 means no history",
            "self",
            "LOW",
            "window depth companion",
            "APPROVED",
            "IMMEDIATE_BASELINE",
        )

    for condition, fields in [
        ("same_meet", "meet"),
        ("same_distance", "rcDist"),
        ("same_meet_distance", "meet,rcDist"),
    ]:
        for metric in ("start_count", "finish_rate", "plc_hit_rate", "avg_finish_rank"):
            add_feature(
                rows,
                f"horse_{condition}_{metric}",
                "CONDITION_AFFINITY",
                f"{fields},ord",
                f"Historical {metric} under {condition}",
                condition,
                "historical only",
                "NULL rate if count=0",
                f"horse_{condition}_start_count",
                "LOW",
                "nested condition summaries",
                "APPROVED_WITH_FLAG",
                "IMMEDIATE_BASELINE",
            )

    for horizon in (3, 5):
        for metric, source in [("race_time", "rcTime"), ("s1f", "seS1fAccTime,buS1fTime")]:
            add_feature(
                rows,
                f"horse_recent{horizon}_{metric}_median",
                "SPEED_SECTIONAL",
                source,
                "median valid historical seconds",
                f"last {horizon} valid records",
                "historical only",
                "0/non-start/structural missing excluded",
                f"horse_recent{horizon}_{metric}_count",
                "MEDIUM",
                "distance and meet dependent",
                "APPROVED_WITH_FLAG",
                "IMMEDIATE_BASELINE",
            )
            add_feature(
                rows,
                f"horse_recent{horizon}_{metric}_count",
                "SPEED_SECTIONAL",
                source,
                "valid observations",
                f"last {horizon} valid records",
                "historical only",
                "0 means unavailable",
                "self",
                "LOW",
                "companion count",
                "APPROVED",
                "IMMEDIATE_BASELINE",
            )
        for metric, source in [
            ("g3f", "seG3fAccTime,bu_3fGTime"),
            ("g1f", "seG1fAccTime,bu_1fGTime"),
        ]:
            add_feature(
                rows,
                f"horse_recent{horizon}_{metric}_median",
                "SPEED_SECTIONAL",
                source,
                "venue-specific meaning pending; do not merge yet",
                f"last {horizon} valid records",
                "historical only",
                "structural missing by venue/distance",
                f"horse_recent{horizon}_{metric}_count",
                "MEDIUM",
                "potentially different source semantics",
                "NEEDS_VALIDATION",
                "VALIDATE_BEFORE_INCLUDE",
            )

    for name, definition in [
        ("horse_last_weight_kg", "latest parsed historical horse weight"),
        ("horse_last_weight_change_kg", "latest published change"),
        ("horse_recent5_weight_mean", "mean weight over last five starts"),
        ("horse_recent5_weight_std", "weight standard deviation over last five starts"),
        ("horse_recent5_weight_count", "valid weight observations"),
    ]:
        add_feature(
            rows,
            name,
            "HORSE_WEIGHT_HISTORY",
            "wgHr",
            definition,
            "last 1 or 5 starts",
            "historical only",
            "parse/missing -> NULL",
            "horse_recent5_weight_count where relevant",
            "LOW",
            "weight level and change related",
            "APPROVED_WITH_FLAG",
            "IMMEDIATE_BASELINE",
        )

    for role, source in [("jockey", "jkNo"), ("trainer", "trNo"), ("horse_jockey", "hrNo,jkNo")]:
        for metric in (
            "recent10_start_count",
            "recent10_plc_hit_rate",
            "same_meet_start_count",
            "same_meet_plc_hit_rate",
        ):
            add_feature(
                rows,
                f"{role}_{metric}",
                "RELATIONSHIP_HISTORY",
                f"{source},meet,ord",
                f"Historical {metric}",
                "last 10 or same meet",
                "historical only",
                "NULL rate if count=0",
                f"{role}_{metric.replace('plc_hit_rate', 'start_count')}",
                "LOW",
                "overlaps all-history relationship rate",
                "APPROVED_WITH_FLAG",
                "IMMEDIATE_BASELINE",
            )

    for name, definition in [
        ("owner_prior_start_count", "historical starts under owner ID"),
        ("owner_prior_plc_hit_rate", "historical PLC hits / starts under owner ID"),
        ("horse_trainer_prior_start_count", "historical starts for horse-trainer pair"),
        ("horse_trainer_prior_plc_hit_rate", "historical PLC rate for horse-trainer pair"),
    ]:
        add_feature(
            rows,
            name,
            "RELATIONSHIP_HISTORY",
            "owNo,hrNo,trNo,ord",
            definition,
            "ALL",
            "historical only",
            "NULL rate when ID/count missing",
            name.replace("plc_hit_rate", "start_count"),
            "LOW",
            "sparse pair/entity history",
            "APPROVED_WITH_FLAG",
            "IMMEDIATE_BASELINE",
        )

    for name, source in [
        ("current_weather", "weather"),
        ("current_track_condition", "track"),
        ("current_track_moisture_percent", "track"),
        ("current_horse_weight_kg", "wgHr"),
        ("current_horse_weight_change_kg", "wgHr"),
    ]:
        add_feature(
            rows,
            name,
            "CURRENT_UNVERIFIED",
            source,
            "Current-race value",
            "CURRENT",
            "not yet proven available at prediction cutoff",
            "NULL if not published",
            "none",
            "HIGH",
            "may overlap historical condition",
            "NEEDS_VALIDATION",
            "VALIDATE_BEFORE_INCLUDE",
        )

    for name in (
        "horse_same_track_condition_start_count",
        "horse_same_track_condition_plc_hit_rate",
        "horse_same_weather_start_count",
        "horse_same_weather_plc_hit_rate",
    ):
        add_feature(
            rows,
            name,
            "ENVIRONMENT_AFFINITY",
            "weather,track,ord",
            "Historical performance under matching environment",
            "matching historical condition",
            "historical side safe; current matching key unavailable until validated",
            "NULL rate if count=0",
            name.replace("plc_hit_rate", "start_count"),
            "MEDIUM",
            "sparse categories and current availability",
            "DEFERRED",
            "FOLLOW_UP",
        )

    for name, source, reason in [
        ("current_finish_rank", "ord", "current outcome"),
        ("current_race_time", "rcTime", "current outcome"),
        ("current_sectionals", "se*/bu*", "current outcome"),
        ("current_margin", "diffUnit", "current outcome"),
        ("current_win_odds", "winOdds", "post-race/market value not cutoff-validated"),
        ("current_place_odds", "plcOdds", "post-race/market value not cutoff-validated"),
        ("current_sales", "API179 amt", "post-race market aggregate"),
        ("api26_current_cumulative_stats", "API26 totals", "historical PIT failure"),
        ("api37_cumulative_sectionals", "API37 aggregates", "request-date inclusion and PIT risk"),
        ("ilsu_as_days_since_last_start", "ilsu", "meaning disproven"),
    ]:
        add_feature(
            rows,
            name,
            "PROHIBITED",
            source,
            reason,
            "CURRENT/EXTERNAL",
            "not safely available",
            "not applicable",
            "none",
            "HIGH",
            "not applicable",
            "PROHIBITED",
            "PROHIBITED",
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-docx", type=Path, required=True)
    args = parser.parse_args()
    paths = ProjectPaths.from_root()
    output = paths.exports / "validation" / VERSION
    docs = paths.root / "docs"
    metadata = metadata_from_docx(args.metadata_docx)
    if set(metadata) != set(RACE_FIELDS):
        raise ValueError(f"Metadata mismatch: metadata={len(metadata)} raw={len(RACE_FIELDS)}")

    connection = duckdb.connect(str(paths.database), read_only=True)
    total = int(connection.execute("SELECT count(*) FROM staging.race_result").fetchone()[0])
    field_rows: list[dict[str, Any]] = []
    for field in RACE_FIELDS:
        nonblank, distinct_count, zero_count = connection.execute(
            f"""SELECT
                    count(*) FILTER (WHERE nullif(trim(\"{field}\"), '') IS NOT NULL),
                    count(DISTINCT nullif(trim(\"{field}\"), '')),
                    count(*) FILTER (WHERE try_cast(\"{field}\" AS DOUBLE) = 0)
                FROM staging.race_result"""
        ).fetchone()
        category, availability, historical, status, post_race = classify_field(field)
        loss, transform = information_loss(field)
        semantic_dtype = {
            "rcTime": "DECIMAL(8,1) seconds",
            "wgHr": "INTEGER kg + INTEGER delta",
            "track": "VARCHAR condition + INTEGER moisture_percent",
        }.get(field, "VARCHAR (semantic cast only when defined)")
        field_rows.append(
            {
                "raw_field": field,
                **metadata[field],
                "actual_examples": " | ".join(sample_values(connection, field)),
                "staging_dtype": "VARCHAR",
                "semantic_dtype": semantic_dtype,
                "nonblank_rows": nonblank,
                "null_or_blank_rate": round(1 - nonblank / total, 8),
                "distinct_count": distinct_count,
                "numeric_zero_rows": zero_count,
                "staging_preserved": "YES",
                "canonical_preservation": CANONICAL_MAP.get(field, "NO DEDICATED COLUMN"),
                "current_transform": transform,
                "information_loss": loss,
                "field_category": category,
                "prediction_time_direct_use": availability,
                "historical_feature_source": historical,
                "post_race_information": post_race,
                "review_status": status,
            }
        )

    registry = build_feature_registry()
    write_csv(output / "api4_field_audit.csv", field_rows)
    write_csv(output / "feature_registry.csv", registry)
    write_csv(docs / "api4-field-audit-v2.csv", field_rows)
    write_csv(docs / "place-feature-registry-v2.csv", registry)

    sectional_fields = [
        "valid_race_time_seconds",
        "s1f_seconds",
        "se_g3f_acc_time_seconds",
        "se_g1f_acc_time_seconds",
        "bu_g3f_to_finish_seconds",
        "bu_g1f_to_finish_seconds",
    ]
    availability_rows: list[dict[str, Any]] = []
    for field in sectional_fields:
        for year, meet, distance, rows, available in connection.execute(
            f"""SELECT year(race_date), meet_code, distance_m, count(*), count(\"{field}\")
                FROM semantic.api4_runner_event_v2
                GROUP BY ALL ORDER BY 1, 2, 3"""
        ).fetchall():
            availability_rows.append(
                {
                    "field": field,
                    "year": year,
                    "meet_code": meet,
                    "distance_m": distance,
                    "rows": rows,
                    "available_rows": available,
                    "available_rate": round(available / rows, 8),
                    "structural_missing_rate": round(1 - available / rows, 8),
                }
            )
    write_csv(output / "sectional_availability.csv", availability_rows)

    semantic_source_fields = [
        "valid_race_time_seconds",
        "horse_weight_kg",
        "horse_weight_change_kg",
        "s1f_seconds",
        "se_g3f_acc_time_seconds",
        "se_g1f_acc_time_seconds",
        "bu_g3f_to_finish_seconds",
        "bu_g1f_to_finish_seconds",
        "weather",
        "track_condition",
        "track_moisture_percent",
    ]
    source_profile_rows: list[dict[str, Any]] = []
    for field in semantic_source_fields:
        for year, meet, rows, available in connection.execute(
            f"""SELECT year(race_date), meet_code, count(*), count(\"{field}\")
                FROM semantic.api4_runner_event_v2
                GROUP BY ALL ORDER BY 1, 2"""
        ).fetchall():
            source_profile_rows.append(
                {
                    "field": field,
                    "year": year,
                    "meet_code": meet,
                    "rows": rows,
                    "available_rows": available,
                    "available_rate": round(available / rows, 8),
                }
            )
    write_csv(output / "semantic_source_availability_by_year_meet.csv", source_profile_rows)

    weight_failure_rows = [
        {"horse_weight_raw": raw, "row_count": count, "failure_type": failure_type}
        for raw, count, failure_type in connection.execute(
            """SELECT horse_weight_raw, count(*),
                      CASE WHEN horse_weight_kg IS NULL THEN 'WEIGHT_PARSE_FAILED'
                           ELSE 'CHANGE_PARSE_FAILED' END
               FROM semantic.api4_runner_event_v2
               WHERE horse_weight_kg IS NULL OR horse_weight_change_kg IS NULL
               GROUP BY 1, 3 ORDER BY 2 DESC, 1"""
        ).fetchall()
    ]
    write_csv(output / "horse_weight_parse_failures.csv", weight_failure_rows)

    weight = connection.execute(
        """SELECT count(*), count(horse_weight_kg), count(horse_weight_change_kg),
                  min(horse_weight_kg), quantile_cont(horse_weight_kg, 0.5), max(horse_weight_kg),
                  min(horse_weight_change_kg), quantile_cont(horse_weight_change_kg, 0.5),
                  max(horse_weight_change_kg)
           FROM semantic.api4_runner_event_v2"""
    ).fetchone()
    race_time = connection.execute(
        """SELECT count(*), count(race_time_seconds),
                  count(*) FILTER (WHERE race_time_seconds = 0),
                  min(race_time_seconds) FILTER (WHERE race_time_seconds > 0),
                  quantile_cont(race_time_seconds, 0.5) FILTER (WHERE race_time_seconds > 0),
                  max(race_time_seconds)
           FROM semantic.api4_runner_event_v2"""
    ).fetchone()
    categories = {
        "weather": connection.execute(
            "SELECT weather, count(*) FROM semantic.api4_runner_event_v2 GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall(),
        "track": connection.execute(
            """SELECT track_condition, track_moisture_percent, count(*)
               FROM semantic.api4_runner_event_v2 GROUP BY 1,2 ORDER BY 3 DESC"""
        ).fetchall(),
    }
    semantic_audit_issues: list[str] = []
    semantic_rows = int(
        connection.execute("SELECT count(*) FROM semantic.api4_runner_event_v2").fetchone()[0]
    )
    if semantic_rows != total:
        semantic_audit_issues.append("SEMANTIC_ROW_COUNT_MISMATCH")
    duplicate_keys = int(
        connection.execute(
            """SELECT count(*) FROM (
               SELECT staging_row_id FROM semantic.api4_runner_event_v2
               GROUP BY 1 HAVING count(*) > 1
           )"""
        ).fetchone()[0]
    )
    if duplicate_keys:
        semantic_audit_issues.append("DUPLICATE_STAGING_ROW_ID")
    precision_mismatches = int(
        connection.execute(
            """SELECT count(*) FROM semantic.api4_runner_event_v2 v
           JOIN staging.race_result s USING (staging_row_id)
           WHERE v.race_time_seconds IS DISTINCT FROM try_cast(s.rcTime AS DECIMAL(8,1))"""
        ).fetchone()[0]
    )
    if precision_mismatches:
        semantic_audit_issues.append("RACE_TIME_PRECISION_MISMATCH")
    complete_weight_parse_failures = int(
        connection.execute(
            """SELECT count(*) FROM semantic.api4_runner_event_v2
           WHERE regexp_matches(horse_weight_raw, '^[0-9]{2,3}\\([+-]?[0-9]+\\)$')
             AND (horse_weight_kg IS NULL OR horse_weight_change_kg IS NULL)"""
        ).fetchone()[0]
    )
    if complete_weight_parse_failures:
        semantic_audit_issues.append("COMPLETE_WEIGHT_PATTERN_PARSE_FAILURE")
    summary = {
        "version": VERSION,
        "raw_field_count": len(RACE_FIELDS),
        "metadata_matched": len(metadata),
        "staging_rows": total,
        "feature_candidate_count": len(registry),
        "status_counts": dict(Counter(row["status"] for row in registry)),
        "recommendation_group_counts": dict(
            Counter(row["recommendation_group"] for row in registry)
        ),
        "horse_weight_profile": weight,
        "horse_weight_parse_failure_rows": sum(row["row_count"] for row in weight_failure_rows),
        "horse_weight_parse_failure_patterns": len(weight_failure_rows),
        "race_time_profile": race_time,
        "category_profiles": categories,
        "semantic_row_count": semantic_rows,
        "semantic_duplicate_key_count": duplicate_keys,
        "race_time_precision_mismatch_count": precision_mismatches,
        "complete_weight_pattern_parse_failure_count": complete_weight_parse_failures,
        "semantic_audit_issues": semantic_audit_issues,
        "baseline_v1_changed": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
