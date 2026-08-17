from __future__ import annotations

import numpy as np
import pandas as pd

from kra_analytics.m1_experiment import build_m1_pipeline
from kra_analytics.modeling_v2 import V2FeatureContract


def test_m1_pipeline_handles_unseen_category_without_scaling() -> None:
    contract = V2FeatureContract(
        inputs=("category", "numeric", "count"),
        categorical=("category",),
        numeric=("numeric", "count"),
        zero_count=("count",),
        feature_hash="dummy",
    )
    train = pd.DataFrame(
        {
            "category": ["A", "A", "B", "B"] * 10,
            "numeric": [1.0, np.nan, 3.0, 4.0] * 10,
            "count": [0.0, 1.0, np.nan, 2.0] * 10,
        }
    )
    target = np.asarray([0, 0, 1, 1] * 10)
    evaluation = pd.DataFrame(
        {"category": ["UNSEEN"], "numeric": [999.0], "count": [np.nan]}
    )
    pipeline = build_m1_pipeline(contract, max_leaf_nodes=15, l2_regularization=1.0)

    pipeline.fit(train, target)
    probability = pipeline.predict_proba(evaluation)[0, 1]

    assert 0.0 <= probability <= 1.0
    transformed = pipeline.named_steps["preprocessor"].transform(evaluation)
    assert np.isnan(transformed[0, 0])
    assert transformed[0, 2] == 0.0
