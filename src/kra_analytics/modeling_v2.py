from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import warnings
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import joblib  # type: ignore[import-untyped]
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # type: ignore[import-untyped]

from kra_analytics.database import connect_database
from kra_analytics.modeling import (
    OOFFold,
    SigmoidCalibrator,
    calibration_table,
    evaluate_probabilities,
    fit_sigmoid_calibrator,
)
from kra_analytics.paths import ProjectPaths

MODEL_VERSION = "official_place_logistic_baseline_v2"
SNAPSHOT_TABLE = "mart.place_feature_snapshot_v2_candidate"
TARGET_COLUMN = "place_hit"
RANDOM_SEED = 20260817
TRAIN_START = date(2023, 1, 1)
VALIDATION_START = date(2024, 7, 1)
POST_SELECTION_START = date(2025, 7, 1)
POST_SELECTION_END = date(2026, 7, 26)
INVENTORY = "docs/official-place-baseline-v2-model-input-inventory.csv"

EXCLUDED_LOGICAL = {
    "horse_recent3_race_time_median",
    "horse_recent5_race_time_median",
}
EXCLUDED_STRUCTURAL = {
    "horse_prior_finish_count",
    "horse_prior_win_count",
    "horse_prior_top3_count",
    "horse_history_available",
    "jockey_history_available",
    "trainer_history_available",
}
ZERO_COUNT_FEATURES = {
    "horse_recent3_race_time_count",
    "horse_recent3_s1f_count",
    "horse_recent3_g3f_count",
    "horse_recent3_g1f_count",
    "horse_recent5_race_time_count",
    "horse_recent5_s1f_count",
    "horse_recent5_g3f_count",
    "horse_recent5_g1f_count",
}
CATEGORICAL_NUMERIC_FEATURES = {"meet_code", "race_day_of_week"}


@dataclass(frozen=True)
class V2FeatureContract:
    inputs: tuple[str, ...]
    categorical: tuple[str, ...]
    numeric: tuple[str, ...]
    zero_count: tuple[str, ...]
    feature_hash: str


@dataclass(frozen=True)
class V2RunOutcome:
    model_version: str
    selected_procedure: str
    train_rows: int
    train_races: int
    validation_rows: int
    validation_races: int
    refit_rows: int
    contract_path: Path
    contract_payload_sha256: str
    post_selection_predictions_created: bool


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_feature_contract(paths: ProjectPaths) -> V2FeatureContract:
    inventory_path = paths.root / INVENTORY
    with inventory_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    model_rows = [row for row in rows if row["modeling_role"] == "MODEL_INPUT"]
    inputs = tuple(row["feature_name"] for row in model_rows)
    if len(inputs) != 117 or len(set(inputs)) != 117:
        raise ValueError("Expected exactly 117 unique MODEL_INPUT features")
    if (EXCLUDED_LOGICAL | EXCLUDED_STRUCTURAL) & set(inputs):
        raise ValueError("Excluded Feature leaked into the v2 model input contract")

    categorical = tuple(
        row["feature_name"]
        for row in model_rows
        if row["data_type"] == "VARCHAR"
        or row["feature_name"] in CATEGORICAL_NUMERIC_FEATURES
    )
    numeric = tuple(name for name in inputs if name not in categorical)
    if not ZERO_COUNT_FEATURES <= set(numeric):
        raise ValueError("Expected zero-observation count Features are missing")
    feature_hash = _sha256_text("\n".join(inputs) + "\n")
    return V2FeatureContract(
        inputs=inputs,
        categorical=categorical,
        numeric=numeric,
        zero_count=tuple(name for name in inputs if name in ZERO_COUNT_FEATURES),
        feature_hash=feature_hash,
    )


def build_v2_pipeline(contract: V2FeatureContract) -> Pipeline:
    median_numeric = tuple(name for name in contract.numeric if name not in contract.zero_count)
    categorical = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    numeric = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    zero_count = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value=0)),
            ("scaler", StandardScaler()),
        ]
    )
    preprocessor = ColumnTransformer(
        transformers=[
            ("categorical", categorical, list(contract.categorical)),
            ("numeric", numeric, list(median_numeric)),
            ("zero_count", zero_count, list(contract.zero_count)),
        ]
    )
    model = LogisticRegression(
        penalty="l2",
        C=1.0,
        solver="lbfgs",
        max_iter=2000,
        class_weight=None,
        random_state=RANDOM_SEED,
    )
    return Pipeline(steps=[("preprocessor", preprocessor), ("model", model)])


def load_v2_development_frame(
    *, paths: ProjectPaths, contract: V2FeatureContract
) -> pd.DataFrame:
    columns = ("race_id", "horse_id", "race_date", *contract.inputs, TARGET_COLUMN)
    query = f"""
        SELECT {", ".join(columns)}
        FROM {SNAPSHOT_TABLE}
        WHERE race_date >= ? AND race_date < ?
        ORDER BY race_date, race_id, horse_id
    """
    with connect_database(paths=paths, read_only=True) as connection:
        frame = connection.execute(
            query, [TRAIN_START, POST_SELECTION_START]
        ).fetchdf()
        versions = connection.execute(
            f"""SELECT DISTINCT snapshot_version, semantic_version
                 FROM {SNAPSHOT_TABLE}
                 WHERE race_date >= ? AND race_date < ?""",
            [TRAIN_START, POST_SELECTION_START],
        ).fetchall()
    if len(versions) != 1:
        raise ValueError(f"Expected one Snapshot/Semantic version, found {versions}")
    frame.attrs["snapshot_version"] = str(versions[0][0])
    frame.attrs["semantic_version"] = str(versions[0][1])
    validate_v2_development_frame(frame, contract)
    return frame


def validate_v2_development_frame(
    frame: pd.DataFrame, contract: V2FeatureContract
) -> None:
    required = {"race_id", "horse_id", "race_date", TARGET_COLUMN, *contract.inputs}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing v2 modeling columns: {sorted(missing)}")
    if len(contract.inputs) != 117:
        raise ValueError("v2 model input count is not 117")
    if frame.empty:
        raise ValueError("v2 development frame is empty")
    dates = pd.to_datetime(frame["race_date"]).dt.date
    if dates.min() < TRAIN_START or dates.max() >= POST_SELECTION_START:
        raise ValueError("Development loader crossed its permitted date boundary")
    if frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate race_id + horse_id modeling key")
    if frame[TARGET_COLUMN].isna().any():
        raise ValueError("Modeling target contains NULL")
    if not set(frame[TARGET_COLUMN].astype(int).unique()) <= {0, 1}:
        raise ValueError("Modeling target is not binary")
    race_dates = frame.groupby("race_id", observed=True)["race_date"].nunique()
    if (race_dates != 1).any():
        raise ValueError("A race has multiple dates")


def _fit_pipeline(
    frame: pd.DataFrame, contract: V2FeatureContract
) -> tuple[Pipeline, int]:
    pipeline = build_v2_pipeline(contract)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        pipeline.fit(frame.loc[:, contract.inputs], frame[TARGET_COLUMN].astype(int))
    convergence_warnings = sum(
        issubclass(item.category, ConvergenceWarning) for item in caught
    )
    if convergence_warnings:
        raise RuntimeError("Logistic Regression did not converge under the fixed contract")
    return pipeline, convergence_warnings


def expanding_temporal_oof_v2(
    frame: pd.DataFrame, contract: V2FeatureContract
) -> tuple[pd.Series, list[dict[str, Any]]]:
    """Use the first three months for fitting, then predict successive 3-month blocks."""
    ordered = frame.sort_values(["race_date", "race_id", "horse_id"]).copy()
    dates = pd.to_datetime(ordered["race_date"])
    first_month = dates.min().to_period("M")
    last_month = dates.max().to_period("M")
    prediction_start = first_month + 3
    predictions = pd.Series(index=ordered.index, dtype=float)
    folds: list[dict[str, Any]] = []

    while prediction_start <= last_month:
        prediction_end = prediction_start + 3
        train_mask = dates < prediction_start.start_time
        prediction_mask = (dates >= prediction_start.start_time) & (
            dates < prediction_end.start_time
        )
        fold_train = ordered.loc[train_mask]
        fold_prediction = ordered.loc[prediction_mask]
        if fold_prediction.empty:
            prediction_start = prediction_end
            continue
        pipeline, convergence_warnings = _fit_pipeline(fold_train, contract)
        predictions.loc[fold_prediction.index] = pipeline.predict_proba(
            fold_prediction.loc[:, contract.inputs]
        )[:, 1]
        train_end = pd.to_datetime(fold_train["race_date"]).max().date()
        prediction_first = pd.to_datetime(fold_prediction["race_date"]).min().date()
        if train_end >= prediction_first:
            raise ValueError("Temporal OOF order violation")
        fold = OOFFold(
            train_start=str(pd.to_datetime(fold_train["race_date"]).min().date()),
            train_end=str(train_end),
            prediction_start=str(prediction_first),
            prediction_end=str(
                pd.to_datetime(fold_prediction["race_date"]).max().date()
            ),
            train_rows=len(fold_train),
            prediction_rows=len(fold_prediction),
        )
        folds.append(
            {
                **asdict(fold),
                "train_races": int(fold_train["race_id"].nunique()),
                "prediction_races": int(fold_prediction["race_id"].nunique()),
                "preprocessing_fit_scope": "fold_train_only",
                "convergence_warnings": convergence_warnings,
            }
        )
        prediction_start = prediction_end
    return predictions.dropna(), folds


def _candidate_monthly_metrics(
    validation: pd.DataFrame, candidates: dict[str, np.ndarray]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    months = pd.to_datetime(validation["race_date"]).dt.strftime("%Y-%m")
    for candidate, probabilities in candidates.items():
        for month in sorted(months.unique()):
            mask = months == month
            metric = evaluate_probabilities(validation.loc[mask], probabilities[mask])
            result.append({"candidate": candidate, "year_month": month, **asdict(metric)})
    return result


def _segment_metrics(
    validation: pd.DataFrame, candidates: dict[str, np.ndarray]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for candidate, probabilities in candidates.items():
        working = validation.copy()
        working["probability"] = probabilities
        for column in ("meet_code", "registered_runner_count", "race_grade", "distance_m"):
            for value, group in working.groupby(column, observed=True, dropna=False):
                metric = evaluate_probabilities(group, group["probability"].to_numpy())
                result.append(
                    {
                        "candidate": candidate,
                        "segment": column,
                        "value": str(value),
                        **asdict(metric),
                    }
                )
    return result


def choose_probability_procedure(metrics: dict[str, dict[str, Any]]) -> tuple[str, str]:
    raw = metrics["logistic_raw"]
    sigmoid = metrics["logistic_sigmoid"]
    if (
        sigmoid["macro_log_loss"] < raw["macro_log_loss"]
        and sigmoid["macro_brier"] < raw["macro_brier"]
    ):
        return (
            "logistic_sigmoid",
            "sigmoid improved both Validation macro Log Loss and macro Brier",
        )
    return (
        "logistic_raw",
        "sigmoid did not improve both primary macro metrics; selected simpler raw probability",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def run_official_baseline_v2_validation(
    *, paths: ProjectPaths | None = None
) -> V2RunOutcome:
    project_paths = paths or ProjectPaths.from_root()
    contract = load_feature_contract(project_paths)
    frame = load_v2_development_frame(paths=project_paths, contract=contract)
    train = frame.loc[pd.to_datetime(frame["race_date"]).dt.date < VALIDATION_START].copy()
    validation = frame.loc[
        pd.to_datetime(frame["race_date"]).dt.date >= VALIDATION_START
    ].copy()
    if train.empty or validation.empty:
        raise ValueError("Train and Validation rows are required")

    baseline_probability = float(train[TARGET_COLUMN].mean())
    baseline_predictions = np.full(len(validation), baseline_probability)
    train_pipeline, convergence_warnings = _fit_pipeline(train, contract)
    raw_predictions = cast(
        np.ndarray,
        train_pipeline.predict_proba(validation.loc[:, contract.inputs])[:, 1],
    )
    train_oof, train_folds = expanding_temporal_oof_v2(train, contract)
    calibrator = fit_sigmoid_calibrator(
        train.loc[train_oof.index, TARGET_COLUMN], train_oof.to_numpy()
    )
    sigmoid_predictions = calibrator.predict(raw_predictions)
    candidates = {
        "uninformed_baseline": baseline_predictions,
        "logistic_raw": raw_predictions,
        "logistic_sigmoid": sigmoid_predictions,
    }
    metric_objects = {
        name: evaluate_probabilities(validation, values)
        for name, values in candidates.items()
    }
    metrics = {name: asdict(metric) for name, metric in metric_objects.items()}
    selected, selection_reason = choose_probability_procedure(metrics)

    combined = pd.concat([train, validation], ignore_index=True)
    refit_pipeline, refit_convergence_warnings = _fit_pipeline(combined, contract)
    refit_calibrator: SigmoidCalibrator | None = None
    refit_folds: list[dict[str, Any]] = []
    if selected == "logistic_sigmoid":
        refit_oof, refit_folds = expanding_temporal_oof_v2(combined, contract)
        refit_calibrator = fit_sigmoid_calibrator(
            combined.loc[refit_oof.index, TARGET_COLUMN], refit_oof.to_numpy()
        )

    output = project_paths.exports / "modeling" / MODEL_VERSION
    output.mkdir(parents=True, exist_ok=True)
    feature_list_path = output / "model_inputs.txt"
    feature_list_path.write_bytes(("\n".join(contract.inputs) + "\n").encode("utf-8"))
    refit_artifact_path = output / "refit_artifact.joblib"
    joblib.dump(
        {"pipeline": refit_pipeline, "calibrator": refit_calibrator},
        refit_artifact_path,
    )
    _write_csv(output / "train_oof_folds.csv", train_folds)
    if refit_folds:
        _write_csv(output / "refit_oof_folds.csv", refit_folds)
    monthly_metrics = _candidate_monthly_metrics(validation, candidates)
    segment_metrics = _segment_metrics(
        validation,
        {name: values for name, values in candidates.items() if name != "uninformed_baseline"},
    )
    _write_csv(output / "validation_monthly_metrics.csv", monthly_metrics)
    _write_csv(output / "validation_segment_metrics.csv", segment_metrics)
    calibration_rows: list[dict[str, Any]] = []
    for candidate, values in candidates.items():
        for row in calibration_table(validation, values):
            calibration_rows.append({"candidate": candidate, **row})
    _write_csv(output / "validation_calibration_table.csv", calibration_rows)

    packages = {
        name: importlib.metadata.version(name)
        for name in ("duckdb", "joblib", "numpy", "pandas", "scikit-learn")
    }
    missing_without_companion = list(contract.zero_count)
    payload: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "selection_status": "SEALED_BEFORE_POST_SELECTION_TEMPORAL_EVALUATION",
        "snapshot_table": SNAPSHOT_TABLE,
        "snapshot_version": frame.attrs["snapshot_version"],
        "semantic_version": frame.attrs["semantic_version"],
        "target": TARGET_COLUMN,
        "model_inputs": contract.inputs,
        "model_input_count": len(contract.inputs),
        "model_input_sha256": contract.feature_hash,
        "excluded_logical": sorted(EXCLUDED_LOGICAL),
        "excluded_structural": sorted(EXCLUDED_STRUCTURAL),
        "date_contract": {
            "historical_warmup": ["2022-01-01", "2022-12-31"],
            "train": [str(TRAIN_START), "2024-06-30"],
            "validation": [str(VALIDATION_START), "2025-06-30"],
            "post_selection_temporal_evaluation": [
                str(POST_SELECTION_START),
                str(POST_SELECTION_END),
            ],
        },
        "development_data_max_date": str(
            pd.to_datetime(frame["race_date"]).max().date()
        ),
        "preprocessing": {
            "fit_scope": "Train only for candidate selection; fold-train only for OOF",
            "categorical_features": contract.categorical,
            "categorical": "most_frequent imputation + OneHotEncoder(handle_unknown=ignore)",
            "numeric_features": tuple(
                name for name in contract.numeric if name not in contract.zero_count
            ),
            "numeric": "Train median imputation + StandardScaler",
            "zero_observation_count_features": contract.zero_count,
            "zero_observation_count_rule": (
                "NULL means no valid historical observation; fill 0 then scale"
            ),
            "added_missing_indicators": [],
            "companionless_missing_features": missing_without_companion,
        },
        "logistic_parameters": {
            "penalty": "l2",
            "C": 1.0,
            "solver": "lbfgs",
            "max_iter": 2000,
            "class_weight": None,
            "random_state": RANDOM_SEED,
        },
        "candidate_convergence_warnings": convergence_warnings,
        "oof_contract": {
            "rule": "first 3 months train; predict next 3 months; expand by 3 months",
            "strict_order": "max(training date) < min(prediction date)",
            "folds": train_folds,
            "calibrator_fit_source": "Train temporal OOF predictions only",
            "sigmoid": asdict(calibrator),
        },
        "validation_candidates": [
            "uninformed_baseline",
            "logistic_raw",
            "logistic_sigmoid",
        ],
        "uninformed_probability_source": "Train place_hit prevalence",
        "uninformed_probability": baseline_probability,
        "validation_metrics": metrics,
        "selection_rule": (
            "sigmoid only if both macro Log Loss and macro Brier improve; otherwise raw"
        ),
        "selected_procedure": selected,
        "selection_reason": selection_reason,
        "train_rows": len(train),
        "train_races": int(train["race_id"].nunique()),
        "validation_rows": len(validation),
        "validation_races": int(validation["race_id"].nunique()),
        "refit": {
            "performed": True,
            "date_range": [str(TRAIN_START), "2025-06-30"],
            "rows": len(combined),
            "races": int(combined["race_id"].nunique()),
            "convergence_warnings": refit_convergence_warnings,
            "calibrator": asdict(refit_calibrator) if refit_calibrator else None,
            "oof_folds": refit_folds,
            "artifact_sha256": _file_sha256(refit_artifact_path),
        },
        "package_versions": packages,
        "post_selection_predictions_created": False,
        "post_selection_evaluated": False,
        "operator_pre_run_post_period_aggregate_exposure": {
            "occurred": True,
            "scope": "race count, row count, and aggregate place_hit prevalence only",
            "used_by_model_selection_code": False,
            "prediction_or_loss_metric_created": False,
        },
        "walk_forward_executed": False,
        "feature_selection_performed": False,
        "hyperparameter_search_performed": False,
    }
    canonical_payload = json.dumps(
        _json_ready(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    contract_payload_sha256 = _sha256_text(canonical_payload)
    payload["contract_payload_sha256"] = contract_payload_sha256
    contract_path = output / "run_contract.json"
    contract_path.write_text(
        json.dumps(_json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "run_contract.sha256").write_text(
        contract_payload_sha256 + "\n", encoding="ascii"
    )
    validation_result = {
        "model_version": MODEL_VERSION,
        "metrics": metrics,
        "selected_procedure": selected,
        "selection_reason": selection_reason,
        "train_oof_folds": train_folds,
        "calibration_tables": {
            name: calibration_table(validation, values)
            for name, values in candidates.items()
        },
        "monthly_metrics_file": "validation_monthly_metrics.csv",
        "segment_metrics_file": "validation_segment_metrics.csv",
        "post_selection_period_accessed": False,
    }
    (output / "validation_result.json").write_text(
        json.dumps(_json_ready(validation_result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return V2RunOutcome(
        model_version=MODEL_VERSION,
        selected_procedure=selected,
        train_rows=len(train),
        train_races=int(train["race_id"].nunique()),
        validation_rows=len(validation),
        validation_races=int(validation["race_id"].nunique()),
        refit_rows=len(combined),
        contract_path=contract_path,
        contract_payload_sha256=contract_payload_sha256,
        post_selection_predictions_created=False,
    )
