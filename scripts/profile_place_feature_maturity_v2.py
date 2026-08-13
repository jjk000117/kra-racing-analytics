from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import cast

from kra_analytics.database import connect_database
from kra_analytics.paths import ProjectPaths

TABLE = "mart.place_feature_snapshot_v2_candidate"
INVENTORY = "docs/official-place-baseline-v2-model-input-inventory.csv"
OUTPUT_NAME = "place_feature_maturity_v2"
PROFILE_END = "2023-07-31"

FAMILY_OBSERVATION_RULES = {
    "horse_long_term": "horse_prior_start_count > 0",
    "recent3_any": "horse_recent3_start_count > 0",
    "recent3_full": "horse_recent3_start_count >= 3",
    "recent5_any": "horse_recent5_start_count > 0",
    "recent5_full": "horse_recent5_start_count >= 5",
    "recent10_any": "horse_recent10_start_count > 0",
    "recent10_full": "horse_recent10_start_count >= 10",
    "same_distance": "horse_same_distance_start_count > 0",
    "same_meet": "horse_same_meet_start_count > 0",
    "speed_race_time": "horse_recent3_race_time_count > 0",
    "sectional_s1f": "horse_recent3_s1f_count > 0",
    "sectional_g3f": "horse_recent3_g3f_count > 0",
    "sectional_g1f": "horse_recent3_g1f_count > 0",
    "horse_weight": "horse_recent5_weight_count > 0",
    "jockey": "jockey_prior_start_count > 0",
    "trainer": "trainer_prior_start_count > 0",
    "owner": "owner_prior_start_count > 0",
    "horse_jockey": "horse_jockey_recent10_start_count > 0",
    "horse_trainer": "horse_trainer_prior_start_count > 0",
}

CANDIDATES = ("2022-07-01", "2023-01-01", "2023-07-01")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _model_inputs(root: Path) -> tuple[list[str], dict[str, list[str]]]:
    with (root / INVENTORY).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    model_rows = [row for row in rows if row["modeling_role"] == "MODEL_INPUT"]
    features = [row["feature_name"] for row in model_rows]
    families: dict[str, list[str]] = defaultdict(list)
    for row in model_rows:
        families[row["feature_family"]].append(row["feature_name"])
    if len(features) != 117 or len(features) != len(set(features)):
        raise ValueError("Expected 117 unique MODEL_INPUT features")
    return features, dict(families)


def main() -> None:
    paths = ProjectPaths.from_root()
    features, feature_families = _model_inputs(paths.root)
    output = paths.exports / "validation" / OUTPUT_NAME
    with connect_database(paths=paths, read_only=True) as connection:
        schema = {str(row[0]) for row in connection.execute(f"DESCRIBE {TABLE}").fetchall()}
        missing = sorted(set(features) - schema)
        if missing:
            raise ValueError(f"MODEL_INPUT columns missing from Snapshot: {missing}")

        sample_rows = [
            {
                "month": str(row[0]),
                "race_count": int(row[1]),
                "runner_row_count": int(row[2]),
                "plc_positive_count": int(row[3]),
                "plc_positive_rate": round(float(row[4]), 8),
            }
            for row in connection.execute(
                f"""
                SELECT strftime(race_date, '%Y-%m') AS month,
                       count(DISTINCT race_id), count(*),
                       count(*) FILTER (WHERE place_hit), avg(place_hit::INTEGER)
                FROM {TABLE}
                WHERE race_date <= DATE '{PROFILE_END}'
                GROUP BY 1 ORDER BY 1
                """
            ).fetchall()
        ]

        availability_rows: list[dict[str, object]] = []
        for feature in features:
            family = next(
                family for family, names in feature_families.items() if feature in names
            )
            rows = connection.execute(
                f"""
                SELECT strftime(race_date, '%Y-%m') AS month, count(*),
                       count({feature}), count(*) - count({feature}),
                       count({feature})::DOUBLE / count(*)
                FROM {TABLE}
                WHERE race_date <= DATE '{PROFILE_END}'
                GROUP BY 1 ORDER BY 1
                """
            ).fetchall()
            availability_rows.extend(
                {
                    "month": str(row[0]),
                    "feature_family": family,
                    "feature_name": feature,
                    "row_count": int(row[1]),
                    "non_null_count": int(row[2]),
                    "null_count": int(row[3]),
                    "non_null_rate": round(float(row[4]), 8),
                }
                for row in rows
            )

        family_rows: list[dict[str, object]] = []
        for family, rule in FAMILY_OBSERVATION_RULES.items():
            rows = connection.execute(
                f"""
                SELECT strftime(race_date, '%Y-%m') AS month, count(*),
                       count(*) FILTER (WHERE {rule}),
                       count(*) FILTER (WHERE {rule})::DOUBLE / count(*)
                FROM {TABLE}
                WHERE race_date <= DATE '{PROFILE_END}'
                GROUP BY 1 ORDER BY 1
                """
            ).fetchall()
            family_rows.extend(
                {
                    "month": str(row[0]),
                    "family_metric": family,
                    "observation_rule": rule,
                    "row_count": int(row[1]),
                    "available_row_count": int(row[2]),
                    "availability_rate": round(float(row[3]), 8),
                }
                for row in rows
            )

        candidate_rows: list[dict[str, object]] = []
        for start_date in CANDIDATES:
            start_month = start_date[:7]
            period = connection.execute(
                f"""
                SELECT count(DISTINCT race_id), count(*), max(race_date)
                FROM {TABLE} WHERE race_date >= CAST(? AS DATE)
                """,
                [start_date],
            ).fetchone()
            assert period is not None
            month_rates = {
                str(row["family_metric"]): cast(float, row["availability_rate"])
                for row in family_rows if row["month"] == start_month
            }
            candidate_rows.append(
                {
                    "modeling_start": start_date,
                    "modeling_end": str(period[2]),
                    "modeling_race_count": int(period[0]),
                    "modeling_runner_row_count": int(period[1]),
                    "horse_long_term_rate_at_start": round(month_rates["horse_long_term"], 8),
                    "recent3_full_rate_at_start": round(month_rates["recent3_full"], 8),
                    "recent5_full_rate_at_start": round(month_rates["recent5_full"], 8),
                    "recent10_full_rate_at_start": round(month_rates["recent10_full"], 8),
                    "same_distance_rate_at_start": round(month_rates["same_distance"], 8),
                    "horse_jockey_rate_at_start": round(month_rates["horse_jockey"], 8),
                    "horse_trainer_rate_at_start": round(month_rates["horse_trainer"], 8),
                }
            )

    _write_csv(output / "monthly_sample.csv", sample_rows)
    _write_csv(output / "monthly_model_input_availability.csv", availability_rows)
    _write_csv(output / "monthly_family_maturity.csv", family_rows)
    family_metrics = list(FAMILY_OBSERVATION_RULES)
    family_lookup = {
        (str(row["month"]), str(row["family_metric"])): row["availability_rate"]
        for row in family_rows
    }
    family_wide_rows = [
        {
            "month": sample["month"],
            **{
                metric: family_lookup[(str(sample["month"]), metric)]
                for metric in family_metrics
            },
        }
        for sample in sample_rows
    ]
    _write_csv(output / "monthly_family_maturity_wide.csv", family_wide_rows)
    _write_csv(output / "modeling_start_candidates.csv", candidate_rows)
    summary = {
        "snapshot_table": TABLE,
        "profile_period": [sample_rows[0]["month"], sample_rows[-1]["month"]],
        "model_input_count": len(features),
        "month_count": len(sample_rows),
        "family_metric_count": len(FAMILY_OBSERVATION_RULES),
        "candidate_count": len(candidate_rows),
        "model_training_or_evaluation_performed": False,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
