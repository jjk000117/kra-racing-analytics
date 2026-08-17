from __future__ import annotations

import json
import time
import warnings
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OrdinalEncoder  # type: ignore[import-untyped]

from kra_analytics.development_evaluation import (
    DEFAULT_REGISTRY,
    DEVELOPMENT_FOLDS,
    ExperimentRegistry,
    _fold_frames,
    load_development_frame,
    verify_sealed_artifacts,
)
from kra_analytics.modeling import evaluate_probabilities
from kra_analytics.modeling_v2 import (
    RANDOM_SEED,
    TARGET_COLUMN,
    V2FeatureContract,
    build_v2_pipeline,
    load_feature_contract,
)
from kra_analytics.paths import ProjectPaths

M1_EXPERIMENT_VERSION = "m1_histgradientboosting_development_v1"
M1_SETTINGS = {
    "M1-A": {"max_leaf_nodes": 31, "l2_regularization": 0.0},
    "M1-B": {"max_leaf_nodes": 15, "l2_regularization": 1.0},
}
COMMON_HGB_SETTINGS = {
    "loss": "log_loss",
    "learning_rate": 0.1,
    "max_iter": 100,
    "max_depth": None,
    "min_samples_leaf": 20,
    "max_bins": 255,
    "early_stopping": False,
    "random_state": RANDOM_SEED,
    "class_weight": None,
}


def build_m1_pipeline(
    contract: V2FeatureContract, *, max_leaf_nodes: int, l2_regularization: float
) -> Pipeline:
    median_numeric = tuple(name for name in contract.numeric if name not in contract.zero_count)
    categorical = OrdinalEncoder(
        handle_unknown="use_encoded_value",
        unknown_value=np.nan,
        encoded_missing_value=np.nan,
    )
    numeric = SimpleImputer(strategy="median")
    zero_count = SimpleImputer(strategy="constant", fill_value=0)
    preprocessor = ColumnTransformer(
        transformers=[
            ("categorical", categorical, list(contract.categorical)),
            ("numeric", numeric, list(median_numeric)),
            ("zero_count", zero_count, list(contract.zero_count)),
        ],
        sparse_threshold=0.0,
    )
    categorical_mask = [True] * len(contract.categorical) + [False] * len(contract.numeric)
    model = HistGradientBoostingClassifier(
        **COMMON_HGB_SETTINGS,
        max_leaf_nodes=max_leaf_nodes,
        l2_regularization=l2_regularization,
        categorical_features=categorical_mask,
    )
    return Pipeline(steps=[("preprocessor", preprocessor), ("model", model)])


def _unseen_profile(
    train: pd.DataFrame, evaluation: pd.DataFrame, contract: V2FeatureContract
) -> dict[str, Any]:
    any_unseen = pd.Series(False, index=evaluation.index)
    feature_rows: dict[str, int] = {}
    for feature in contract.categorical:
        train_values = set(train[feature].dropna().unique())
        mask = evaluation[feature].notna() & ~evaluation[feature].isin(train_values)
        feature_rows[feature] = int(mask.sum())
        any_unseen |= mask
    return {
        "any_unseen_rows": int(any_unseen.sum()),
        "any_unseen_row_rate": float(any_unseen.mean()),
        "unseen_rows_by_feature": feature_rows,
    }


def _metric_payload(frame: pd.DataFrame, probabilities: np.ndarray) -> dict[str, float]:
    metric = asdict(evaluate_probabilities(frame, probabilities))
    return {key: float(value) for key, value in metric.items() if value is not None}


def _fit_and_evaluate(
    pipeline: Pipeline,
    *,
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    contract: V2FeatureContract,
) -> tuple[dict[str, float], float, list[str]]:
    start = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        pipeline.fit(train.loc[:, contract.inputs], train[TARGET_COLUMN].astype(int))
    fit_seconds = time.perf_counter() - start
    probabilities = pipeline.predict_proba(evaluation.loc[:, contract.inputs])[:, 1]
    warning_messages = [str(item.message) for item in caught]
    return _metric_payload(evaluation, probabilities), fit_seconds, warning_messages


def _summaries(fold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metric_names = (
        "macro_log_loss",
        "macro_brier",
        "micro_log_loss",
        "micro_brier",
        "calibration_intercept",
        "calibration_slope",
        "fit_seconds",
    )
    results: list[dict[str, Any]] = []
    for experiment_id in ("B0", *M1_SETTINGS):
        rows = [row for row in fold_rows if row["experiment_id"] == experiment_id]
        summary: dict[str, Any] = {"experiment_id": experiment_id, "folds": len(rows)}
        for metric in metric_names:
            values = np.asarray([row[metric] for row in rows], dtype=float)
            summary[f"{metric}_mean"] = float(values.mean())
            summary[f"{metric}_std"] = float(values.std(ddof=0))
        results.append(summary)
    return results


def _register_results(
    *,
    registry: ExperimentRegistry,
    fold_rows: list[dict[str, Any]],
    contract: V2FeatureContract,
) -> None:
    model_configs: dict[str, dict[str, Any]] = {
        "B0": {"family": "LogisticRegression", "contract": "official_v2_raw"},
        **{
            name: {
                "family": "HistGradientBoostingClassifier",
                **COMMON_HGB_SETTINGS,
                **settings,
            }
            for name, settings in M1_SETTINGS.items()
        },
    }
    for experiment_id, config in model_configs.items():
        registry.register(
            experiment_id=experiment_id,
            model_config=config,
            feature_config={"count": len(contract.inputs), "set": "official_v2_117"},
        )
        for row in fold_rows:
            if row["experiment_id"] != experiment_id:
                continue
            metrics = {
                key: float(row[key])
                for key in (
                    "macro_log_loss",
                    "macro_brier",
                    "micro_log_loss",
                    "micro_brier",
                    "calibration_intercept",
                    "calibration_slope",
                    "fit_seconds",
                )
            }
            registry.record_fold_metrics(
                experiment_id=experiment_id, fold_id=str(row["fold_id"]), metrics=metrics
            )
        registry.complete_development(experiment_id=experiment_id)


def run_m1_development_experiment(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contract = load_feature_contract(project_paths)
    frame = load_development_frame(paths=project_paths, contract=contract)
    protection = json.loads(
        (project_paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    sealed_before = verify_sealed_artifacts(project_paths, protection["artifacts"])
    fold_rows: list[dict[str, Any]] = []
    fold_context: list[dict[str, Any]] = []

    for spec in DEVELOPMENT_FOLDS:
        train, evaluation = _fold_frames(frame, spec)
        unseen = _unseen_profile(train, evaluation, contract)
        fold_context.append(
            {
                "fold_id": spec.fold_id,
                "train_start": str(train["race_date"].min()),
                "train_end": str(train["race_date"].max()),
                "evaluation_start": str(evaluation["race_date"].min()),
                "evaluation_end": str(evaluation["race_date"].max()),
                "train_rows": len(train),
                "train_races": int(train["race_id"].nunique()),
                "evaluation_rows": len(evaluation),
                "evaluation_races": int(evaluation["race_id"].nunique()),
                "strict_temporal_ordering": bool(
                    train["race_date"].max() < evaluation["race_date"].min()
                ),
                "preprocessing_fit_scope": "fold_train_only",
                **unseen,
            }
        )
        pipelines = {
            "B0": build_v2_pipeline(contract),
            **{
                name: build_m1_pipeline(
                    contract,
                    max_leaf_nodes=int(settings["max_leaf_nodes"]),
                    l2_regularization=float(settings["l2_regularization"]),
                )
                for name, settings in M1_SETTINGS.items()
            },
        }
        for experiment_id, pipeline in pipelines.items():
            metrics, fit_seconds, warning_messages = _fit_and_evaluate(
                pipeline,
                train=train,
                evaluation=evaluation,
                contract=contract,
            )
            fold_rows.append(
                {
                    "experiment_id": experiment_id,
                    "fold_id": spec.fold_id,
                    **metrics,
                    "fit_seconds": fit_seconds,
                    "warning_count": len(warning_messages),
                    "warning_messages": warning_messages,
                }
            )

    registry_path = project_paths.root / DEFAULT_REGISTRY
    registry = ExperimentRegistry(registry_path, feature_hash=contract.feature_hash)
    registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry_payload["experiments"]:
        raise ValueError("Development registry must be empty before the sealed M1 run")
    _register_results(registry=registry, fold_rows=fold_rows, contract=contract)
    registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
    validation_access_count = int(
        sum(item["validation_access_count"] for item in registry_payload["experiments"])
    )
    sealed_after = verify_sealed_artifacts(project_paths, protection["artifacts"])
    if sealed_before != sealed_after:
        raise ValueError("Sealed baseline v2 artifacts changed during M1")

    output = project_paths.exports / f"modeling/{M1_EXPERIMENT_VERSION}"
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(fold_rows).drop(columns="warning_messages").to_csv(
        output / "fold_metrics.csv", index=False
    )
    summaries = _summaries(fold_rows)
    pd.DataFrame(summaries).to_csv(output / "summary_metrics.csv", index=False)
    result = {
        "experiment_version": M1_EXPERIMENT_VERSION,
        "development_window": ["2023-01-01", "2024-06-30"],
        "feature_count": len(contract.inputs),
        "feature_hash": contract.feature_hash,
        "fold_context": fold_context,
        "fold_metrics": fold_rows,
        "summary_metrics": summaries,
        "validation_access_count": validation_access_count,
        "sealed_artifacts_unchanged": True,
        "sealed_artifact_hashes": sealed_after,
        "registry_path": str(registry_path.relative_to(project_paths.root)),
        "validation_or_later_rows_loaded": False,
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
