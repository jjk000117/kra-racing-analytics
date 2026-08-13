from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from duckdb import DuckDBPyConnection

from kra_analytics.database import connect_database
from kra_analytics.paths import ProjectPaths

TABLE = "mart.place_feature_snapshot_v2_candidate"
OUTPUT_NAME = "place_baseline_v2_temporal_design"
MODELING_START = "2023-01-01"


@dataclass(frozen=True)
class SplitCandidate:
    candidate_id: str
    train_start: str
    train_end_exclusive: str
    validation_start: str
    validation_end_exclusive: str
    evaluation_start: str


CANDIDATES = (
    SplitCandidate(
        "A_REFERENCE_24M_TRAIN_6M_VALIDATION",
        MODELING_START,
        "2025-01-01",
        "2025-01-01",
        "2025-07-01",
        "2025-07-01",
    ),
    SplitCandidate(
        "B_FULL_SEASON_VALIDATION_RECOMMENDED",
        MODELING_START,
        "2024-07-01",
        "2024-07-01",
        "2025-07-01",
        "2025-07-01",
    ),
    SplitCandidate(
        "C_CALENDAR_YEAR_VALIDATION_SHORT_EVALUATION",
        MODELING_START,
        "2025-01-01",
        "2025-01-01",
        "2026-01-01",
        "2026-01-01",
    ),
)


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(dict(row) for row in rows)


def _period_row(
    connection: DuckDBPyConnection,
    candidate_id: str,
    role: str,
    start: str,
    end_exclusive: str,
) -> dict[str, object]:
    result = connection.execute(
        f"""
        WITH scoped AS (
            SELECT * FROM {TABLE}
            WHERE race_date >= CAST(? AS DATE) AND race_date < CAST(? AS DATE)
        )
        SELECT min(race_date), max(race_date), count(DISTINCT strftime(race_date, '%Y-%m')),
               count(DISTINCT month(race_date)), count(DISTINCT race_id), count(*),
               count(*) FILTER (WHERE place_hit), avg(place_hit::INTEGER)
        FROM scoped
        """,
        [start, end_exclusive],
    ).fetchone()
    assert result is not None and result[0] is not None
    return {
        "candidate_id": candidate_id,
        "role": role,
        "start_date": start,
        "end_date": str(result[1]),
        "calendar_month_count": int(result[2]),
        "distinct_month_of_year_count": int(result[3]),
        "covers_all_calendar_months": int(result[3]) == 12,
        "race_count": int(result[4]),
        "runner_row_count": int(result[5]),
        "plc_positive_count": int(result[6]),
        "plc_positive_rate_descriptive_only": round(float(result[7]), 8),
    }


def main() -> None:
    paths = ProjectPaths.from_root()
    output = paths.exports / "validation" / OUTPUT_NAME
    with connect_database(paths=paths, read_only=True) as connection:
        max_row = connection.execute(f"SELECT max(race_date) FROM {TABLE}").fetchone()
        assert max_row is not None and max_row[0] is not None
        max_date = max_row[0]
        end_row = connection.execute("SELECT ?::DATE + 1", [max_date]).fetchone()
        assert end_row is not None
        end_exclusive = str(end_row[0])

        monthly_rows = [
            {
                "month": str(row[0]),
                "race_count": int(row[1]),
                "runner_row_count": int(row[2]),
                "plc_positive_count": int(row[3]),
                "plc_positive_rate_descriptive_only": round(float(row[4]), 8),
            }
            for row in connection.execute(
                f"""
                SELECT strftime(race_date, '%Y-%m'), count(DISTINCT race_id), count(*),
                       count(*) FILTER (WHERE place_hit), avg(place_hit::INTEGER)
                FROM {TABLE} WHERE race_date >= DATE '{MODELING_START}'
                GROUP BY 1 ORDER BY 1
                """
            ).fetchall()
        ]

        meet_rows = [
            {
                "month": str(row[0]),
                "meet_code": int(row[1]),
                "meet_name": "Seoul" if int(row[1]) == 1 else "Busan-Gyeongnam",
                "race_count": int(row[2]),
                "race_share": round(float(row[3]), 8),
                "runner_row_count": int(row[4]),
                "runner_row_share": round(float(row[5]), 8),
            }
            for row in connection.execute(
                f"""
                WITH race_grain AS (
                    SELECT DISTINCT race_id, race_date, meet_code FROM {TABLE}
                    WHERE race_date >= DATE '{MODELING_START}'
                ), race_mix AS (
                    SELECT strftime(race_date, '%Y-%m') AS month_key, meet_code,
                           count(*) AS races
                    FROM race_grain GROUP BY 1, 2
                ), runner_mix AS (
                    SELECT strftime(race_date, '%Y-%m') AS month_key, meet_code,
                           count(*) AS runner_rows
                    FROM {TABLE} WHERE race_date >= DATE '{MODELING_START}' GROUP BY 1, 2
                )
                SELECT r.month_key, r.meet_code, r.races,
                       r.races::DOUBLE / sum(r.races) OVER (PARTITION BY r.month_key),
                       x.runner_rows,
                       x.runner_rows::DOUBLE /
                           sum(x.runner_rows) OVER (PARTITION BY x.month_key)
                FROM race_mix r JOIN runner_mix x USING (month_key, meet_code)
                ORDER BY 1, 2
                """
            ).fetchall()
        ]

        runner_distribution_rows = [
            {
                "month": str(row[0]),
                "race_count": int(row[1]),
                "min_registered_runner_count": int(row[2]),
                "p25_registered_runner_count": float(row[3]),
                "median_registered_runner_count": float(row[4]),
                "p75_registered_runner_count": float(row[5]),
                "max_registered_runner_count": int(row[6]),
            }
            for row in connection.execute(
                f"""
                WITH race_grain AS (
                    SELECT DISTINCT race_id, race_date, registered_runner_count FROM {TABLE}
                    WHERE race_date >= DATE '{MODELING_START}'
                )
                SELECT strftime(race_date, '%Y-%m'), count(*), min(registered_runner_count),
                       quantile_cont(registered_runner_count, 0.25),
                       median(registered_runner_count),
                       quantile_cont(registered_runner_count, 0.75),
                       max(registered_runner_count)
                FROM race_grain GROUP BY 1 ORDER BY 1
                """
            ).fetchall()
        ]

        composition_rows: list[dict[str, object]] = []
        for dimension, column in (("race_grade", "race_grade"), ("distance_m", "distance_m")):
            rows = connection.execute(
                f"""
                WITH race_grain AS (
                    SELECT DISTINCT race_id, race_date, {column} AS dimension_value
                    FROM {TABLE}
                    WHERE race_date >= DATE '{MODELING_START}'
                ), counts AS (
                    SELECT strftime(race_date, '%Y-%m') AS month_key, dimension_value,
                           count(*) AS race_count
                    FROM race_grain GROUP BY 1, 2
                )
                SELECT month_key, dimension_value::VARCHAR, race_count,
                       race_count::DOUBLE /
                           sum(race_count) OVER (PARTITION BY month_key)
                FROM counts ORDER BY 1, race_count DESC, dimension_value
                """
            ).fetchall()
            composition_rows.extend(
                {
                    "month": str(row[0]),
                    "dimension": dimension,
                    "value": str(row[1]),
                    "race_count": int(row[2]),
                    "race_share": round(float(row[3]), 8),
                }
                for row in rows
            )

        candidate_rows: list[dict[str, object]] = []
        for candidate in CANDIDATES:
            candidate_rows.extend(
                (
                    _period_row(
                        connection,
                        candidate.candidate_id,
                        "TRAIN",
                        candidate.train_start,
                        candidate.train_end_exclusive,
                    ),
                    _period_row(
                        connection,
                        candidate.candidate_id,
                        "VALIDATION",
                        candidate.validation_start,
                        candidate.validation_end_exclusive,
                    ),
                    _period_row(
                        connection,
                        candidate.candidate_id,
                        "POST_SELECTION_TEMPORAL_EVALUATION",
                        candidate.evaluation_start,
                        end_exclusive,
                    ),
                )
            )

        monthly_fold_rows = connection.execute(
            f"""
            SELECT strftime(race_date, '%Y-%m') period, count(DISTINCT race_id), count(*)
            FROM {TABLE} WHERE race_date >= DATE '2024-01-01'
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
        quarterly_fold_rows = connection.execute(
            f"""
            SELECT year(race_date)::VARCHAR || '-Q' || quarter(race_date)::VARCHAR period,
                   count(DISTINCT race_id), count(*)
            FROM {TABLE} WHERE race_date >= DATE '2024-01-01'
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
        walk_forward_rows = [
            {
                "evaluation_unit": unit,
                "period": str(row[0]),
                "race_count": int(row[1]),
                "runner_row_count": int(row[2]),
                "is_partial_final_period": str(row[0]) in {"2026-07", "2026-Q3"},
            }
            for unit, rows in (
                ("MONTHLY", monthly_fold_rows),
                ("QUARTERLY", quarterly_fold_rows),
            )
            for row in rows
        ]

        timeline_rows = []
        for row in monthly_rows:
            month = str(row["month"])
            role = (
                "TRAIN"
                if month < "2024-07"
                else "VALIDATION"
                if month < "2025-07"
                else "POST_SELECTION_TEMPORAL_EVALUATION"
            )
            timeline_rows.append(
                {
                    "month": month,
                    "fixed_split_role": role,
                    "walk_forward_role": (
                        "INITIAL_TRAIN" if month < "2024-01" else "EVALUATION_FOLD"
                    ),
                    "historical_warmup_start": "2022-01-01",
                    "modeling_start": MODELING_START,
                }
            )

    _write_csv(output / "monthly_population.csv", monthly_rows)
    _write_csv(output / "monthly_meet_mix.csv", meet_rows)
    _write_csv(output / "monthly_registered_runner_distribution.csv", runner_distribution_rows)
    _write_csv(output / "monthly_grade_distance_mix.csv", composition_rows)
    _write_csv(output / "split_candidates.csv", candidate_rows)
    _write_csv(output / "walk_forward_period_sizes.csv", walk_forward_rows)
    _write_csv(output / "recommended_timeline.csv", timeline_rows)
    summary = {
        "snapshot_table": TABLE,
        "modeling_start": MODELING_START,
        "available_end_date": str(max_date),
        "month_count": len(monthly_rows),
        "candidate_count": len(CANDIDATES),
        "recommended_candidate": "B_FULL_SEASON_VALIDATION_RECOMMENDED",
        "recommended_walk_forward_unit": "MONTHLY_WITH_QUARTERLY_ROLLUP",
        "model_training_or_prediction_performed": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
