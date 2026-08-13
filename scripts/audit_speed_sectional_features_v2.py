from __future__ import annotations

import csv
import json
from pathlib import Path

from duckdb import DuckDBPyConnection

from kra_analytics.database import connect_database
from kra_analytics.paths import ProjectPaths

VERSION = "official_place_baseline_v2_speed_sectional_audit"
SNAPSHOT = "mart.place_feature_snapshot_v2_candidate"

METRICS = {
    "s1f": "s1f_seconds",
    "g3f": "historical_g3f_seconds",
    "g1f": "historical_g1f_seconds",
}


def _write_query_csv(
    connection: DuckDBPyConnection, query: str, output: Path
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(f"COPY ({query}) TO '{output.as_posix()}' (HEADER, DELIMITER ',')")


def _profile_query(group_columns: tuple[str, ...]) -> str:
    grouping = ", ".join(group_columns)
    selected_grouping = f"{grouping}," if grouping else ""
    grouped_by = f"GROUP BY metric, {grouping}" if grouping else "GROUP BY metric"
    values = " UNION ALL ".join(
        f"SELECT {selected_grouping}'{metric}' metric, {column} metric_value FROM eligible_events"
        for metric, column in METRICS.items()
    )
    return f"""
        WITH eligible_events AS (
            SELECT e.meet_code, e.distance_m, e.s1f_seconds,
                   e.historical_g3f_seconds, e.historical_g1f_seconds
            FROM semantic.api4_runner_event_v2 e
            JOIN canonical.runner_result rr
              ON rr.source_staging_row_id = e.staging_row_id
            JOIN analytics.fact_race fr USING (race_id)
            WHERE fr.is_market_eligible AND rr.is_valid_start
        ), long_values AS ({values})
        SELECT {selected_grouping}metric,
               count(*) row_count,
               count(metric_value) observed_count,
               round(1 - count(metric_value)::DOUBLE / count(*), 8) missing_rate,
               round(quantile_cont(metric_value, 0.05), 3) p05,
               round(quantile_cont(metric_value, 0.25), 3) p25,
               round(median(metric_value), 3) median,
               round(quantile_cont(metric_value, 0.75), 3) p75,
               round(quantile_cont(metric_value, 0.95), 3) p95
        FROM long_values
        {grouped_by}
        ORDER BY {selected_grouping}metric
    """


def _lineage_rows(inventory: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in inventory:
        name = row["feature_name"]
        if not any(token in name for token in ("race_time", "s1f", "g3f", "g1f")):
            continue
        metric = next(
            token for token in ("race_time", "s1f", "g3f", "g1f") if token in name
        )
        window = "recent3" if "recent3" in name else "recent5"
        aggregation = "count(non-null)" if name.endswith("_count") else "median(non-null)"
        sources = {
            "race_time": ("rcTime", "rcTime", "valid_race_time_seconds", "seconds"),
            "s1f": ("seS1fAccTime", "buS1fTime", "s1f_seconds", "seconds (first 200m)"),
            "g3f": (
                "rcTime - seG3fAccTime",
                "bu_3fGTime",
                "historical_g3f_seconds",
                "seconds (final 600m)",
            ),
            "g1f": (
                "rcTime - seG1fAccTime",
                "bu_1fGTime",
                "historical_g1f_seconds",
                "seconds (final 200m)",
            ),
        }
        seoul, busan, semantic, unit = sources[metric]
        if metric == "race_time" and name.endswith("_median"):
            verdict = "EXCLUDE"
            reason = "absolute total time mixes different distances and meets"
        elif metric == "race_time":
            verdict = "KEEP_AS_IS"
            reason = "count represents historical observation depth, not speed magnitude"
        else:
            verdict = "KEEP_AS_IS"
            reason = "venue-normalized fixed-length section in common seconds"
        rows.append(
            {
                "feature_name": name,
                "current_modeling_role": row["modeling_role"],
                "raw_source_seoul": seoul,
                "raw_source_busan": busan,
                "staging_columns": seoul.replace("rcTime - ", "rcTime,")
                + ("," + busan if busan != seoul else ""),
                "semantic_event_value": semantic,
                "unit": unit,
                "window": window,
                "aggregation": aggregation,
                "mixes_meets": "true",
                "mixes_distances": "true",
                "pit_condition": "historical.race_date < feature_as_of",
                "verdict": verdict,
                "verdict_reason": reason,
            }
        )
    return rows


def main() -> None:
    paths = ProjectPaths.from_root()
    output_dir = paths.exports / "validation" / VERSION
    inventory_path = paths.root / "docs" / "official-place-baseline-v2-model-input-inventory.csv"
    with inventory_path.open(encoding="utf-8-sig", newline="") as stream:
        inventory = list(csv.DictReader(stream))

    lineage = _lineage_rows(inventory)
    lineage_path = output_dir / "feature_lineage_and_verdict.csv"
    lineage_path.parent.mkdir(parents=True, exist_ok=True)
    with lineage_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(lineage[0]))
        writer.writeheader()
        writer.writerows(lineage)

    with connect_database(paths=paths, read_only=True) as connection:
        _write_query_csv(
            connection,
            _profile_query(("meet_code",)),
            output_dir / "profile_by_meet.csv",
        )
        _write_query_csv(
            connection,
            _profile_query(("distance_m",)),
            output_dir / "profile_by_distance.csv",
        )
        _write_query_csv(
            connection,
            _profile_query(("meet_code", "distance_m")),
            output_dir / "profile_by_meet_distance.csv",
        )

        normalization = connection.execute(
            """
            WITH eligible AS (
                SELECT e.*
                FROM semantic.api4_runner_event_v2 e
                JOIN canonical.runner_result rr
                  ON rr.source_staging_row_id = e.staging_row_id
                JOIN analytics.fact_race fr USING (race_id)
                WHERE fr.is_market_eligible AND rr.is_valid_start
            )
            SELECT
              count(*) FILTER (WHERE meet_code=3 AND race_time_seconds IS NOT NULL
                                AND bu_g3f_acc_time_seconds IS NOT NULL
                                AND bu_g3f_to_finish_seconds IS NOT NULL) busan_g3f_comparable,
              count(*) FILTER (WHERE meet_code=3 AND race_time_seconds IS NOT NULL
                                AND bu_g3f_acc_time_seconds IS NOT NULL
                                AND bu_g3f_to_finish_seconds IS NOT NULL
                                AND abs((race_time_seconds-bu_g3f_acc_time_seconds)
                                        -bu_g3f_to_finish_seconds)>0.0001) busan_g3f_mismatch,
              max(abs((race_time_seconds-bu_g3f_acc_time_seconds)
                      -bu_g3f_to_finish_seconds)) FILTER (WHERE meet_code=3) busan_g3f_max_diff,
              count(*) FILTER (WHERE meet_code=3 AND race_time_seconds IS NOT NULL
                                AND bu_g1f_acc_time_seconds IS NOT NULL
                                AND bu_g1f_to_finish_seconds IS NOT NULL) busan_g1f_comparable,
              count(*) FILTER (WHERE meet_code=3 AND race_time_seconds IS NOT NULL
                                AND bu_g1f_acc_time_seconds IS NOT NULL
                                AND bu_g1f_to_finish_seconds IS NOT NULL
                                AND abs((race_time_seconds-bu_g1f_acc_time_seconds)
                                        -bu_g1f_to_finish_seconds)>0.0001) busan_g1f_mismatch,
              max(abs((race_time_seconds-bu_g1f_acc_time_seconds)
                      -bu_g1f_to_finish_seconds)) FILTER (WHERE meet_code=3) busan_g1f_max_diff,
              count(*) FILTER (
                  WHERE meet_code=1 AND historical_g3f_seconds IS NOT NULL
                    AND historical_g3f_seconds != race_time_seconds-se_g3f_acc_time_seconds
              )
                  seoul_g3f_semantic_mismatch,
              count(*) FILTER (
                  WHERE meet_code=1 AND historical_g1f_seconds IS NOT NULL
                    AND historical_g1f_seconds != race_time_seconds-se_g1f_acc_time_seconds
              )
                  seoul_g1f_semantic_mismatch
            FROM eligible
            """
        ).fetchone()
        assert normalization is not None
        pit_result = connection.execute(
            f"SELECT count(*) FROM {SNAPSHOT} WHERE source_max_event_date >= feature_as_of"
        ).fetchone()
        assert pit_result is not None
        pit_violations = int(pit_result[0])
        snapshot_result = connection.execute(
            f"SELECT count(*), count(DISTINCT race_id) FROM {SNAPSHOT}"
        ).fetchone()
        assert snapshot_result is not None
        snapshot_rows, snapshot_races = snapshot_result

    roles: dict[str, int] = {}
    for row in inventory:
        roles[row["modeling_role"]] = roles.get(row["modeling_role"], 0) + 1
    summary = {
        "version": VERSION,
        "snapshot_rows": int(snapshot_rows),
        "snapshot_races": int(snapshot_races),
        "speed_sectional_snapshot_features": len(lineage),
        "speed_sectional_model_inputs": sum(
            row["current_modeling_role"] == "MODEL_INPUT" for row in lineage
        ),
        "modeling_role_counts": roles,
        "pit_violations": pit_violations,
        "busan_g3f_comparable": int(normalization[0]),
        "busan_g3f_mismatch": int(normalization[1]),
        "busan_g3f_max_diff": float(normalization[2] or 0),
        "busan_g1f_comparable": int(normalization[3]),
        "busan_g1f_mismatch": int(normalization[4]),
        "busan_g1f_max_diff": float(normalization[5] or 0),
        "seoul_g3f_semantic_mismatch": int(normalization[6]),
        "seoul_g1f_semantic_mismatch": int(normalization[7]),
        "target_or_model_performance_used": False,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
