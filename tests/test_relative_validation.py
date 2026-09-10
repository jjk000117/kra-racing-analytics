from __future__ import annotations

from kra_analytics.relative_validation import _decision, _source_query


def _candidate(log_loss: float, brier: float) -> dict[str, object]:
    return {"metrics": {"macro_log_loss": log_loss, "macro_brier": brier}}


def test_r1_reproduction_requires_both_primary_metrics_to_improve() -> None:
    assert _decision(_candidate(0.53, 0.18), _candidate(0.52, 0.17))["judgement"] == "REPRODUCE_R1"
    equal_brier = _decision(_candidate(0.53, 0.18), _candidate(0.52, 0.18))
    worse_brier = _decision(_candidate(0.53, 0.18), _candidate(0.52, 0.19))
    assert equal_brier["judgement"] == "FAIL_TO_REPRODUCE_R1"
    assert worse_brier["judgement"] == "FAIL_TO_REPRODUCE_R1"


def test_validation_query_has_strict_pit_and_unopened_boundary() -> None:
    query = _source_query(("race_id", "horse_id", "race_date", "feature_as_of"))
    assert "hist.race_date<cur.feature_as_of" in query
    assert "race_date<DATE '2025-07-01'" in query
    assert "race_date<=DATE '2025-07-01'" not in query
