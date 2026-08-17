from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest
from sklearn.base import clone  # type: ignore[import-untyped]

from kra_analytics.development_evaluation import (
    DEVELOPMENT_FOLDS,
    DevelopmentAccessError,
    ExperimentRegistry,
    _fold_frames,
    enforce_development_window,
)
from kra_analytics.modeling_v2 import V2FeatureContract, build_v2_pipeline


def test_development_guard_rejects_validation_or_later_access() -> None:
    enforce_development_window(start=date(2023, 1, 1), end_exclusive=date(2024, 7, 1))
    with pytest.raises(DevelopmentAccessError, match="2024-07-01"):
        enforce_development_window(start=date(2023, 1, 1), end_exclusive=date(2024, 7, 2))


def test_four_folds_have_strict_expanding_temporal_order() -> None:
    rows = []
    for month_index, month in enumerate(pd.date_range("2023-01-01", periods=18, freq="MS")):
        rows.append(
            {
                "race_id": f"R{month_index}",
                "horse_id": "H1",
                "race_date": month.date(),
            }
        )
    frame = pd.DataFrame(rows)

    assert len(DEVELOPMENT_FOLDS) == 4
    previous_train_rows = 0
    for spec in DEVELOPMENT_FOLDS:
        train, evaluation = _fold_frames(frame, spec)
        assert train["race_date"].max() < evaluation["race_date"].min()
        assert len(train) > previous_train_rows
        previous_train_rows = len(train)


def test_preprocessor_learns_categories_and_median_from_fold_train_only() -> None:
    contract = V2FeatureContract(
        inputs=("numeric", "category"),
        categorical=("category",),
        numeric=("numeric",),
        zero_count=(),
        feature_hash="dummy",
    )
    train = pd.DataFrame({"numeric": [1.0, None, 3.0], "category": ["A", "A", "B"]})
    evaluation = pd.DataFrame({"numeric": [9999.0], "category": ["EVAL_ONLY"]})
    preprocessor = clone(build_v2_pipeline(contract).named_steps["preprocessor"])

    preprocessor.fit(train)
    preprocessor.transform(evaluation)
    categorical_pipeline = preprocessor.named_transformers_["categorical"]
    numeric_pipeline = preprocessor.named_transformers_["numeric"]

    categories = categorical_pipeline.named_steps["onehot"].categories_[0]
    median = numeric_pipeline.named_steps["imputer"].statistics_[0]
    assert "EVAL_ONLY" not in categories
    assert median == 2.0


def test_registry_records_fold_metrics_and_limits_validation_access(tmp_path) -> None:
    path = tmp_path / "registry.json"
    registry = ExperimentRegistry(path, feature_hash="a" * 64)
    registry.register(
        experiment_id="M1", model_config={"family": "test"}, feature_config={"set": "117"}
    )
    for spec in DEVELOPMENT_FOLDS:
        registry.record_fold_metrics(
            experiment_id="M1", fold_id=spec.fold_id, metrics={"macro_log_loss": 0.5}
        )
    registry.freeze_for_validation(experiment_id="M1")
    registry.record_validation_access(experiment_id="M1", reason="frozen comparison")

    payload = json.loads(path.read_text(encoding="utf-8"))
    experiment = payload["experiments"][0]
    assert experiment["feature_hash"] == "a" * 64
    assert len(experiment["fold_metrics"]) == 4
    assert experiment["validation_access_count"] == 1
    with pytest.raises(ValueError, match="exhausted"):
        registry.record_validation_access(experiment_id="M1", reason="repeat")
