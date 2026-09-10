# SQL and contract paths remain readable as complete expressions.
# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from kra_analytics.experiment_database import (
    connect_source_database,
    resolve_experiment_database_paths,
)
from kra_analytics.feature_bundles import ENGINEERED_TABLE
from kra_analytics.modeling import evaluate_probabilities, fit_sigmoid_calibrator
from kra_analytics.modeling_v2 import (
    TARGET_COLUMN,
    V2FeatureContract,
    _fit_pipeline,
    expanding_temporal_oof_v2,
)
from kra_analytics.paths import ProjectPaths
from kra_analytics.race_aware_experiment import ranking_metrics
from kra_analytics.relative_experiment import (
    EXPECTED_LR1_HASH,
    EXPECTED_LT1_HASH,
    _contracts,
)
from kra_analytics.relative_features import (
    RELATIVE_FEATURES,
    SOURCE_BY_FEATURE,
    average_rank_percentiles,
)
from kra_analytics.trend_features import METRIC_TO_FEATURE

EXPERIMENT_VERSION = "post_baseline_v2_relative_r1_validation_reproduction_v1"
CONTRACT_PATH = "docs/post-baseline-v2-relative-r1-validation-contract.md"
EXPECTED_CONTRACT_SHA256 = "831c468b5906fd6f5b49b1ebe0c34a4307b3ade571c36ef5d65fbfdc970c17d8"
TRAIN_START = date(2023, 1, 1)
VALIDATION_START = date(2024, 7, 1)
VALIDATION_END_EXCLUSIVE = date(2025, 7, 1)
OUTPUT_RELATIVE = f"data/exports/modeling/{EXPERIMENT_VERSION}"
ACCESS_FILE = f"{OUTPUT_RELATIVE}/validation_access.json"
RESUME_ACCESS_FILE = f"{OUTPUT_RELATIVE}/resume_access.json"
SECOND_RESUME_ACCESS_FILE = f"{OUTPUT_RELATIVE}/resume2_access.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _preflight(
    paths: ProjectPaths, *, authorized_resume: bool = False
) -> tuple[dict[str, V2FeatureContract], dict[str, str]]:
    contract_path = paths.root / CONTRACT_PATH
    if _sha(contract_path) != EXPECTED_CONTRACT_SHA256:
        raise ValueError("LR1 Validation contract SHA256 mismatch")
    contracts = _contracts(paths)
    if contracts["LT1"].feature_hash != EXPECTED_LT1_HASH:
        raise ValueError("LT1 hash mismatch")
    if contracts["LR1"].feature_hash != EXPECTED_LR1_HASH:
        raise ValueError("LR1 hash mismatch")
    if len(contracts["LT1"].inputs) != 137 or len(contracts["LR1"].inputs) != 144:
        raise ValueError("LT1/LR1 Feature count mismatch")
    protected = {
        "contract": contract_path,
        "r1_registry": paths.root / "docs/post-baseline-v2-relative-r1-registry.csv",
        "r1_code": paths.root / "src/kra_analytics/relative_features.py",
        "development_result": paths.root
        / "data/exports/modeling/post_baseline_v2_relative_r1_development_v1/result.json",
    }
    missing = [name for name, path in protected.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Protected LR1 files missing: {missing}")
    access_path = paths.root / ACCESS_FILE
    if access_path.exists():
        access = json.loads(access_path.read_text(encoding="utf-8"))
        resume_path = paths.root / RESUME_ACCESS_FILE
        second_resume_path = paths.root / SECOND_RESUME_ACCESS_FILE
        resume = (
            json.loads(resume_path.read_text(encoding="utf-8"))
            if resume_path.exists()
            else None
        )
        resumable = (
            authorized_resume
            and access.get("status") == "FAILED_AFTER_ACCESS"
            and (
                not resume_path.exists()
                or (
                    resume is not None
                    and resume.get("status") == "FAILED_BEFORE_DATA_ACCESS"
                    and not second_resume_path.exists()
                )
            )
            and not (access_path.parent / "result.json").exists()
        )
        if not resumable:
            raise RuntimeError("LR1 Validation reproduction access has already been consumed")
    return contracts, {name: _sha(path) for name, path in protected.items()}


def _consume_access(paths: ProjectPaths, *, authorized_resume: bool = False) -> Path:
    initial_path = paths.root / ACCESS_FILE
    first_resume = paths.root / RESUME_ACCESS_FILE
    if not authorized_resume:
        path = initial_path
        attempt_count = 1
    elif not first_resume.exists():
        path = first_resume
        attempt_count = 2
    else:
        path = paths.root / SECOND_RESUME_ACCESS_FILE
        attempt_count = 3
    _write_json(
        path,
        {
            "experiment_version": EXPERIMENT_VERSION,
            "access_count": 1,
            "attempt_count": attempt_count,
            "access_type": "PREVIOUSLY_EXPOSED_VALIDATION_REPRODUCTION",
            "accessed_at_utc": datetime.now(UTC).isoformat(),
            "fresh_test": False,
            "post_2025_07_access_allowed": False,
            "authorized_resume_after_pre_query_parse_failure": authorized_resume,
            "initial_failure_ledger_preserved": str(initial_path) if authorized_resume else None,
            "status": "ACCESS_STARTED",
        },
    )
    return path


def _source_query(columns: tuple[str, ...]) -> str:
    trend_expressions = []
    for metric, feature in METRIC_TO_FEATURE.items():
        sign = "" if metric == "time_percentile" else "-"
        trend_expressions.append(
            f"CASE WHEN count(*) FILTER (WHERE metric='{metric}') >= 3 "
            f"THEN {sign}regr_slope(metric_value, sequence_index) FILTER (WHERE metric='{metric}') "
            f"END AS {feature}"
        )
    selected = ", ".join(f"base.{name}" for name in columns)
    return f"""
WITH event_source AS (
    SELECT b.race_id, b.horse_id, b.race_date,
           rr.result_status, rr.is_valid_start, rr.is_valid_finish,
           e.valid_race_time_seconds AS race_time,
           e.s1f_seconds AS s1f,
           e.historical_g3f_seconds AS g3f,
           e.historical_g1f_seconds AS g1f
    FROM mart.place_feature_snapshot_v2_candidate b
    JOIN canonical.runner_result rr USING (race_id, horse_id)
    JOIN semantic.api4_runner_event_v2 e ON e.staging_row_id = rr.source_staging_row_id
),
f1_ranked AS (
    SELECT race_id, horse_id, race_date, race_time,
           count(*) OVER (PARTITION BY race_id) AS comparison_count,
           rank() OVER (PARTITION BY race_id ORDER BY race_time)
             + (count(*) OVER (PARTITION BY race_id, race_time) - 1) / 2.0 AS average_rank
    FROM event_source
    WHERE is_valid_start AND is_valid_finish AND result_status='FINISHED'
      AND race_time IS NOT NULL AND race_time > 0
),
metric_events AS (
    SELECT race_id, horse_id, race_date, 'time_percentile' AS metric,
           (comparison_count-average_rank)/(comparison_count-1) AS metric_value
    FROM f1_ranked WHERE comparison_count >= 3
    UNION ALL SELECT race_id,horse_id,race_date,'s1f',s1f FROM event_source
      WHERE is_valid_start AND is_valid_finish AND result_status='FINISHED' AND s1f IS NOT NULL
    UNION ALL SELECT race_id,horse_id,race_date,'g3f',g3f FROM event_source
      WHERE is_valid_start AND is_valid_finish AND result_status='FINISHED' AND g3f IS NOT NULL
    UNION ALL SELECT race_id,horse_id,race_date,'g1f',g1f FROM event_source
      WHERE is_valid_start AND is_valid_finish AND result_status='FINISHED' AND g1f IS NOT NULL
),
current_rows AS (
    SELECT race_id,horse_id,feature_as_of FROM {ENGINEERED_TABLE}
    WHERE race_date>=DATE '{TRAIN_START}' AND race_date<DATE '{VALIDATION_END_EXCLUSIVE}'
),
ranked_history AS (
    SELECT cur.race_id,cur.horse_id,cur.feature_as_of,
           hist.race_id historical_race_id,hist.race_date historical_race_date,
           hist.metric,hist.metric_value,
           row_number() OVER (
             PARTITION BY cur.race_id,cur.horse_id,hist.metric
             ORDER BY hist.race_date DESC,hist.race_id DESC
           ) recency_rank
    FROM current_rows cur JOIN metric_events hist
      ON hist.horse_id=cur.horse_id AND hist.race_date<cur.feature_as_of
),
recent_five AS (
    SELECT *, row_number() OVER (
      PARTITION BY race_id,horse_id,metric ORDER BY historical_race_date,historical_race_id
    ) - 1 AS sequence_index
    FROM ranked_history WHERE recency_rank<=5
),
trends AS (
    SELECT race_id,horse_id,{', '.join(trend_expressions)},
           max(historical_race_date) t1_source_max_event_date
    FROM recent_five GROUP BY race_id,horse_id
)
SELECT {selected},{', '.join('trends.' + name for name in METRIC_TO_FEATURE.values())},
       trends.t1_source_max_event_date
FROM {ENGINEERED_TABLE} base
LEFT JOIN trends USING (race_id,horse_id)
WHERE base.race_date>=DATE '{TRAIN_START}' AND base.race_date<DATE '{VALIDATION_END_EXCLUSIVE}'
ORDER BY base.race_date,base.race_id,base.horse_id
"""


def _load_frame(paths: ProjectPaths, contract: V2FeatureContract) -> pd.DataFrame:
    base_columns = tuple(
        dict.fromkeys(("race_id", "horse_id", "race_date", "feature_as_of", *contract.inputs, TARGET_COLUMN))
    )
    derived = {*METRIC_TO_FEATURE.values(), *RELATIVE_FEATURES}
    query_columns = tuple(name for name in base_columns if name not in derived)
    databases = resolve_experiment_database_paths(paths=paths)
    with connect_source_database(database_paths=databases) as connection:
        frame = connection.execute(_source_query(query_columns)).fetchdf()
    frame["race_date"] = pd.to_datetime(frame["race_date"]).dt.date
    frame["feature_as_of"] = pd.to_datetime(frame["feature_as_of"]).dt.date
    source_dates = pd.to_datetime(frame["t1_source_max_event_date"]).dt.date
    if (source_dates.notna() & (source_dates >= frame["feature_as_of"])).any():
        raise ValueError("T1 historical PIT violation")
    for feature, source in SOURCE_BY_FEATURE.items():
        frame[feature] = frame.groupby("race_id", sort=False, observed=True)[source].transform(
            average_rank_percentiles
        )
    if frame.empty or frame["race_date"].min() < TRAIN_START:
        raise ValueError("Invalid lower date boundary")
    if frame["race_date"].max() >= VALIDATION_END_EXCLUSIVE:
        raise ValueError("Loader crossed unopened 2025-07 boundary")
    if frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate runner key")
    missing = set(contract.inputs) - set(frame.columns)
    if missing:
        raise ValueError(f"Validation Feature columns missing: {sorted(missing)}")
    return frame


def _candidate_result(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    contract: V2FeatureContract,
) -> dict[str, Any]:
    pipeline, convergence = _fit_pipeline(train, contract)
    raw = cast(np.ndarray, pipeline.predict_proba(validation.loc[:, contract.inputs])[:, 1])
    oof, folds = expanding_temporal_oof_v2(train, contract)
    calibrator = fit_sigmoid_calibrator(
        train.loc[oof.index, TARGET_COLUMN], oof.to_numpy(dtype=float)
    )
    probability = calibrator.predict(raw)
    return {
        "metrics": asdict(evaluate_probabilities(validation, probability)),
        "ranking": ranking_metrics(validation, probability),
        "calibrator": asdict(calibrator),
        "oof_folds": folds,
        "convergence_warnings": convergence,
    }


def _decision(lt1: dict[str, Any], lr1: dict[str, Any]) -> dict[str, Any]:
    ll_delta = float(lr1["metrics"]["macro_log_loss"]) - float(lt1["metrics"]["macro_log_loss"])
    brier_delta = float(lr1["metrics"]["macro_brier"]) - float(lt1["metrics"]["macro_brier"])
    reproduced = ll_delta < 0 and brier_delta < 0
    return {
        "judgement": "REPRODUCE_R1" if reproduced else "FAIL_TO_REPRODUCE_R1",
        "delta_macro_log_loss": ll_delta,
        "delta_macro_brier": brier_delta,
    }


def run_r1_validation_reproduction(
    paths: ProjectPaths | None = None, *, authorized_resume: bool = False
) -> dict[str, Any]:
    project = paths or ProjectPaths.from_root()
    contracts, protected_before = _preflight(project, authorized_resume=authorized_resume)
    access_path = _consume_access(project, authorized_resume=authorized_resume)
    validation_loaded = False
    try:
        frame = _load_frame(project, contracts["LR1"])
        validation_loaded = True
        train = frame.loc[frame["race_date"] < VALIDATION_START].copy()
        validation = frame.loc[frame["race_date"] >= VALIDATION_START].copy()
        if train["race_date"].max() >= validation["race_date"].min():
            raise ValueError("Train/Validation ordering violation")
        candidates = {
            name: _candidate_result(train, validation, contracts[name])
            for name in ("LT1", "LR1")
        }
        protected_after = {
            name: _sha(path)
            for name, path in {
                "contract": project.root / CONTRACT_PATH,
                "r1_registry": project.root / "docs/post-baseline-v2-relative-r1-registry.csv",
                "r1_code": project.root / "src/kra_analytics/relative_features.py",
                "development_result": project.root
                / "data/exports/modeling/post_baseline_v2_relative_r1_development_v1/result.json",
            }.items()
        }
        if protected_before != protected_after:
            raise ValueError("Protected LR1 artifact changed")
        result = {
            "experiment_version": EXPERIMENT_VERSION,
            "fresh_test": False,
            "interpretation": "reproduction check on a previously exposed Validation period",
            "train": {"rows": len(train), "races": int(train["race_id"].nunique())},
            "validation": {
                "rows": len(validation),
                "races": int(validation["race_id"].nunique()),
                "start": str(validation["race_date"].min()),
                "end": str(validation["race_date"].max()),
            },
            "contracts": {
                name: {"feature_count": len(contract.inputs), "feature_hash": contract.feature_hash}
                for name, contract in contracts.items()
            },
            "candidates": candidates,
            "decision": _decision(candidates["LT1"], candidates["LR1"]),
            "access_count": 1,
            "attempt_count": 3
            if access_path.name == Path(SECOND_RESUME_ACCESS_FILE).name
            else 2
            if authorized_resume
            else 1,
            "validation_reaccess_type": "PREVIOUSLY_EXPOSED_VALIDATION_REPRODUCTION",
            "authorized_resume_after_pre_query_parse_failure": authorized_resume,
            "post_2025_07_rows_loaded": 0,
            "protected_artifacts_unchanged": True,
            "protected_sha256": protected_after,
        }
        _write_json(access_path.parent / "result.json", result)
        _write_json(
            access_path,
            {
                "experiment_version": EXPERIMENT_VERSION,
                "access_count": 1,
                "attempt_count": 3
                if access_path.name == Path(SECOND_RESUME_ACCESS_FILE).name
                else 2
                if authorized_resume
                else 1,
                "access_type": "PREVIOUSLY_EXPOSED_VALIDATION_REPRODUCTION",
                "fresh_test": False,
                "post_2025_07_access_allowed": False,
                "authorized_resume_after_pre_query_parse_failure": authorized_resume,
                "initial_failure_ledger_preserved": str(project.root / ACCESS_FILE)
                if authorized_resume
                else None,
                "status": "COMPLETED",
            },
        )
        return result
    except Exception:
        payload = json.loads(access_path.read_text(encoding="utf-8"))
        if validation_loaded:
            payload["status"] = "FAILED_AFTER_DATA_ACCESS"
        else:
            payload["status"] = "FAILED_BEFORE_DATA_ACCESS"
            payload["access_count"] = 0
        _write_json(access_path, payload)
        raise
