# SQL fragments intentionally remain readable as complete expressions.
# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from duckdb import DuckDBPyConnection

from kra_analytics.database import connect_database, initialize_database
from kra_analytics.development_evaluation import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_FOLDS,
    verify_sealed_artifacts,
)
from kra_analytics.development_evaluation import (
    DEVELOPMENT_START as DEVELOPMENT_START_DATE,
)
from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.feature_bundles import ENGINEERED_TABLE
from kra_analytics.paths import ProjectPaths

TREND_TABLE = "mart.place_feature_snapshot_v2_trend_candidate"
SOURCE_AUDIT_TABLE = "quality.post_baseline_v2_trend_source_audit"
REGISTRY_PATH = "docs/post-baseline-v2-historical-trend-feature-registry.csv"
OUTPUT_DIRECTORY = "data/exports/validation/post_baseline_v2_historical_trend"

TREND_FEATURES = (
    "horse_recent5_race_time_percentile_trend_per_start",
    "horse_recent5_s1f_improvement_trend_seconds_per_start",
    "horse_recent5_g3f_improvement_trend_seconds_per_start",
    "horse_recent5_g1f_improvement_trend_seconds_per_start",
)

METRIC_TO_FEATURE = {
    "time_percentile": TREND_FEATURES[0],
    "s1f": TREND_FEATURES[1],
    "g3f": TREND_FEATURES[2],
    "g1f": TREND_FEATURES[3],
}

METRIC_TO_COMPANION = {
    "time_percentile": "horse_recent5_race_relative_time_count",
    "s1f": "horse_recent5_s1f_count",
    "g3f": "horse_recent5_g3f_count",
    "g1f": "horse_recent5_g1f_count",
}


@dataclass(frozen=True)
class TrendFeatureOutcome:
    row_count: int
    race_count: int
    feature_count: int
    audit_issue_count: int
    output_directory: Path


def sequence_slope(values: list[float]) -> float | None:
    """Return OLS slope on x=0..n-1; fewer than three observations are unavailable."""
    if len(values) < 3:
        return None
    x_mean = (len(values) - 1) / 2.0
    y_mean = sum(values) / len(values)
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    return numerator / denominator


def _registry_rows(paths: ProjectPaths) -> list[dict[str, str]]:
    with (paths.root / REGISTRY_PATH).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    names = tuple(row["feature_name"] for row in rows)
    if names != TREND_FEATURES:
        raise ValueError("T1 registry names or order differ from the sealed implementation contract")
    if len(names) != len(set(names)) or len(names) != 4:
        raise ValueError("T1 must contain exactly four unique Features")
    return rows


def trend_feature_hash(paths: ProjectPaths) -> str:
    _registry_rows(paths)
    return hashlib.sha256(("\n".join(TREND_FEATURES) + "\n").encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_files(paths: ProjectPaths) -> dict[str, Path]:
    return {
        "base_feature_registry": paths.root / "docs/place-feature-registry-v2.csv",
        "f1_f2_f3_registry": paths.root / "docs/post-baseline-v2-feature-bundle-registry.csv",
        "f1_f3_implementation": paths.root / "src/kra_analytics/feature_bundles.py",
        "validation_contract": paths.root / "docs/post-baseline-v2-improvement-validation-contract.json",
        "validation_access_ledger": paths.root
        / "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/validation_access.json",
        "promotion_result": paths.root
        / "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/result.json",
        "m1_result": paths.root / "data/exports/modeling/m1_histgradientboosting_development_v1/result.json",
        "h133_result": paths.root
        / "data/exports/modeling/post_baseline_v2_h133_development_v1/result.json",
        "ra1_result": paths.root
        / "data/exports/modeling/post_baseline_v2_ra1_development_v1/result.json",
    }


def _hash_existing_files(paths: ProjectPaths) -> dict[str, str]:
    files = _protected_files(paths)
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Protected files missing: {missing}")
    return {name: _sha256_file(path) for name, path in files.items()}


def _build_source_sql() -> str:
    return f"""
CREATE OR REPLACE TABLE {SOURCE_AUDIT_TABLE} AS
WITH event_source AS (
    SELECT b.race_id, b.horse_id, b.race_date,
           rr.result_status, rr.is_valid_start, rr.is_valid_finish,
           e.valid_race_time_seconds AS race_time,
           e.s1f_seconds AS s1f,
           e.historical_g3f_seconds AS g3f,
           e.historical_g1f_seconds AS g1f
    FROM mart.place_feature_snapshot_v2_candidate b
    JOIN canonical.runner_result rr USING (race_id, horse_id)
    JOIN semantic.api4_runner_event_v2 e
      ON e.staging_row_id = rr.source_staging_row_id
),
f1_ranked AS (
    SELECT race_id, horse_id, race_date, race_time,
           count(*) OVER (PARTITION BY race_id) AS comparison_count,
           rank() OVER (PARTITION BY race_id ORDER BY race_time) +
             (count(*) OVER (PARTITION BY race_id, race_time) - 1) / 2.0 AS average_rank
    FROM event_source
    WHERE is_valid_start AND is_valid_finish AND result_status = 'FINISHED'
      AND race_time IS NOT NULL AND race_time > 0
),
metric_events AS (
    SELECT race_id, horse_id, race_date, 'time_percentile' AS metric,
           (comparison_count - average_rank) / (comparison_count - 1) AS value
    FROM f1_ranked WHERE comparison_count >= 3
    UNION ALL
    SELECT race_id, horse_id, race_date, 's1f', s1f
    FROM event_source
    WHERE is_valid_start AND is_valid_finish AND result_status = 'FINISHED'
      AND s1f IS NOT NULL
    UNION ALL
    SELECT race_id, horse_id, race_date, 'g3f', g3f
    FROM event_source
    WHERE is_valid_start AND is_valid_finish AND result_status = 'FINISHED'
      AND g3f IS NOT NULL
    UNION ALL
    SELECT race_id, horse_id, race_date, 'g1f', g1f
    FROM event_source
    WHERE is_valid_start AND is_valid_finish AND result_status = 'FINISHED'
      AND g1f IS NOT NULL
),
development_current AS (
    SELECT race_id, horse_id, feature_as_of
    FROM {ENGINEERED_TABLE}
    WHERE race_date >= DATE '{DEVELOPMENT_START_DATE}'
      AND race_date < DATE '{DEVELOPMENT_END_EXCLUSIVE}'
),
ranked_history AS (
    SELECT cur.race_id, cur.horse_id, cur.feature_as_of,
           hist.race_id AS historical_race_id,
           hist.race_date AS historical_race_date,
           hist.metric, hist.value,
           row_number() OVER (
             PARTITION BY cur.race_id, cur.horse_id, hist.metric
             ORDER BY hist.race_date DESC, hist.race_id DESC
           ) AS recency_rank
    FROM development_current cur
    JOIN metric_events hist
      ON hist.horse_id = cur.horse_id
     AND hist.race_date < cur.feature_as_of
),
recent_five AS (
    SELECT *, row_number() OVER (
             PARTITION BY race_id, horse_id, metric
             ORDER BY historical_race_date, historical_race_id
           ) - 1 AS sequence_index
    FROM ranked_history
    WHERE recency_rank <= 5
)
SELECT race_id, horse_id, feature_as_of, historical_race_id,
       historical_race_date, metric, value, recency_rank,
       sequence_index::INTEGER AS sequence_index,
       count(*) OVER (PARTITION BY race_id, horse_id, metric)::INTEGER AS valid_count
FROM recent_five;
"""


def _build_candidate_sql() -> str:
    expressions = []
    for metric, feature in METRIC_TO_FEATURE.items():
        sign = "" if metric == "time_percentile" else "-"
        expressions.append(
            f"CASE WHEN count(*) FILTER (WHERE metric='{metric}') >= 3 "
            f"THEN {sign}regr_slope(value, sequence_index) FILTER (WHERE metric='{metric}') "
            f"END AS {feature}"
        )
    return f"""
CREATE OR REPLACE TABLE {TREND_TABLE} AS
WITH trends AS (
    SELECT race_id, horse_id, {', '.join(expressions)}
    FROM {SOURCE_AUDIT_TABLE}
    GROUP BY race_id, horse_id
)
SELECT base.*, {', '.join('trends.' + name for name in TREND_FEATURES)}
FROM {ENGINEERED_TABLE} base
LEFT JOIN trends USING (race_id, horse_id)
WHERE base.race_date >= DATE '{DEVELOPMENT_START_DATE}'
  AND base.race_date < DATE '{DEVELOPMENT_END_EXCLUSIVE}';
"""


def _scalar(connection: DuckDBPyConnection, query: str) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise ValueError("Scalar query returned no row")
    return int(row[0])


def _write_query(connection: DuckDBPyConnection, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(path).replace("'", "''")
    connection.execute(f"COPY ({query}) TO '{escaped}' (HEADER, DELIMITER ',')")


def _profile_query(group_expression: str | None = None) -> str:
    group_select = f"{group_expression} AS period, " if group_expression else "'ALL' AS period, "
    group_by = f" GROUP BY {group_expression}" if group_expression else ""
    where_clause = (
        f" WHERE {group_expression} IS NOT NULL"
        if group_expression is not None and group_expression.startswith("CASE")
        else ""
    )
    queries = []
    for feature in TREND_FEATURES:
        queries.append(
            f"SELECT {group_select}'{feature}' feature_name, count(*) row_count, "
            f"count({feature}) non_null_count, count({feature})::DOUBLE/count(*) availability_rate, "
            f"min({feature}) minimum, quantile_cont({feature},0.01) p01, "
            f"quantile_cont({feature},0.05) p05, quantile_cont({feature},0.25) p25, "
            f"median({feature}) median, quantile_cont({feature},0.75) p75, "
            f"quantile_cont({feature},0.95) p95, quantile_cont({feature},0.99) p99, "
            f"max({feature}) maximum, avg({feature}) mean, stddev_samp({feature}) standard_deviation "
            f"FROM {TREND_TABLE}{where_clause}{group_by}"
        )
    return " UNION ALL ".join(queries) + " ORDER BY period, feature_name"


def _fold_case() -> str:
    clauses = []
    for fold in DEVELOPMENT_FOLDS:
        clauses.append(
            f"WHEN race_date >= DATE '{fold.evaluation_start}' "
            f"AND race_date < DATE '{fold.evaluation_end_exclusive}' THEN '{fold.fold_id}'"
        )
    return "CASE " + " ".join(clauses) + " END"


def _manual_samples(connection: DuckDBPyConnection) -> list[dict[str, Any]]:
    aggregate_rows = connection.execute(
        f"""
        WITH aggregates AS (
            SELECT race_id, horse_id, metric, count(*) n,
                   regr_slope(value, sequence_index) raw_slope
            FROM {SOURCE_AUDIT_TABLE}
            GROUP BY race_id, horse_id, metric HAVING count(*) >= 3
        ), candidates AS (
            SELECT *,
              row_number() OVER (PARTITION BY metric,n ORDER BY race_id,horse_id) rn_count,
              row_number() OVER (PARTITION BY metric ORDER BY raw_slope,race_id,horse_id) rn_low,
              row_number() OVER (PARTITION BY metric ORDER BY raw_slope DESC,race_id,horse_id) rn_high,
              row_number() OVER (PARTITION BY metric ORDER BY abs(raw_slope),race_id,horse_id) rn_flat
            FROM aggregates
        )
        SELECT race_id,horse_id,metric,n FROM candidates
        WHERE (n IN (3,4,5) AND rn_count=1) OR rn_low=1 OR rn_high=1 OR rn_flat=1
        ORDER BY metric,race_id,horse_id
        """
    ).fetchall()
    seen: set[tuple[str, str, str]] = set()
    results: list[dict[str, Any]] = []
    for race_id, horse_id, metric, count in aggregate_rows:
        key = (str(race_id), str(horse_id), str(metric))
        if key in seen:
            continue
        seen.add(key)
        observations = connection.execute(
            f"""
            SELECT historical_race_date,historical_race_id,sequence_index,value
            FROM {SOURCE_AUDIT_TABLE}
            WHERE race_id=? AND horse_id=? AND metric=?
            ORDER BY sequence_index
            """,
            [race_id, horse_id, metric],
        ).fetchall()
        values = [float(row[3]) for row in observations]
        independent_raw = sequence_slope(values)
        assert independent_raw is not None
        expected = independent_raw if metric == "time_percentile" else -independent_raw
        feature = METRIC_TO_FEATURE[str(metric)]
        stored = connection.execute(
            f"SELECT {feature} FROM {TREND_TABLE} WHERE race_id=? AND horse_id=?",
            [race_id, horse_id],
        ).fetchone()
        assert stored is not None and stored[0] is not None
        stored_value = float(stored[0])
        results.append(
            {
                "race_id": race_id,
                "horse_id": horse_id,
                "metric": metric,
                "valid_count": int(count),
                "historical_dates": "|".join(str(row[0]) for row in observations),
                "historical_race_ids": "|".join(str(row[1]) for row in observations),
                "sequence_indices": "|".join(str(row[2]) for row in observations),
                "observation_values": "|".join(f"{float(row[3]):.12g}" for row in observations),
                "independent_raw_slope": independent_raw,
                "independent_feature_value": expected,
                "stored_feature_value": stored_value,
                "absolute_error": abs(expected - stored_value),
                "direction": "positive" if expected > 0 else "negative" if expected < 0 else "flat",
            }
        )
    return results


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def audit_trend_features(
    *, connection: DuckDBPyConnection | None = None,
    paths: ProjectPaths | None = None,
    export: bool = True,
    protected_before: dict[str, str] | None = None,
) -> list[str]:
    project_paths = paths or ProjectPaths.from_root()
    _registry_rows(project_paths)
    owned = connection is None
    context = connect_database(paths=project_paths) if owned else None
    conn = context.__enter__() if context is not None else connection
    assert conn is not None
    try:
        issues: list[str] = []
        base_contract = _combined_contract(project_paths)["F1+F3"]
        base_columns = [str(row[0]) for row in conn.execute(f"DESCRIBE {ENGINEERED_TABLE}").fetchall()]
        trend_columns = [str(row[0]) for row in conn.execute(f"DESCRIBE {TREND_TABLE}").fetchall()]
        expected_columns = base_columns + list(TREND_FEATURES)
        if trend_columns != expected_columns:
            issues.append("candidate schema does not equal existing engineered schema plus ordered T1")
        if len(base_contract.inputs) != 133 or base_contract.feature_hash != "18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182":
            issues.append("L133 contract count/hash mismatch")

        expected_rows = _scalar(
            conn,
            f"SELECT count(*) FROM {ENGINEERED_TABLE} WHERE race_date>=DATE '{DEVELOPMENT_START_DATE}' AND race_date<DATE '{DEVELOPMENT_END_EXCLUSIVE}'",
        )
        candidate_rows = _scalar(conn, f"SELECT count(*) FROM {TREND_TABLE}")
        if candidate_rows != expected_rows:
            issues.append(f"candidate row mismatch={candidate_rows}/{expected_rows}")
        duplicates = _scalar(
            conn,
            f"SELECT count(*)-count(DISTINCT (race_id,horse_id)) FROM {TREND_TABLE}",
        )
        if duplicates:
            issues.append(f"candidate duplicate business keys={duplicates}")

        same_day = _scalar(
            conn,
            f"""
            SELECT count(*) FROM (
              SELECT horse_id,historical_race_date,count(DISTINCT historical_race_id) n
              FROM {SOURCE_AUDIT_TABLE}
              GROUP BY horse_id,historical_race_date HAVING n>1
            )
            """,
        )
        if same_day:
            issues.append(f"same-horse same-date multiple historical events={same_day}")
        pit = _scalar(
            conn,
            f"SELECT count(*) FROM {SOURCE_AUDIT_TABLE} WHERE historical_race_date>=feature_as_of",
        )
        if pit:
            issues.append(f"historical PIT violations={pit}")
        ordering = _scalar(
            conn,
            f"""
            WITH ordered AS (
              SELECT *,lag(historical_race_date) OVER(
                PARTITION BY race_id,horse_id,metric ORDER BY sequence_index) previous_date
              FROM {SOURCE_AUDIT_TABLE}
            )
            SELECT count(*) FROM ordered
            WHERE sequence_index<0 OR sequence_index>=valid_count OR valid_count>5
               OR (previous_date IS NOT NULL AND historical_race_date<=previous_date)
            """,
        )
        if ordering:
            issues.append(f"temporal ordering/recent5 violations={ordering}")

        companion_mismatches: dict[str, int] = {}
        for metric, feature in METRIC_TO_FEATURE.items():
            companion = METRIC_TO_COMPANION[metric]
            invalid_presence = _scalar(
                conn,
                f"""
                WITH counts AS (
                  SELECT race_id,horse_id,count(*) n FROM {SOURCE_AUDIT_TABLE}
                  WHERE metric='{metric}' GROUP BY race_id,horse_id
                )
                SELECT count(*) FROM {TREND_TABLE} t LEFT JOIN counts c USING(race_id,horse_id)
                WHERE (coalesce(n,0)<3 AND {feature} IS NOT NULL)
                   OR (coalesce(n,0)>=3 AND {feature} IS NULL)
                """,
            )
            if invalid_presence:
                issues.append(f"count/NULL contradiction {feature}={invalid_presence}")
            companion_mismatch = _scalar(
                conn,
                f"""
                WITH counts AS (
                  SELECT race_id,horse_id,count(*) n FROM {SOURCE_AUDIT_TABLE}
                  WHERE metric='{metric}' GROUP BY race_id,horse_id
                )
                SELECT count(*) FROM {TREND_TABLE} t LEFT JOIN counts c USING(race_id,horse_id)
                WHERE coalesce(n,0)<>coalesce({companion},0)
                """,
            )
            companion_mismatches[feature] = companion_mismatch
            non_finite = _scalar(
                conn,
                f"SELECT count(*) FROM {TREND_TABLE} WHERE isnan({feature}) OR isinf({feature})",
            )
            if non_finite:
                issues.append(f"non-finite values {feature}={non_finite}")

        samples = _manual_samples(conn)
        bad_manual = sum(float(row["absolute_error"]) > 1e-12 for row in samples)
        if bad_manual:
            issues.append(f"independent slope recalculation mismatches={bad_manual}")
        directions = {(str(row["metric"]), str(row["direction"])) for row in samples}
        for metric in METRIC_TO_FEATURE:
            if (metric, "positive") not in directions or (metric, "negative") not in directions:
                issues.append(f"actual direction samples incomplete for {metric}")

        protected_after = _hash_existing_files(project_paths)
        if protected_before is not None and protected_after != protected_before:
            issues.append("protected file hash changed during T1 build/audit")
        protection = json.loads(
            (project_paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
                encoding="utf-8"
            )
        )
        sealed_hashes = verify_sealed_artifacts(project_paths, protection["artifacts"])

        if export:
            output = project_paths.root / OUTPUT_DIRECTORY
            output.mkdir(parents=True, exist_ok=True)
            _write_query(conn, _profile_query(), output / "feature_profile_overall.csv")
            _write_query(
                conn,
                _profile_query("year(race_date)"),
                output / "feature_profile_by_year.csv",
            )
            _write_query(
                conn,
                _profile_query(_fold_case()),
                output / "feature_profile_by_development_fold.csv",
            )
            _write_csv(output / "independent_slope_recalculation_samples.csv", samples)
            count_parts = []
            for metric, feature in METRIC_TO_FEATURE.items():
                count_parts.append(
                    f"""
                    SELECT '{feature}' feature_name,coalesce(c.actual_count,0) actual_valid_count,
                           count(*) current_runner_rows
                    FROM {TREND_TABLE} t
                    LEFT JOIN (
                      SELECT race_id,horse_id,count(*) actual_count
                      FROM {SOURCE_AUDIT_TABLE} WHERE metric='{metric}'
                      GROUP BY race_id,horse_id
                    ) c USING(race_id,horse_id)
                    GROUP BY coalesce(c.actual_count,0)
                    """
                )
            _write_query(
                conn,
                " UNION ALL ".join(count_parts)
                + " ORDER BY feature_name,actual_valid_count",
                output / "observation_count_distribution.csv",
            )
            mismatch_parts = []
            for metric, feature in METRIC_TO_FEATURE.items():
                companion = METRIC_TO_COMPANION[metric]
                mismatch_parts.append(
                    f"""
                    SELECT '{feature}' feature_name,t.race_id,t.horse_id,
                           (SELECT count(*) FROM {SOURCE_AUDIT_TABLE} s
                            WHERE s.race_id=t.race_id AND s.horse_id=t.horse_id
                              AND s.metric='{metric}') actual_valid_count,
                           coalesce(t.{companion},0) existing_companion_count,
                           t.{feature} feature_value
                    FROM {TREND_TABLE} t
                    WHERE (SELECT count(*) FROM {SOURCE_AUDIT_TABLE} s
                           WHERE s.race_id=t.race_id AND s.horse_id=t.horse_id
                             AND s.metric='{metric}')<>coalesce(t.{companion},0)
                    """
                )
            _write_query(
                conn,
                " UNION ALL ".join(mismatch_parts)
                + " ORDER BY feature_name,race_id,horse_id",
                output / "companion_count_mismatches.csv",
            )
            extreme_parts = []
            for metric, feature in METRIC_TO_FEATURE.items():
                extreme_parts.append(
                    f"""
                    SELECT '{feature}' feature_name,t.race_id,t.horse_id,t.{feature} feature_value,
                           s.historical_race_date,s.historical_race_id,s.sequence_index,s.value source_value
                    FROM {TREND_TABLE} t JOIN {SOURCE_AUDIT_TABLE} s USING(race_id,horse_id)
                    WHERE s.metric='{metric}' AND t.{feature} IN (
                      (SELECT min({feature}) FROM {TREND_TABLE}),
                      (SELECT max({feature}) FROM {TREND_TABLE})
                    )
                    """
                )
            _write_query(
                conn,
                " UNION ALL ".join(extreme_parts) + " ORDER BY feature_name,feature_value,sequence_index",
                output / "extreme_value_source_trace.csv",
            )
            summary: dict[str, Any] = {
                "generated_at": datetime.now().astimezone().isoformat(),
                "candidate_table": TREND_TABLE,
                "source_audit_table": SOURCE_AUDIT_TABLE,
                "development_start": str(DEVELOPMENT_START_DATE),
                "development_end_exclusive": str(DEVELOPMENT_END_EXCLUSIVE),
                "rows": candidate_rows,
                "races": _scalar(conn, f"SELECT count(DISTINCT race_id) FROM {TREND_TABLE}"),
                "trend_feature_count": 4,
                "trend_feature_hash": trend_feature_hash(project_paths),
                "base_l133_feature_count": len(base_contract.inputs),
                "base_l133_feature_hash": base_contract.feature_hash,
                "pit_violations": pit,
                "same_horse_same_date_multiple_events": same_day,
                "temporal_ordering_violations": ordering,
                "manual_recalculation_samples": len(samples),
                "manual_recalculation_max_absolute_error": max(
                    float(row["absolute_error"]) for row in samples
                ),
                "companion_count_mismatches": companion_mismatches,
                "nan_or_inf": sum(
                    _scalar(
                        conn,
                        f"SELECT count(*) FROM {TREND_TABLE} WHERE isnan({feature}) OR isinf({feature})",
                    )
                    for feature in TREND_FEATURES
                ),
                "target_or_prediction_metrics_calculated": False,
                "validation_accessed": False,
                "post_2024_07_evaluation_accessed": False,
                "protected_file_hashes": protected_after,
                "sealed_artifact_hashes": sealed_hashes,
                "issues": issues,
            }
            (output / "audit_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        return issues
    finally:
        if context is not None:
            context.__exit__(None, None, None)


def build_trend_features(*, paths: ProjectPaths | None = None) -> TrendFeatureOutcome:
    project_paths = paths or ProjectPaths.from_root()
    _registry_rows(project_paths)
    protected_before = _hash_existing_files(project_paths)
    initialize_database(paths=project_paths)
    with connect_database(paths=project_paths) as connection:
        connection.execute("BEGIN")
        try:
            connection.execute(_build_source_sql())
            connection.execute(_build_candidate_sql())
            issues = audit_trend_features(
                connection=connection,
                paths=project_paths,
                export=True,
                protected_before=protected_before,
            )
            if issues:
                raise ValueError("; ".join(issues))
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        rows = _scalar(connection, f"SELECT count(*) FROM {TREND_TABLE}")
        races = _scalar(connection, f"SELECT count(DISTINCT race_id) FROM {TREND_TABLE}")
    return TrendFeatureOutcome(
        row_count=rows,
        race_count=races,
        feature_count=4,
        audit_issue_count=0,
        output_directory=project_paths.root / OUTPUT_DIRECTORY,
    )
