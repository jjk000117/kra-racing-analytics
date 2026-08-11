# Audit SQL is kept inline so every reported metric remains directly reviewable.
# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from pathlib import Path

from kra_analytics.database import connect_database
from kra_analytics.feature_snapshot_v2 import (
    TABLE_NAME,
    audit_feature_snapshot_v2,
    registry_feature_names,
)
from kra_analytics.paths import ProjectPaths

OUTPUT_VERSION = "place_feature_snapshot_v2_candidate"


def _write_csv(path: Path, header: list[str], rows: list[tuple[object, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    paths = ProjectPaths.from_root()
    output = paths.exports / "validation" / OUTPUT_VERSION
    features = registry_feature_names(paths.root)
    table = f"mart.{TABLE_NAME}"
    with connect_database(paths=paths, read_only=True) as connection:
        feature_rows: list[tuple[object, ...]] = []
        for feature in features:
            row = connection.execute(
                f"""SELECT count(*) row_count, count({feature}) non_null_count,
                           count(*)-count({feature}) null_count,
                           count(*) FILTER (WHERE try_cast({feature} AS DOUBLE)=0) zero_count
                    FROM {table}"""
            ).fetchone()
            assert row is not None
            feature_rows.append((feature, *row))

        source_rows = connection.execute(
            """SELECT e.meet_code, e.distance_m, count(*) row_count,
                      count(*) FILTER (WHERE rr.is_valid_finish) normal_finish_count,
                      count(e.valid_race_time_seconds) race_time_count,
                      count(e.s1f_seconds) s1f_count,
                      count(e.historical_g3f_seconds) g3f_count,
                      count(e.historical_g1f_seconds) g1f_count,
                      count(e.valid_race_time_seconds) FILTER (WHERE rr.is_valid_finish)
                          normal_finish_race_time_count,
                      count(e.s1f_seconds) FILTER (WHERE rr.is_valid_finish)
                          normal_finish_s1f_count,
                      count(e.historical_g3f_seconds) FILTER (WHERE rr.is_valid_finish)
                          normal_finish_g3f_count,
                      count(e.historical_g1f_seconds) FILTER (WHERE rr.is_valid_finish)
                          normal_finish_g1f_count
               FROM semantic.api4_runner_event_v2 e
               JOIN canonical.runner_result rr
                 ON rr.source_staging_row_id=e.staging_row_id
               GROUP BY e.meet_code, e.distance_m ORDER BY 1,2"""
        ).fetchall()
        snapshot_speed_rows = connection.execute(
            f"""SELECT meet_code, distance_m, count(*) row_count,
                       count(*) FILTER (WHERE horse_recent5_race_time_count>0)
                           race_time_available,
                       count(*) FILTER (WHERE horse_recent5_s1f_count>0) s1f_available,
                       count(*) FILTER (WHERE horse_recent5_g3f_count>0) g3f_available,
                       count(*) FILTER (WHERE horse_recent5_g1f_count>0) g1f_available
                FROM {table} GROUP BY meet_code, distance_m ORDER BY 1,2"""
        ).fetchall()
        busan_relation = connection.execute(
            """SELECT count(*),
                      max(abs(valid_race_time_seconds-bu_g3f_acc_time_seconds-
                              bu_g3f_to_finish_seconds)),
                      max(abs(valid_race_time_seconds-bu_g1f_acc_time_seconds-
                              bu_g1f_to_finish_seconds))
               FROM semantic.api4_runner_event_v2
               WHERE meet_code=3 AND valid_race_time_seconds IS NOT NULL
                 AND bu_g3f_acc_time_seconds IS NOT NULL
                 AND bu_g3f_to_finish_seconds IS NOT NULL"""
        ).fetchone()
        range_rows = []
        for feature in (
            "current_horse_weight_kg", "current_horse_weight_change_kg",
            "horse_recent5_race_time_median", "horse_recent5_s1f_median",
            "horse_recent5_g3f_median", "horse_recent5_g1f_median",
        ):
            values = connection.execute(
                f"SELECT min({feature}), quantile_cont({feature}, .01), quantile_cont({feature}, .5), quantile_cont({feature}, .99), max({feature}) FROM {table}"
            ).fetchone()
            assert values is not None
            range_rows.append((feature, *values))

        frame = connection.execute(
            f"SELECT {','.join(features)} FROM {table} ORDER BY race_id, horse_id"
        ).fetchdf()
        duplicate_groups: list[tuple[str, str]] = []
        duplicate_candidates = list(frame.columns[frame.T.duplicated(keep=False)])
        for index, first in enumerate(duplicate_candidates):
            for second in duplicate_candidates[index + 1 :]:
                if frame[first].equals(frame[second]):
                    duplicate_groups.append((first, second))

        formula_violations = connection.execute(
            f"""SELECT
                count(*) FILTER (WHERE horse_prior_finish_rate IS DISTINCT FROM
                    horse_prior_finish_count::DOUBLE/nullif(horse_prior_start_count,0)),
                count(*) FILTER (WHERE horse_recent3_start_count>horse_recent5_start_count
                                      OR horse_recent5_start_count>horse_recent10_start_count),
                count(*) FILTER (WHERE horse_same_distance_start_count>
                                      horse_prior_start_count),
                count(*) FILTER (WHERE NOT horse_history_available AND
                                      (horse_prior_start_count>0 OR
                                       horse_prior_plc_hit_rate IS NOT NULL)),
                count(*) FILTER (WHERE horse_recent5_g3f_count=0 AND
                                      horse_recent5_g3f_median IS NOT NULL),
                count(*) FILTER (WHERE horse_recent5_g1f_count=0 AND
                                      horse_recent5_g1f_median IS NOT NULL)
                FROM {table}"""
        ).fetchone()
        counts = connection.execute(
            f"SELECT count(*),count(DISTINCT race_id),count(*) FILTER(WHERE place_hit) FROM {table}"
        ).fetchone()

    _write_csv(
        output / "feature_availability.csv",
        ["feature", "row_count", "non_null_count", "null_count", "zero_count"],
        feature_rows,
    )
    _write_csv(
        output / "source_sectional_by_meet_distance.csv",
        [
            "meet_code", "distance_m", "row_count", "normal_finish_count",
            "race_time_count", "s1f_count", "g3f_count", "g1f_count",
            "normal_finish_race_time_count", "normal_finish_s1f_count",
            "normal_finish_g3f_count", "normal_finish_g1f_count",
        ],
        source_rows,
    )
    _write_csv(
        output / "snapshot_sectional_by_meet_distance.csv",
        [
            "meet_code", "distance_m", "row_count", "race_time_available",
            "s1f_available", "g3f_available", "g1f_available",
        ],
        snapshot_speed_rows,
    )
    _write_csv(
        output / "feature_ranges.csv",
        ["feature", "min", "p01", "median", "p99", "max"],
        range_rows,
    )
    _write_csv(
        output / "exact_duplicate_features.csv",
        ["first_feature", "duplicate_feature"],
        duplicate_groups,
    )
    summary = {
        "snapshot_version": OUTPUT_VERSION,
        "feature_count": len(features),
        "row_count": counts[0],
        "race_count": counts[1],
        "positive_count": counts[2],
        "core_audit_issues": audit_feature_snapshot_v2(paths=paths),
        "busan_accumulated_direct_relation": {
            "rows": busan_relation[0],
            "max_g3f_absolute_difference": busan_relation[1],
            "max_g1f_absolute_difference": busan_relation[2],
        },
        "formula_violation_counts": {
            "prior_finish_rate": formula_violations[0],
            "recent_window_count_order": formula_violations[1],
            "same_distance_vs_prior": formula_violations[2],
            "horse_history_flag": formula_violations[3],
            "g3f_count_value": formula_violations[4],
            "g1f_count_value": formula_violations[5],
        },
        "exact_duplicate_feature_pairs": duplicate_groups,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
