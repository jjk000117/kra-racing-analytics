from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "warehouse" / "kra.duckdb"
API26_EVIDENCE = ROOT / "data" / "exports" / "api26_pit_validation.json"
API26_RAW = ROOT / "data" / "raw" / "api26_2_pit_validation"
OUTPUT = ROOT / "data" / "exports" / "api26_ilsu_speed_source_validation.json"

SPEED_FIELDS = (
    "rcTime",
    "diffUnit",
    "weather",
    "track",
    "wgHr",
    "seS1fAccTime",
    "seG3fAccTime",
    "seG1fAccTime",
    "se_1cAccTime",
    "se_2cAccTime",
    "se_3cAccTime",
    "se_4cAccTime",
    "sjS1fOrd",
    "sjG3fOrd",
    "sjG1fOrd",
    "buS1fTime",
    "buS1fAccTime",
    "buG3fAccTime",
    "buG1fAccTime",
    "bu_10_8fTime",
    "bu_8_6fTime",
    "bu_6_4fTime",
    "bu_4_2fTime",
    "bu_3fGTime",
    "bu_2fGTime",
    "bu_1fGTime",
    "buS1fOrd",
    "buG3fOrd",
    "buG1fOrd",
)

API26_OVERLAP_FIELDS = (
    "ilsu",
    "rating",
    "ageCond",
    "sexCond",
    "prizeCond",
    "budam",
    "rcName",
    "chaksun1",
    "chaksun2",
    "chaksun3",
    "chaksun4",
    "chaksun5",
)


def api26_items(document: dict[str, Any]) -> list[dict[str, Any]]:
    raw = document["response"]["body"]["items"]["item"]
    return [raw] if isinstance(raw, dict) else raw


def main() -> None:
    connection = duckdb.connect(str(DATABASE), read_only=True)

    ilsu_day_summary = connection.execute(
        """
        WITH days AS (
            SELECT CASE WHEN meet IN ('1', '서울') THEN 1 ELSE 3 END AS meet_code,
                   try_strptime(rcDate, '%Y%m%d')::DATE AS race_date,
                   try_cast(ilsu AS INTEGER) AS ilsu,
                   count(*) AS row_count,
                   count(DISTINCT coalesce(ilsu, '')) AS ilsu_distinct
            FROM staging.race_result
            WHERE batch_id = (SELECT race_batch_id FROM canonical.transform_run LIMIT 1)
            GROUP BY 1, 2, 3
        ), ranked AS (
            SELECT *, dense_rank() OVER (
                PARTITION BY meet_code, year(race_date) ORDER BY race_date
            ) AS observed_race_day_rank
            FROM days
        )
        SELECT count(*) AS day_count,
               count_if(ilsu_distinct <> 1) AS inconsistent_days,
               count_if(ilsu <> observed_race_day_rank) AS rank_mismatches,
               min(ilsu), max(ilsu)
        FROM ranked
        """
    ).fetchone()
    assert ilsu_day_summary is not None

    ilsu_by_meet_year_rows = connection.execute(
        """
        WITH days AS (
            SELECT CASE WHEN meet IN ('1', '서울') THEN 1 ELSE 3 END AS meet_code,
                   try_strptime(rcDate, '%Y%m%d')::DATE AS race_date,
                   try_cast(ilsu AS INTEGER) AS ilsu
            FROM staging.race_result
            WHERE batch_id = (SELECT race_batch_id FROM canonical.transform_run LIMIT 1)
            GROUP BY 1, 2, 3
        ), ranked AS (
            SELECT *, dense_rank() OVER (
                PARTITION BY meet_code, year(race_date) ORDER BY race_date
            ) AS observed_race_day_rank
            FROM days
        )
        SELECT meet_code, year(race_date) AS race_year, count(*) AS days,
               count_if(ilsu <> observed_race_day_rank) AS rank_mismatches,
               min(ilsu), max(ilsu)
        FROM ranked
        GROUP BY 1, 2
        ORDER BY 2, 1
        """
    ).fetchall()

    ilsu_by_status_rows = connection.execute(
        """
        SELECT rr.result_status, count(*) AS rows,
               count_if(try_cast(s.ilsu AS INTEGER) IS NOT NULL) AS ilsu_present
        FROM canonical.runner_result rr
        JOIN staging.race_result s
          ON s.staging_row_id = rr.source_staging_row_id
        GROUP BY rr.result_status
        ORDER BY rr.result_status
        """
    ).fetchall()

    evidence = json.loads(API26_EVIDENCE.read_text(encoding="utf-8"))
    api26_ilsu_checks: list[dict[str, Any]] = []
    api26_overlap_checks: list[dict[str, Any]] = []
    api26_only_field_values: dict[str, list[Any]] = {"stTime": [], "prd": []}
    for observation in evidence["observations"]:
        prefix = observation["request_id"][:8]
        raw_files = list(API26_RAW.glob(f"*{prefix}.json"))
        if len(raw_files) != 1:
            raise RuntimeError(f"Expected one Raw file for request {prefix}")
        document = json.loads(raw_files[0].read_text(encoding="utf-8"))
        item = next(
            row
            for row in api26_items(document)
            if str(row.get("hrNo")) == str(observation["horse_id"])
        )
        api4_ilsu = connection.execute(
            """
            SELECT try_cast(s.ilsu AS INTEGER)
            FROM canonical.runner_result rr
            JOIN canonical.race r USING (race_id)
            JOIN staging.race_result s
              ON s.staging_row_id = rr.source_staging_row_id
            WHERE rr.horse_id = ? AND r.race_date = ?::DATE
            """,
            [observation["horse_id"], observation["race_date"]],
        ).fetchone()
        assert api4_ilsu is not None
        prior_dates = connection.execute(
            """
            SELECT max(r.race_date) FILTER (WHERE rr.is_valid_start),
                   max(r.race_date) FILTER (WHERE rr.is_valid_finish)
            FROM canonical.runner_result rr
            JOIN canonical.race r USING (race_id)
            WHERE rr.horse_id = ? AND r.race_date < ?::DATE
            """,
            [observation["horse_id"], observation["race_date"]],
        ).fetchone()
        assert prior_dates is not None
        current_date = connection.execute("SELECT ?::DATE", [observation["race_date"]]).fetchone()[
            0
        ]
        prior_start_date, prior_finish_date = prior_dates
        api26_ilsu_checks.append(
            {
                "horse_id": observation["horse_id"],
                "race_date": observation["race_date"],
                "api26_ilsu": int(item["ilsu"]),
                "api4_ilsu": api4_ilsu[0],
                "matches": int(item["ilsu"]) == api4_ilsu[0],
                "prior_valid_start_date": prior_start_date,
                "days_since_prior_valid_start": (
                    (current_date - prior_start_date).days if prior_start_date else None
                ),
                "prior_valid_finish_date": prior_finish_date,
                "days_since_prior_valid_finish": (
                    (current_date - prior_finish_date).days if prior_finish_date else None
                ),
            }
        )

        staging_values = connection.execute(
            f"""
            SELECT {", ".join(f"s.{field}" for field in API26_OVERLAP_FIELDS)}
            FROM canonical.runner_result rr
            JOIN canonical.race r USING (race_id)
            JOIN staging.race_result s
              ON s.staging_row_id = rr.source_staging_row_id
            WHERE rr.horse_id = ? AND r.race_date = ?::DATE
            """,
            [observation["horse_id"], observation["race_date"]],
        ).fetchone()
        assert staging_values is not None
        for field, api4_value in zip(API26_OVERLAP_FIELDS, staging_values, strict=True):
            api26_value = item.get(field)
            api26_overlap_checks.append(
                {
                    "field": field,
                    "horse_id": observation["horse_id"],
                    "race_date": observation["race_date"],
                    "api26_value": api26_value,
                    "api4_value": api4_value,
                    "matches_as_text": str(api26_value).strip() == str(api4_value).strip(),
                }
            )
        for field in api26_only_field_values:
            api26_only_field_values[field].append(item.get(field))

    status_transition_rows = connection.execute(
        """
        WITH ordered AS (
            SELECT rr.horse_id, r.race_id, r.race_date, rr.result_status,
                   try_cast(s.ilsu AS INTEGER) AS ilsu,
                   lag(r.race_date) OVER (
                       PARTITION BY rr.horse_id ORDER BY r.race_date, r.race_id
                   ) AS previous_event_date,
                   lag(rr.result_status) OVER (
                       PARTITION BY rr.horse_id ORDER BY r.race_date, r.race_id
                   ) AS previous_event_status
            FROM canonical.runner_result rr
            JOIN canonical.race r USING (race_id)
            JOIN staging.race_result s
              ON s.staging_row_id = rr.source_staging_row_id
        ), candidates AS (
            SELECT *, row_number() OVER (
                PARTITION BY previous_event_status ORDER BY race_date, horse_id
            ) AS sample_no
            FROM ordered
            WHERE previous_event_status IN ('DNS', 'RACE_STOPPED', 'DISQUALIFIED')
              AND result_status = 'FINISHED'
        )
        SELECT horse_id, race_date, ilsu, previous_event_date,
               previous_event_status,
               date_diff('day', previous_event_date, race_date) AS interval_days
        FROM candidates
        WHERE sample_no = 1
        ORDER BY previous_event_status
        """
    ).fetchall()

    speed_profile: dict[str, dict[str, dict[str, Any]]] = {}
    for meet_code in (1, 3):
        meet_profile: dict[str, dict[str, Any]] = {}
        for field in SPEED_FIELDS:
            row = connection.execute(
                f"""
                SELECT count(*) AS rows,
                       count_if(nullif(trim(s.{field}), '') IS NOT NULL) AS present,
                       count_if(try_cast(nullif(trim(s.{field}), '') AS DOUBLE)
                                IS NOT NULL) AS numeric,
                       count_if(try_cast(nullif(trim(s.{field}), '') AS DOUBLE) = 0)
                           AS numeric_zero,
                       count_if(try_cast(nullif(trim(s.{field}), '') AS DOUBLE) <> 0)
                           AS numeric_nonzero,
                       min(try_cast(nullif(trim(s.{field}), '') AS DOUBLE))
                           FILTER (WHERE try_cast(nullif(trim(s.{field}), '') AS DOUBLE) <> 0),
                       max(try_cast(nullif(trim(s.{field}), '') AS DOUBLE))
                           FILTER (WHERE try_cast(nullif(trim(s.{field}), '') AS DOUBLE) <> 0),
                       list(DISTINCT s.{field} ORDER BY s.{field})
                           FILTER (WHERE nullif(trim(s.{field}), '') IS NOT NULL) [1:5]
                           AS sample_values
                FROM canonical.runner_result rr
                JOIN canonical.race r USING (race_id)
                JOIN staging.race_result s
                  ON s.staging_row_id = rr.source_staging_row_id
                WHERE r.meet_code = ? AND rr.is_valid_start
                  AND r.race_status = 'COMPLETED'
                  AND EXISTS (
                      SELECT 1
                      FROM canonical.winning_payout wp
                      WHERE wp.race_id = r.race_id
                  )
                """,
                [meet_code],
            ).fetchone()
            assert row is not None
            meet_profile[field] = {
                "rows": row[0],
                "present": row[1],
                "numeric": row[2],
                "numeric_zero": row[3],
                "numeric_nonzero": row[4],
                "nonzero_min": row[5],
                "nonzero_max": row[6],
                "sample_values": row[7],
            }
        speed_profile[str(meet_code)] = meet_profile

    connection.close()
    output = {
        "ilsu_day_summary": {
            "day_count": ilsu_day_summary[0],
            "inconsistent_days": ilsu_day_summary[1],
            "dense_rank_mismatches": ilsu_day_summary[2],
            "min_ilsu": ilsu_day_summary[3],
            "max_ilsu": ilsu_day_summary[4],
        },
        "ilsu_by_result_status": [
            {"result_status": row[0], "rows": row[1], "ilsu_present": row[2]}
            for row in ilsu_by_status_rows
        ],
        "ilsu_by_meet_year": [
            {
                "meet_code": row[0],
                "race_year": row[1],
                "days": row[2],
                "dense_rank_mismatches": row[3],
                "min_ilsu": row[4],
                "max_ilsu": row[5],
            }
            for row in ilsu_by_meet_year_rows
        ],
        "api26_ilsu_checks": api26_ilsu_checks,
        "api26_ilsu_match_count": sum(row["matches"] for row in api26_ilsu_checks),
        "status_transition_examples": [
            {
                "horse_id": row[0],
                "race_date": row[1],
                "ilsu": row[2],
                "previous_event_date": row[3],
                "previous_event_status": row[4],
                "interval_days": row[5],
            }
            for row in status_transition_rows
        ],
        "api26_overlap_summary": {
            field: {
                "checks": sum(row["field"] == field for row in api26_overlap_checks),
                "matches": sum(
                    row["field"] == field and row["matches_as_text"] for row in api26_overlap_checks
                ),
            }
            for field in API26_OVERLAP_FIELDS
        },
        "api26_only_field_values": api26_only_field_values,
        "speed_field_profile": speed_profile,
    }
    OUTPUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(output, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
