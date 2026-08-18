from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from kra_analytics.database import connect_database
from kra_analytics.development_evaluation import verify_sealed_artifacts
from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.feature_bundles import ENGINEERED_TABLE, SOURCE_AUDIT_TABLE
from kra_analytics.improvement_validation_contract import (
    CONTRACT_PATH,
    EXPECTED_FEATURE_HASH,
    validate_improvement_validation_contract,
)
from kra_analytics.modeling import (
    calibration_table,
    evaluate_probabilities,
    fit_sigmoid_calibrator,
)
from kra_analytics.modeling_v2 import (
    TARGET_COLUMN,
    _candidate_monthly_metrics,
    _fit_pipeline,
    _segment_metrics,
    choose_probability_procedure,
    expanding_temporal_oof_v2,
)
from kra_analytics.paths import ProjectPaths

EXPERIMENT_VERSION = "post_baseline_v2_f1_f3_one_time_validation_v1"
EXPECTED_CONTRACT_SHA256 = "3096508623ba4ecff034caac347107161b8c3f1e30b7b46f901511256e02e1b3"
TRAIN_START = date(2023, 1, 1)
VALIDATION_START = date(2024, 7, 1)
VALIDATION_END_EXCLUSIVE = date(2025, 7, 1)
ACCESS_FILE = (
    "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/"
    "validation_access.json"
)
METRIC_NAMES = (
    "macro_log_loss",
    "macro_brier",
    "micro_log_loss",
    "micro_brier",
    "calibration_intercept",
    "calibration_slope",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _preflight(paths: ProjectPaths) -> tuple[dict[str, Any], dict[str, Any]]:
    contract_path = paths.root / CONTRACT_PATH
    observed_contract_hash = _sha256_file(contract_path)
    if observed_contract_hash != EXPECTED_CONTRACT_SHA256:
        raise ValueError("Validation contract SHA256 mismatch")
    contract = validate_improvement_validation_contract(paths)
    candidate = _combined_contract(paths)["F1+F3"]
    if len(candidate.inputs) != 133 or candidate.feature_hash != EXPECTED_FEATURE_HASH:
        raise ValueError("133-Feature implementation contract mismatch")
    if list(candidate.inputs) != contract["candidate"]["feature_order"]:
        raise ValueError("Feature name/order mismatch")
    if contract["validation_access_budget"] != {
        "current_access_count": 0,
        "reserved_accesses": 1,
        "increment_only_when_validation_is_loaded": True,
        "repeat_access_after_candidate_change_allowed": False,
    }:
        raise ValueError("Validation access budget contract mismatch")
    if contract["calibration"]["candidates"] != [
        "logistic_raw",
        "logistic_temporal_oof_sigmoid",
    ]:
        raise ValueError("Calibration candidate contract mismatch")
    if contract["logistic"] != {
        "penalty": "l2",
        "C": 1.0,
        "solver": "lbfgs",
        "max_iter": 2000,
        "class_weight": None,
        "random_state": 20260817,
        "warning_policy": (
            "record sklearn penalty deprecation separately; any ConvergenceWarning fails the run"
        ),
    }:
        raise ValueError("Logistic contract mismatch")
    access_path = paths.root / ACCESS_FILE
    if access_path.exists():
        access = json.loads(access_path.read_text(encoding="utf-8"))
        if int(access.get("access_count", -1)) != 0:
            raise RuntimeError("One-time Validation access has already been consumed")
    protection = json.loads(
        (paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    baseline_hashes = verify_sealed_artifacts(paths, protection["artifacts"])
    path_map = {
        "feature_bundle_registry": paths.root / "docs/post-baseline-v2-feature-bundle-registry.csv",
        "feature_bundle_implementation": paths.root / "src/kra_analytics/feature_bundles.py",
        "m1_result": paths.exports / "modeling/m1_histgradientboosting_development_v1/result.json",
        "independent_bundle_development_result": paths.exports
        / "modeling/post_baseline_v2_feature_bundle_development_v1/result.json",
        "f1_f3_development_result": paths.exports
        / "modeling/post_baseline_v2_f1_f3_combination_development_v1/result.json",
    }
    protected_hashes = {name: _sha256_file(path) for name, path in path_map.items()}
    if protected_hashes != contract["protection"]["other_protected_hashes"]:
        raise ValueError("Protected Feature/development artifact hash mismatch")
    if baseline_hashes != contract["protection"]["sealed_baseline_artifacts"]:
        raise ValueError("Sealed baseline artifact hash mismatch")
    checks = {
        "contract_sha256": observed_contract_hash,
        "feature_count": len(candidate.inputs),
        "feature_hash": candidate.feature_hash,
        "feature_order_matches": True,
        "registry_and_implementation_match": True,
        "preprocessing_contract_matches": True,
        "logistic_contract_matches": True,
        "calibration_contract_matches": True,
        "promotion_rule_present": True,
        "validation_access_count_before": 0,
        "sealed_baseline_hashes": baseline_hashes,
        "other_protected_hashes": protected_hashes,
    }
    return contract, checks


def _consume_access(paths: ProjectPaths, contract_hash: str) -> Path:
    access_path = paths.root / ACCESS_FILE
    if access_path.exists():
        raise RuntimeError("Validation access ledger already exists")
    _write_json(
        access_path,
        {
            "experiment_version": EXPERIMENT_VERSION,
            "access_count": 1,
            "accessed_at_utc": datetime.now(UTC).isoformat(),
            "contract_sha256": contract_hash,
            "status": "ACCESS_STARTED",
            "repeat_access_allowed": False,
        },
    )
    return access_path


def _load_frames(
    paths: ProjectPaths, features: tuple[str, ...]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    columns = (
        "race_id",
        "horse_id",
        "race_date",
        "meet_code",
        "registered_runner_count",
        "race_grade",
        "distance_m",
        *tuple(name for name in features if name not in {
            "meet_code", "registered_runner_count", "race_grade", "distance_m"
        }),
        TARGET_COLUMN,
    )
    query = f"""
        SELECT {", ".join(columns)}
        FROM {ENGINEERED_TABLE}
        WHERE race_date >= ? AND race_date < ?
        ORDER BY race_date, race_id, horse_id
    """
    with connect_database(paths=paths, read_only=True) as connection:
        frame = connection.execute(
            query, [TRAIN_START, VALIDATION_END_EXCLUSIVE]
        ).fetchdf()
        pit_row = connection.execute(
                f"""
                SELECT count(*) FROM {SOURCE_AUDIT_TABLE}
                WHERE feature_as_of >= ? AND feature_as_of < ?
                  AND (f1_source_max_event_date >= feature_as_of
                    OR f2_source_max_event_date >= feature_as_of)
                """,
                [TRAIN_START, VALIDATION_END_EXCLUSIVE],
            ).fetchone()
        if pit_row is None:
            raise ValueError("PIT audit query returned no row")
        pit_violations = int(pit_row[0])
    frame["race_date"] = pd.to_datetime(frame["race_date"]).dt.date
    if frame.empty or frame["race_date"].min() < TRAIN_START:
        raise ValueError("Validation loader returned an invalid lower boundary")
    if frame["race_date"].max() >= VALIDATION_END_EXCLUSIVE:
        raise ValueError("Validation loader crossed 2025-07-01")
    if frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate race/horse Validation grain")
    train = frame.loc[frame["race_date"] < VALIDATION_START].copy()
    validation = frame.loc[frame["race_date"] >= VALIDATION_START].copy()
    if train.empty or validation.empty:
        raise ValueError("Train or Validation partition is empty")
    if train["race_date"].max() >= validation["race_date"].min():
        raise ValueError("Train/Validation temporal ordering violation")
    audit = {
        "loaded_min_date": str(frame["race_date"].min()),
        "loaded_max_date": str(frame["race_date"].max()),
        "rows_at_or_after_2025_07_01": 0,
        "duplicate_business_keys": 0,
        "historical_pit_violations": pit_violations,
        "train_validation_ordering": True,
    }
    if pit_violations:
        raise ValueError(f"Historical PIT violations={pit_violations}")
    return train, validation, audit


def _metrics(frame: pd.DataFrame, probabilities: np.ndarray) -> dict[str, Any]:
    return asdict(evaluate_probabilities(frame, probabilities))


def _relative_comparison(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for metric in METRIC_NAMES[:4]:
        base_value = float(baseline[metric])
        candidate_value = float(candidate[metric])
        result[metric] = {
            "candidate_minus_b0": candidate_value - base_value,
            "relative_reduction_percent": (base_value - candidate_value) / base_value * 100,
        }
    return result


def _monthly_comparison(monthly: list[dict[str, Any]], selected: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    months = sorted({str(row["year_month"]) for row in monthly})
    for month in months:
        base = next(
            row for row in monthly if row["candidate"] == "B0" and row["year_month"] == month
        )
        candidate = next(
            row
            for row in monthly
            if row["candidate"] == selected and row["year_month"] == month
        )
        rows.append(
            {
                "year_month": month,
                "b0_macro_log_loss": base["macro_log_loss"],
                "candidate_macro_log_loss": candidate["macro_log_loss"],
                "delta_macro_log_loss": float(candidate["macro_log_loss"])
                - float(base["macro_log_loss"]),
                "macro_log_loss_improved": bool(
                    candidate["macro_log_loss"] < base["macro_log_loss"]
                ),
                "b0_macro_brier": base["macro_brier"],
                "candidate_macro_brier": candidate["macro_brier"],
                "delta_macro_brier": float(candidate["macro_brier"])
                - float(base["macro_brier"]),
                "macro_brier_improved": bool(
                    candidate["macro_brier"] < base["macro_brier"]
                ),
            }
        )
    return rows


def _promotion_decision(
    b0: dict[str, Any], selected_metrics: dict[str, Any], monthly: list[dict[str, Any]]
) -> dict[str, Any]:
    ll_overall = selected_metrics["macro_log_loss"] < b0["macro_log_loss"]
    brier_overall = selected_metrics["macro_brier"] < b0["macro_brier"]
    ll_months = sum(bool(row["macro_log_loss_improved"]) for row in monthly)
    brier_months = sum(bool(row["macro_brier_improved"]) for row in monthly)
    minimum_months = int(np.ceil(len(monthly) / 2))
    if (
        ll_overall
        and brier_overall
        and ll_months >= minimum_months
        and brier_months >= minimum_months
    ):
        decision = "PROMOTE"
        reason = "both aggregate Macro metrics and monthly repetition rules passed"
    elif ll_overall or brier_overall:
        decision = "CONDITIONAL"
        reason = "aggregate or monthly repetition requirements were only partially met"
    else:
        decision = "REJECT"
        reason = "neither aggregate Macro metric improved versus B0"
    return {
        "decision": decision,
        "reason": reason,
        "macro_log_loss_improved_overall": bool(ll_overall),
        "macro_brier_improved_overall": bool(brier_overall),
        "macro_log_loss_improved_months": ll_months,
        "macro_brier_improved_months": brier_months,
        "observed_months": len(monthly),
        "minimum_improved_months": minimum_months,
    }


def run_one_time_improvement_validation(
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contract, preflight = _preflight(project_paths)
    contracts = _combined_contract(project_paths)
    base_contract = contracts["B0"]
    candidate_contract = contracts["F1+F3"]
    access_path = _consume_access(project_paths, preflight["contract_sha256"])
    output = access_path.parent
    try:
        train, validation, data_audit = _load_frames(
            project_paths, candidate_contract.inputs
        )
        b0_pipeline, b0_convergence = _fit_pipeline(train, base_contract)
        b0_probabilities = cast(
            np.ndarray,
            b0_pipeline.predict_proba(validation.loc[:, base_contract.inputs])[:, 1],
        )
        candidate_pipeline, candidate_convergence = _fit_pipeline(
            train, candidate_contract
        )
        raw_probabilities = cast(
            np.ndarray,
            candidate_pipeline.predict_proba(
                validation.loc[:, candidate_contract.inputs]
            )[:, 1],
        )
        oof_probabilities, oof_folds = expanding_temporal_oof_v2(
            train, candidate_contract
        )
        calibrator = fit_sigmoid_calibrator(
            train.loc[oof_probabilities.index, TARGET_COLUMN],
            oof_probabilities.to_numpy(),
        )
        sigmoid_probabilities = calibrator.predict(raw_probabilities)
        probabilities = {
            "B0": b0_probabilities,
            "f1_f3_logistic_raw": raw_probabilities,
            "f1_f3_logistic_sigmoid": sigmoid_probabilities,
        }
        metrics = {
            name: _metrics(validation, values) for name, values in probabilities.items()
        }
        selection_input = {
            "logistic_raw": metrics["f1_f3_logistic_raw"],
            "logistic_sigmoid": metrics["f1_f3_logistic_sigmoid"],
        }
        selected_short, selection_reason = choose_probability_procedure(selection_input)
        selected = (
            "f1_f3_logistic_sigmoid"
            if selected_short == "logistic_sigmoid"
            else "f1_f3_logistic_raw"
        )
        baseline_contract = json.loads(
            (
                project_paths.exports
                / "modeling/official_place_logistic_baseline_v2/run_contract.json"
            ).read_text(encoding="utf-8")
        )
        stored_b0 = baseline_contract["validation_metrics"]["logistic_raw"]
        for metric in METRIC_NAMES:
            stored = stored_b0[metric]
            observed = metrics["B0"][metric]
            if stored is None or observed is None:
                if stored != observed:
                    raise ValueError(f"B0 stored metric mismatch: {metric}")
            elif not np.isclose(float(stored), float(observed), rtol=0.0, atol=1e-12):
                raise ValueError(f"B0 stored metric mismatch: {metric}")
        monthly_metrics = _candidate_monthly_metrics(validation, probabilities)
        monthly_comparison = _monthly_comparison(monthly_metrics, selected)
        segment_metrics = _segment_metrics(validation, probabilities)
        decision = _promotion_decision(
            metrics["B0"], metrics[selected], monthly_comparison
        )
        comparison = _relative_comparison(metrics["B0"], metrics[selected])
        calibration_rows: list[dict[str, Any]] = []
        for name, values in probabilities.items():
            calibration_rows.extend(
                {"candidate": name, **row}
                for row in calibration_table(validation, values)
            )
        protected_after = {
            name: _sha256_file(project_paths.root / relative)
            for name, relative in {
                "run_contract": (
                    "data/exports/modeling/official_place_logistic_baseline_v2/"
                    "run_contract.json"
                ),
                "refit_artifact": (
                    "data/exports/modeling/official_place_logistic_baseline_v2/"
                    "refit_artifact.joblib"
                ),
            }.items()
        }
        expected_baseline = {
            Path(path).stem.replace("run_contract", "run_contract"): value
            for path, value in contract["protection"]["sealed_baseline_artifacts"].items()
        }
        if set(protected_after.values()) != set(expected_baseline.values()):
            raise ValueError("Sealed baseline artifact changed during Validation")
        result: dict[str, Any] = {
            "experiment_version": EXPERIMENT_VERSION,
            "contract_sha256": preflight["contract_sha256"],
            "preflight": preflight,
            "access_count_before": 0,
            "access_count_after": 1,
            "train": {
                "start": str(train["race_date"].min()),
                "end": str(train["race_date"].max()),
                "rows": len(train),
                "races": int(train["race_id"].nunique()),
            },
            "validation": {
                "start": str(validation["race_date"].min()),
                "end": str(validation["race_date"].max()),
                "rows": len(validation),
                "races": int(validation["race_id"].nunique()),
                "months": int(pd.to_datetime(validation["race_date"]).dt.to_period("M").nunique()),
            },
            "metrics": metrics,
            "raw_vs_sigmoid": {
                "selected": selected,
                "reason": selection_reason,
            },
            "selected_vs_b0": comparison,
            "monthly_improvement": monthly_comparison,
            "promotion": decision,
            "oof_folds": oof_folds,
            "calibrator": asdict(calibrator),
            "data_and_leakage_audit": {
                **data_audit,
                "b0_convergence_warnings": b0_convergence,
                "candidate_convergence_warnings": candidate_convergence,
                "oof_temporal_ordering_violations": sum(
                    fold["train_end"] >= fold["prediction_start"] for fold in oof_folds
                ),
                "preprocessing_fit_scope": "Train only; OOF fold-train only",
                "validation_preprocessing_fit": False,
                "post_2025_07_access": False,
            },
            "protected_artifacts_unchanged": True,
            "train_plus_validation_refit_performed": False,
            "post_selection_temporal_evaluation_performed": False,
        }
        _write_json(output / "result.json", result)
        _write_csv(output / "overall_metrics.csv", [
            {"candidate": name, **values} for name, values in metrics.items()
        ])
        _write_csv(output / "monthly_metrics.csv", monthly_metrics)
        _write_csv(output / "monthly_selected_vs_b0.csv", monthly_comparison)
        _write_csv(output / "segment_metrics.csv", segment_metrics)
        _write_csv(output / "calibration_table.csv", calibration_rows)
        _write_csv(output / "train_oof_folds.csv", oof_folds)
        access = json.loads(access_path.read_text(encoding="utf-8"))
        access.update(
            {
                "status": "COMPLETED",
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "selected_probability_procedure": selected,
                "promotion_decision": decision["decision"],
            }
        )
        _write_json(access_path, access)
        return result
    except Exception as error:
        access = json.loads(access_path.read_text(encoding="utf-8"))
        access.update(
            {
                "status": "FAILED_AFTER_ACCESS",
                "failed_at_utc": datetime.now(UTC).isoformat(),
                "error_type": type(error).__name__,
                "error_message": str(error),
            }
        )
        _write_json(access_path, access)
        raise
