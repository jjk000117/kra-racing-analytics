from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import joblib  # type: ignore[import-untyped]
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import brier_score_loss, log_loss  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # type: ignore[import-untyped]

from kra_analytics.database import connect_database
from kra_analytics.feature_snapshot import MODEL_FEATURES, SNAPSHOT_VERSION
from kra_analytics.paths import ProjectPaths

MODEL_VERSION = "place_logistic_baseline_v1"
TARGET_COLUMN = "place_hit"
AUDIT_ONLY_FEATURE = "horse_prior_plc_hit_count"
MODEL_INPUTS = tuple(name for name in MODEL_FEATURES if name != AUDIT_ONLY_FEATURE)

CATEGORICAL_FEATURES = ("meet_code", "race_grade", "horse_sex")
BOOLEAN_FEATURES = (
    "horse_history_available",
    "jockey_history_available",
    "trainer_history_available",
)
NUMERIC_FEATURES = tuple(
    name for name in MODEL_INPUTS if name not in CATEGORICAL_FEATURES + BOOLEAN_FEATURES
)

WARMUP_START = date(2024, 1, 5)
TRAIN_START = date(2024, 10, 1)
VALIDATION_START = date(2025, 10, 1)
FINAL_TEST_START = date(2026, 1, 1)
FINAL_TEST_END = date(2026, 7, 26)
EPSILON = 1e-6


@dataclass(frozen=True)
class MetricResult:
    row_count: int
    race_count: int
    positive_rate: float
    macro_log_loss: float
    macro_brier: float
    micro_log_loss: float
    micro_brier: float
    calibration_intercept: float
    calibration_slope: float | None
    probability_min: float
    probability_max: float


@dataclass(frozen=True)
class OOFFold:
    train_start: str
    train_end: str
    prediction_start: str
    prediction_end: str
    train_rows: int
    prediction_rows: int


@dataclass(frozen=True)
class BaselineRunOutcome:
    model_version: str
    snapshot_version: str
    selected_procedure: str
    train_rows: int
    validation_rows: int
    refit_rows: int
    final_test_predictions_created: bool
    output_directory: Path


@dataclass(frozen=True)
class SigmoidCalibrator:
    intercept: float
    slope: float

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        logits = probability_logit(probabilities)
        values = self.intercept + self.slope * logits
        return cast(np.ndarray, 1.0 / (1.0 + np.exp(-values)))


def probability_logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(probabilities, dtype=float), EPSILON, 1.0 - EPSILON)
    return cast(np.ndarray, np.log(clipped / (1.0 - clipped)))


def calibration_intercept_slope(
    targets: np.ndarray | pd.Series, probabilities: np.ndarray | pd.Series
) -> tuple[float, float | None]:
    """Fit logit(P(Y=1)) = intercept + slope * logit(predicted probability)."""
    y = np.asarray(targets, dtype=int)
    if np.unique(y).size != 2:
        raise ValueError("Calibration intercept/slope requires both target classes")
    x = probability_logit(np.asarray(probabilities, dtype=float)).reshape(-1, 1)
    if np.ptp(x) <= np.finfo(float).eps:
        observed_rate = float(y.mean())
        intercept = float(probability_logit(np.array([observed_rate]))[0])
        return intercept, None
    model = LogisticRegression(C=np.inf, l1_ratio=0.0, solver="lbfgs", max_iter=2000)
    model.fit(x, y)
    return float(model.intercept_[0]), float(model.coef_[0, 0])


def fit_sigmoid_calibrator(
    targets: np.ndarray | pd.Series, probabilities: np.ndarray | pd.Series
) -> SigmoidCalibrator:
    intercept, slope = calibration_intercept_slope(targets, probabilities)
    if slope is None:
        raise ValueError("Sigmoid calibration requires non-constant probabilities")
    return SigmoidCalibrator(intercept=intercept, slope=slope)


def build_model_pipeline() -> Pipeline:
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
    preprocessor = ColumnTransformer(
        transformers=[
            ("categorical", categorical, list(CATEGORICAL_FEATURES)),
            ("numeric", numeric, list(NUMERIC_FEATURES)),
            ("boolean", "passthrough", list(BOOLEAN_FEATURES)),
        ]
    )
    model = LogisticRegression(
        C=1.0, l1_ratio=0.0, class_weight=None, solver="lbfgs", max_iter=2000
    )
    return Pipeline(steps=[("preprocessor", preprocessor), ("model", model)])


def _split_name(race_date: date) -> str:
    if WARMUP_START <= race_date < TRAIN_START:
        return "WARMUP"
    if TRAIN_START <= race_date < VALIDATION_START:
        return "TRAIN"
    if VALIDATION_START <= race_date < FINAL_TEST_START:
        return "VALIDATION"
    if FINAL_TEST_START <= race_date <= FINAL_TEST_END:
        return "FINAL_TEST"
    return "OUT_OF_SCOPE"


def assign_splits(frame: pd.DataFrame) -> pd.Series:
    dates = pd.to_datetime(frame["race_date"]).dt.date
    return dates.map(_split_name)


def load_development_snapshot(*, paths: ProjectPaths | None = None) -> pd.DataFrame:
    """Load Warm-up through Validation only; Final Test is inaccessible here."""
    project_paths = paths or ProjectPaths.from_root()
    columns = ("race_id", "horse_id", "race_date", *MODEL_FEATURES, TARGET_COLUMN)
    query = f"""
        SELECT {", ".join(columns)}
        FROM mart.feature_snapshot_place
        WHERE snapshot_version = ?
          AND race_date >= ?
          AND race_date < ?
        ORDER BY race_date, race_id, horse_id
    """
    with connect_database(paths=project_paths, read_only=True) as connection:
        frame = connection.execute(
            query, [SNAPSHOT_VERSION, WARMUP_START, FINAL_TEST_START]
        ).fetchdf()
    frame["split"] = assign_splits(frame)
    validate_development_frame(frame)
    return frame


def validate_development_frame(frame: pd.DataFrame) -> None:
    required = {"race_id", "horse_id", "race_date", TARGET_COLUMN, "split", *MODEL_FEATURES}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Missing modeling columns: {sorted(missing)}")
    if len(MODEL_FEATURES) != 29 or len(MODEL_INPUTS) != 28:
        raise ValueError("Expected 29 Snapshot features and 28 model inputs")
    if AUDIT_ONLY_FEATURE in MODEL_INPUTS:
        raise ValueError("Audit-only PLC hit count leaked into model inputs")
    if frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate race_id + horse_id modeling key")
    if (frame["split"] == "FINAL_TEST").any():
        raise ValueError("Final Test rows must not be loaded by the development path")
    split_counts = frame.groupby("race_id", observed=True)["split"].nunique()
    if (split_counts != 1).any():
        raise ValueError("A race crosses modeling splits")


def expanding_window_oof(frame: pd.DataFrame) -> tuple[pd.Series, list[OOFFold]]:
    """Predict consecutive 3-month blocks using all strictly earlier rows."""
    ordered = frame.sort_values(["race_date", "race_id", "horse_id"]).copy()
    dates = pd.to_datetime(ordered["race_date"])
    first_month = dates.min().to_period("M")
    last_month = dates.max().to_period("M")
    prediction_start = first_month + 3
    predictions = pd.Series(index=ordered.index, dtype=float)
    folds: list[OOFFold] = []

    while prediction_start <= last_month:
        prediction_end = prediction_start + 3
        train_mask = dates < prediction_start.start_time
        prediction_mask = (dates >= prediction_start.start_time) & (
            dates < prediction_end.start_time
        )
        train = ordered.loc[train_mask]
        holdout = ordered.loc[prediction_mask]
        if holdout.empty:
            prediction_start = prediction_end
            continue
        if train.empty or train[TARGET_COLUMN].nunique() != 2:
            raise ValueError("Every OOF fold requires prior rows with both target classes")
        pipeline = build_model_pipeline()
        pipeline.fit(train.loc[:, MODEL_INPUTS], train[TARGET_COLUMN].astype(int))
        predictions.loc[holdout.index] = pipeline.predict_proba(
            holdout.loc[:, MODEL_INPUTS]
        )[:, 1]
        folds.append(
            OOFFold(
                train_start=str(dates.loc[train.index].min().date()),
                train_end=str(dates.loc[train.index].max().date()),
                prediction_start=str(dates.loc[holdout.index].min().date()),
                prediction_end=str(dates.loc[holdout.index].max().date()),
                train_rows=len(train),
                prediction_rows=len(holdout),
            )
        )
        prediction_start = prediction_end
    return predictions.dropna(), folds


def evaluate_probabilities(frame: pd.DataFrame, probabilities: np.ndarray) -> MetricResult:
    values = np.asarray(probabilities, dtype=float)
    if len(values) != len(frame):
        raise ValueError("Probability count does not match evaluation rows")
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("Probabilities must be finite and within [0, 1]")
    y = frame[TARGET_COLUMN].astype(int).to_numpy()
    clipped = np.clip(values, EPSILON, 1.0 - EPSILON)
    row_losses = -(y * np.log(clipped) + (1 - y) * np.log(1 - clipped))
    row_brier = (values - y) ** 2
    grouped = pd.DataFrame(
        {"race_id": frame["race_id"].to_numpy(), "log_loss": row_losses, "brier": row_brier}
    ).groupby("race_id", observed=True)
    intercept, slope = calibration_intercept_slope(y, values)
    return MetricResult(
        row_count=len(frame),
        race_count=int(frame["race_id"].nunique()),
        positive_rate=float(y.mean()),
        macro_log_loss=float(grouped["log_loss"].mean().mean()),
        macro_brier=float(grouped["brier"].mean().mean()),
        micro_log_loss=float(log_loss(y, clipped, labels=[0, 1])),
        micro_brier=float(brier_score_loss(y, values)),
        calibration_intercept=intercept,
        calibration_slope=slope,
        probability_min=float(values.min()),
        probability_max=float(values.max()),
    )


def _calibration_table(frame: pd.DataFrame, probabilities: np.ndarray) -> list[dict[str, Any]]:
    table = frame.loc[:, ["race_id", "horse_id", TARGET_COLUMN]].copy()
    table["probability"] = probabilities
    table = table.sort_values(["probability", "race_id", "horse_id"]).reset_index(drop=True)
    table["bin"] = pd.qcut(table.index, q=min(10, len(table)), labels=False) + 1
    result = table.groupby("bin", observed=True).agg(
        rows=(TARGET_COLUMN, "size"),
        predicted_mean=("probability", "mean"),
        observed_rate=(TARGET_COLUMN, "mean"),
    )
    return cast(list[dict[str, Any]], result.reset_index().to_dict(orient="records"))


def _segment_metrics(frame: pd.DataFrame, probabilities: np.ndarray) -> list[dict[str, Any]]:
    working = frame.copy()
    working["probability"] = probabilities
    working["runner_count_band"] = pd.cut(
        working["registered_runner_count"],
        bins=[0, 8, 11, math.inf],
        labels=["<=8", "9-11", "12+"],
    )
    working["year_month"] = pd.to_datetime(working["race_date"]).dt.strftime("%Y-%m")
    results: list[dict[str, Any]] = []
    segments = (
        "meet_code",
        "race_grade",
        "runner_count_band",
        "year_month",
        "horse_history_available",
    )
    for column in segments:
        for value, group in working.groupby(column, observed=True, dropna=False):
            metric = evaluate_probabilities(group, group["probability"].to_numpy())
            results.append({"segment": column, "value": str(value), **asdict(metric)})
    return results


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def run_validation_and_refit(*, paths: ProjectPaths | None = None) -> BaselineRunOutcome:
    project_paths = paths or ProjectPaths.from_root()
    frame = load_development_snapshot(paths=project_paths)
    train = frame.loc[frame["split"] == "TRAIN"].copy()
    validation = frame.loc[frame["split"] == "VALIDATION"].copy()
    if train.empty or validation.empty:
        raise ValueError("Train and Validation rows are required")

    prevalence = float(train[TARGET_COLUMN].mean())
    baseline_probabilities = np.full(len(validation), prevalence)
    pipeline = build_model_pipeline()
    pipeline.fit(train.loc[:, MODEL_INPUTS], train[TARGET_COLUMN].astype(int))
    raw_probabilities = pipeline.predict_proba(validation.loc[:, MODEL_INPUTS])[:, 1]

    train_oof, train_folds = expanding_window_oof(train)
    calibrator = fit_sigmoid_calibrator(
        train.loc[train_oof.index, TARGET_COLUMN], train_oof.to_numpy()
    )
    calibrated_probabilities = calibrator.predict(raw_probabilities)
    candidate_probabilities = {
        "uninformed_baseline": baseline_probabilities,
        "logistic_raw": raw_probabilities,
        "logistic_sigmoid": calibrated_probabilities,
    }
    metrics = {
        name: evaluate_probabilities(validation, probabilities)
        for name, probabilities in candidate_probabilities.items()
    }
    selected = min(
        metrics,
        key=lambda name: (metrics[name].macro_log_loss, metrics[name].macro_brier, name),
    )

    combined = pd.concat([train, validation], ignore_index=True)
    final_pipeline: Pipeline | None = None
    final_calibrator: SigmoidCalibrator | None = None
    combined_folds: list[OOFFold] = []
    final_prevalence: float | None = None
    if selected == "uninformed_baseline":
        final_prevalence = float(combined[TARGET_COLUMN].mean())
    else:
        final_pipeline = build_model_pipeline()
        final_pipeline.fit(combined.loc[:, MODEL_INPUTS], combined[TARGET_COLUMN].astype(int))
        if selected == "logistic_sigmoid":
            combined_oof, combined_folds = expanding_window_oof(combined)
            final_calibrator = fit_sigmoid_calibrator(
                combined.loc[combined_oof.index, TARGET_COLUMN], combined_oof.to_numpy()
            )

    output_directory = project_paths.exports / "modeling" / MODEL_VERSION
    output_directory.mkdir(parents=True, exist_ok=True)
    if final_pipeline is not None:
        joblib.dump(final_pipeline, output_directory / "pipeline.joblib")
    run_contract = {
        "model_version": MODEL_VERSION,
        "snapshot_version": SNAPSHOT_VERSION,
        "model_inputs": MODEL_INPUTS,
        "audit_only_feature": AUDIT_ONLY_FEATURE,
        "splits": {
            "warmup": [str(WARMUP_START), str(TRAIN_START)],
            "train": [str(TRAIN_START), str(VALIDATION_START)],
            "validation": [str(VALIDATION_START), str(FINAL_TEST_START)],
            "final_test": [str(FINAL_TEST_START), str(FINAL_TEST_END)],
        },
        "selection_metric": ["macro_log_loss", "macro_brier"],
        "preprocessing": {
            "categorical": "train_most_frequent_then_one_hot_handle_unknown_ignore",
            "numeric": "train_median_then_train_standard_scaler",
            "boolean": "passthrough_as_zero_one",
        },
        "logistic_parameters": {
            "regularization": "l2",
            "C": 1.0,
            "class_weight": None,
            "solver": "lbfgs",
            "max_iter": 2000,
        },
        "oof_rule": "expanding_all_prior_months_then_predict_next_three_months",
        "calibration_definition": (
            "logit(P(place_hit=1)) = intercept + slope * logit(predicted_probability)"
        ),
        "selected_procedure": selected,
        "selection_status": "SEALED_BEFORE_FINAL_TEST",
        "validation_metrics": {name: asdict(metric) for name, metric in metrics.items()},
        "validation_calibration_tables": {
            name: _calibration_table(validation, probabilities)
            for name, probabilities in candidate_probabilities.items()
        },
        "selected_segment_metrics": _segment_metrics(
            validation, candidate_probabilities[selected]
        ),
        "train_oof_folds": [asdict(fold) for fold in train_folds],
        "refit_oof_folds": [asdict(fold) for fold in combined_folds],
        "train_sigmoid": asdict(calibrator),
        "refit_sigmoid": asdict(final_calibrator) if final_calibrator else None,
        "refit_prevalence": final_prevalence,
        "train_rows": len(train),
        "validation_rows": len(validation),
        "refit_rows": len(combined),
        "final_test_predictions_created": False,
        "final_test_evaluated": False,
    }
    (output_directory / "run_contract.json").write_text(
        json.dumps(_json_ready(run_contract), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return BaselineRunOutcome(
        model_version=MODEL_VERSION,
        snapshot_version=SNAPSHOT_VERSION,
        selected_procedure=selected,
        train_rows=len(train),
        validation_rows=len(validation),
        refit_rows=len(combined),
        final_test_predictions_created=False,
        output_directory=output_directory,
    )
