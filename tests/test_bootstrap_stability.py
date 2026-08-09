from __future__ import annotations

import numpy as np
import pandas as pd

from kra_analytics.bootstrap_stability import (
    bootstrap_means,
    race_level_losses,
    summarize_bootstrap,
)
from kra_analytics.modeling import TARGET_COLUMN


def test_race_level_losses_preserve_macro_definition() -> None:
    frame = pd.DataFrame(
        {"race_id": ["A", "A", "B"], TARGET_COLUMN: [1, 0, 1]}
    )
    probabilities = np.array([0.8, 0.3, 0.6])

    losses = race_level_losses(frame, probabilities)

    expected_a_log = (-np.log(0.8) - np.log(0.7)) / 2
    expected_b_log = -np.log(0.6)
    assert np.isclose(losses["log_loss"].mean(), (expected_a_log + expected_b_log) / 2)
    assert np.isclose(losses["brier"].mean(), (((0.2**2 + 0.3**2) / 2) + 0.4**2) / 2)


def test_bootstrap_is_reproducible_with_fixed_seed() -> None:
    values = np.array([0.1, 0.2, 0.3, 0.4])
    first = bootstrap_means(
        values, 3, repetitions=100, rng=np.random.default_rng(20260809)
    )
    second = bootstrap_means(
        values, 3, repetitions=100, rng=np.random.default_rng(20260809)
    )

    np.testing.assert_array_equal(first, second)


def test_tail_rate_counts_equal_or_worse_values() -> None:
    summary = summarize_bootstrap(np.array([0.1, 0.2, 0.3, 0.4]), actual=0.3)

    assert summary["empirical_equal_or_worse_rate"] == 0.5
    assert summary["actual"] == 0.3
