import numpy as np
import pandas as pd
import pytest

from kra_analytics.descriptive_validation_diagnostic import (
    maximum_f1_reference,
    ranking_metrics,
    threshold_metrics,
)


def test_threshold_metrics_confusion_counts() -> None:
    targets = np.array([1, 1, 0, 0])
    probabilities = np.array([0.9, 0.4, 0.6, 0.1])
    result = threshold_metrics(targets, probabilities, (0.5,))[0]
    assert result["tp"] == 1
    assert result["fp"] == 1
    assert result["fn"] == 1
    assert result["tn"] == 1
    assert result["precision"] == pytest.approx(0.5)
    assert result["recall"] == pytest.approx(0.5)
    assert result["specificity"] == pytest.approx(0.5)


def test_maximum_f1_reference_is_descriptive() -> None:
    result = maximum_f1_reference(
        np.array([1, 0, 1, 0]), np.array([0.9, 0.7, 0.6, 0.1])
    )
    assert result["threshold"] == pytest.approx(0.6)
    assert result["f1"] == pytest.approx(0.8)
    assert "not an adopted threshold" in result["selection_scope"]


def test_ranking_metrics_use_probability_then_horse_id() -> None:
    frame = pd.DataFrame(
        {
            "race_id": ["r1", "r1", "r1", "r2", "r2", "r2"],
            "horse_id": ["h2", "h1", "h3", "h4", "h5", "h6"],
            "place_hit": [0, 1, 1, 0, 1, 0],
            "sigmoid_probability": [0.8, 0.8, 0.2, 0.9, 0.5, 0.1],
        }
    )
    top_k, distribution = ranking_metrics(frame)
    assert top_k[0]["race_any_hit_rate"] == pytest.approx(0.5)
    assert top_k[1]["total_selected_hits"] == 2
    assert top_k[2]["micro_recall_at_k"] == pytest.approx(1.0)
    assert sum(row["races"] for row in distribution) == 2
