from scripts.design_official_baseline_v2_inputs import (
    REVIEW_REQUIRED,
    STRUCTURAL_EXCLUSIONS,
    _model_role,
)


def test_model_roles_use_only_structural_meaning() -> None:
    assert len(STRUCTURAL_EXCLUSIONS) == 6
    assert len(REVIEW_REQUIRED) == 2
    assert _model_role("horse_history_available")[0] == "EXCLUDE_STRUCTURAL"
    assert _model_role("horse_recent3_race_time_median")[0] == "REVIEW_REQUIRED"
    assert _model_role("horse_recent3_g3f_count")[0] == "MODEL_INPUT"
    assert _model_role("current_horse_weight_kg")[1] == "A_CORE_MODEL_INPUT"
