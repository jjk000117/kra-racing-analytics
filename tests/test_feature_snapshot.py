from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from kra_analytics.database import connect_database, initialize_database
from kra_analytics.feature_snapshot import audit_feature_snapshot, build_feature_snapshot
from kra_analytics.paths import ProjectPaths


def _project(tmp_path: Path) -> ProjectPaths:
    root = Path(__file__).parents[1]
    for directory in ("ddl", "transforms"):
        target = tmp_path / "sql" / directory
        target.mkdir(parents=True)
        for source in (root / "sql" / directory).glob("*.sql"):
            shutil.copyfile(source, target / source.name)
    return ProjectPaths.from_root(tmp_path)


def _seed_inputs(paths: ProjectPaths) -> None:
    initialize_database(paths=paths)
    now = datetime.now(UTC)
    races = [
        ("2024-01-05|1|R01", "2024-01-05"),
        ("2024-01-12|1|R01", "2024-01-12"),
        ("2024-01-19|1|R01", "2024-01-19"),
    ]
    runner_states = [
        ("2024-01-05|1|R01", "H1", 1, "FINISHED", True, 1),
        ("2024-01-05|1|R01", "H2", 2, "FINISHED", True, 2),
        ("2024-01-12|1|R01", "H1", 1, "RACE_STOPPED", False, None),
        ("2024-01-12|1|R01", "H2", 2, "FINISHED", True, 1),
        ("2024-01-19|1|R01", "H1", 1, "FINISHED", True, 2),
        ("2024-01-19|1|R01", "H2", 2, "DISQUALIFIED", False, None),
    ]
    with connect_database(paths=paths) as connection:
        connection.execute(
            """
            INSERT INTO canonical.transform_run
            (transform_version, race_batch_id, sales_batch_id, policy_version,
             started_at, completed_at, status, race_count, runner_count,
             sales_count, issue_count, winning_payout_count)
            VALUES ('canonical_v2', 'race-batch', 'sales-batch', 'race_status_v1',
                    ?, ?, 'COMPLETED', 3, 6, 0, 0, 4)
            """,
            [now, now],
        )
        connection.execute(
            """
            INSERT INTO analytics.transform_run
            VALUES ('star_v1', 'canonical_v2', ?, ?, 'COMPLETED', 3, 0, 3, 0)
            """,
            [now, now],
        )
        for race_key, (race_id, race_date) in enumerate(races, start=1):
            connection.execute(
                """
                INSERT INTO canonical.race
                (race_id, race_date, meet_code, meet_name, race_no, race_name,
                 race_grade, distance_m, weather, track_condition, runner_count,
                 source_batch_id, policy_version, created_at, race_status)
                VALUES (?, ?::DATE, 1, '서울', 1, '일반', '국6등급', 1200,
                        '맑음', '건조', 2, 'race-batch', 'race_status_v1', ?, 'COMPLETED')
                """,
                [race_id, race_date, now],
            )
            connection.execute(
                """
                INSERT INTO analytics.fact_race
                VALUES (?, ?, strftime(?::DATE, '%Y%m%d')::INTEGER,
                        1, 8, 1, 1200, 2, 'COMPLETED', 7, TRUE, TRUE, 1,
                        'race-batch', 'star_v1', ?)
                """,
                [race_key, race_id, race_date, now],
            )
        for row_number, state in enumerate(runner_states, start=1):
            race_id, horse_id, gate_no, status, valid_finish, finish_rank = state
            staging_id = f"S{row_number}"
            connection.execute(
                """
                INSERT INTO staging.race_result
                (staging_row_id, batch_id, request_id, raw_file_id, raw_sha256,
                 source_row_number, loaded_at, transform_version, source_item_json,
                 rating, ord_parse_valid)
                VALUES (?, 'race-batch', 'request', 'raw-file', 'sha', ?, ?,
                        'staging_v1', '{}', ?, TRUE)
                """,
                [staging_id, row_number, now, str(30 + row_number)],
            )
            connection.execute(
                """
                INSERT INTO canonical.runner_result
                (runner_result_id, race_id, horse_id, jockey_id, trainer_id,
                 gate_no, horse_sex, horse_age, carried_weight, ord_raw,
                 official_finish_rank, result_status, is_valid_start,
                 is_valid_finish, source_staging_row_id, source_batch_id,
                 policy_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, '수', 4, 54.5, ?, ?, ?, TRUE, ?, ?,
                        'race-batch', 'race_status_v1', ?)
                """,
                [
                    f"{race_id}|H{horse_id}",
                    race_id,
                    horse_id,
                    f"J{horse_id}",
                    f"T{horse_id}",
                    gate_no,
                    str(finish_rank or 92),
                    finish_rank,
                    status,
                    valid_finish,
                    staging_id,
                    now,
                ],
            )
        payouts = [
            ("2024-01-05|1|R01", 1, 1),
            ("2024-01-05|1|R01", 2, 2),
            ("2024-01-12|1|R01", 1, 2),
            ("2024-01-19|1|R01", 1, 1),
        ]
        for race_id, combination_no, gate_no in payouts:
            sales_id = f"{race_id}|P연식"
            connection.execute(
                """
                INSERT INTO canonical.winning_payout
                (winning_payout_id, sales_id, race_id, pool_code, combination_no,
                 selection_count, horse_no_1, combination_key, order_matters,
                 confirmed_odds, confirmed_odds_raw, parse_status, parser_version,
                 source_staging_row_id, source_batch_id, created_at)
                VALUES (?, ?, ?, '연식', ?, 1, ?, ?, FALSE, 1.5, '원문', 'PARSED',
                        'winning_payout_v1', ?, 'sales-batch', ?)
                """,
                [
                    f"{sales_id}|{combination_no}",
                    sales_id,
                    race_id,
                    combination_no,
                    gate_no,
                    str(gate_no),
                    f"P{race_id}{combination_no}",
                    now,
                ],
            )


def test_build_feature_snapshot_preserves_pit_and_status_rules(tmp_path: Path) -> None:
    paths = _project(tmp_path)
    _seed_inputs(paths)

    first = build_feature_snapshot(paths=paths)
    second = build_feature_snapshot(paths=paths)

    assert first == second
    assert first.row_count == 6
    assert first.race_count == 3
    assert first.positive_count == 4
    assert first.no_horse_history_count == 2
    assert audit_feature_snapshot(paths=paths) == []

    with connect_database(paths=paths, read_only=True) as connection:
        h1_last = connection.execute(
            """
            SELECT rating, horse_prior_start_count, horse_prior_finish_count,
                   horse_prior_finish_rate, horse_prior_plc_hit_count,
                   horse_prior_plc_hit_rate, horse_recent5_start_count,
                   horse_recent5_finish_rate, source_max_event_date, place_hit
            FROM mart.feature_snapshot_place
            WHERE race_id = '2024-01-19|1|R01' AND horse_id = 'H1'
            """
        ).fetchone()
        statuses = connection.execute(
            """
            SELECT result_status, count(*)
            FROM mart.feature_snapshot_place
            GROUP BY result_status ORDER BY result_status
            """
        ).fetchall()

    assert h1_last == (
        35,
        2,
        1,
        0.5,
        1,
        0.5,
        2,
        0.5,
        datetime(2024, 1, 12).date(),
        True,
    )
    assert statuses == [("DISQUALIFIED", 1), ("FINISHED", 4), ("RACE_STOPPED", 1)]
