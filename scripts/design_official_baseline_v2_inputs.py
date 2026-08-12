# Inventory rows keep full feature-contract descriptions together.
# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from collections import Counter

from kra_analytics.database import connect_database
from kra_analytics.feature_snapshot_v2 import registry_feature_names
from kra_analytics.paths import ProjectPaths

VERSION = "official_place_baseline_v2_input_contract"
TABLE = "mart.place_feature_snapshot_v2_candidate"

STRUCTURAL_EXCLUSIONS = {
    "horse_prior_finish_count": (
        "horse_prior_start_count × horse_prior_finish_rate로 정확히 복원 가능"
    ),
    "horse_prior_win_count": "horse_prior_start_count × horse_prior_win_rate로 정확히 복원 가능",
    "horse_prior_top3_count": (
        "horse_prior_start_count × horse_prior_top3_rate로 정확히 복원 가능"
    ),
    "horse_history_available": "horse_prior_start_count > 0과 정의상 동일",
    "jockey_history_available": "jockey_prior_start_count > 0과 정의상 동일",
    "trainer_history_available": "trainer_prior_start_count > 0과 정의상 동일",
}

REVIEW_REQUIRED = {
    "horse_recent3_race_time_median": (
        "거리·경마장 조건을 혼합한 절대 경주시간 중앙값이므로 보정 없는 모델 입력 여부 검토 필요"
    ),
    "horse_recent5_race_time_median": (
        "거리·경마장 조건을 혼합한 절대 경주시간 중앙값이므로 보정 없는 모델 입력 여부 검토 필요"
    ),
}


def _family(name: str, category: str) -> str:
    if name in {"current_horse_weight_kg", "current_horse_weight_change_kg"}:
        return "현재 마체중"
    if name.startswith("current_"):
        return "기타 경주 전 관측정보"
    if category == "CURRENT_RACE_CONDITION":
        return "현재 경주 조건"
    if category == "CURRENT_PRERACE":
        return "현재 출전마·경주 기본정보"
    if name.startswith("horse_recent") and "race_time" in name:
        return "race time 이력"
    if name.startswith("horse_recent") and "s1f" in name:
        return "S1F 이력"
    if name.startswith("horse_recent") and "g3f" in name:
        return "G3F 이력"
    if name.startswith("horse_recent") and "g1f" in name:
        return "G1F 이력"
    if category == "HORSE_WEIGHT_HISTORY":
        return "마체중 이력"
    if name.startswith("horse_same_meet_distance"):
        return "동일 경마장×거리 이력"
    if name.startswith("horse_same_distance"):
        return "동일 거리 이력"
    if name.startswith("horse_same_meet"):
        return "동일 경마장 이력"
    if name.startswith("horse_recent"):
        return "recent form"
    if name.startswith("jockey_"):
        return "기수 이력"
    if name.startswith("trainer_"):
        return "조교사 이력"
    if name.startswith("owner_"):
        return "마주 이력"
    if name.startswith("horse_jockey_"):
        return "말×기수 조합 이력"
    if name.startswith("horse_trainer_"):
        return "말×조교사 조합 이력"
    return "말 장기 이력"


def _role(name: str, dtype: str) -> str:
    if name.endswith("_count"):
        return "count/sample-size"
    if name.endswith("_rate"):
        return "rate"
    if name.endswith("_available"):
        return "availability flag"
    if any(token in name for token in ("_avg_", "_mean", "_median", "_std")):
        return "average/summary"
    if "change" in name or "days_since" in name:
        return "delta/recency"
    if "best_finish_rank" in name or name.endswith("_rating"):
        return "historical level"
    if dtype == "BOOLEAN":
        return "flag"
    return "raw/current value"


def _companion(name: str) -> str:
    replacements = (
        ("_plc_hit_rate", "_start_count"),
        ("_finish_rate", "_start_count"),
        ("_win_rate", "_start_count"),
        ("_top3_rate", "_start_count"),
        ("_avg_finish_rank", "_start_count"),
        ("_best_finish_rank", "_start_count"),
        ("_avg_rating", "_start_count"),
        ("_rating_change", "_start_count"),
        ("_race_time_median", "_race_time_count"),
        ("_s1f_median", "_s1f_count"),
        ("_g3f_median", "_g3f_count"),
        ("_g1f_median", "_g1f_count"),
    )
    if name == "horse_prior_avg_finish_rank" or name == "horse_prior_finish_rank_std":
        return "horse_prior_start_count + horse_prior_finish_rate"
    if name.startswith("horse_prior_") and name.endswith("_rate"):
        return "horse_prior_start_count"
    if name in {
        "horse_prior_rating_mean", "horse_last_rating", "horse_rating_change_last_start",
        "horse_prior_carried_weight_mean", "horse_days_since_last_start",
    }:
        return "horse_prior_start_count"
    if name.startswith("horse_last_weight"):
        return "horse_prior_start_count"
    if name.startswith("horse_recent5_weight") and not name.endswith("_count"):
        return "horse_recent5_weight_count"
    for old, new in replacements:
        if name.endswith(old):
            return name[: -len(old)] + new
    if name.endswith("_available"):
        return name.replace("_history_available", "_prior_start_count")
    return ""


def _missing_meaning(name: str, family: str, nullable: bool) -> str:
    if not nullable:
        if name.endswith("_count"):
            return "0은 해당 Historical 관측 없음"
        return "현재 Snapshot에서는 결측 없음"
    if family in {"현재 마체중", "기타 경주 전 관측정보", "현재 경주 조건"}:
        return "현재 사전정보 미공개·원천 결측 또는 parsing 불가"
    if family in {"race time 이력", "S1F 이력", "G3F 이력", "G1F 이력"}:
        return "과거 이력 부족 또는 해당 기록 미관측; companion count로 구분"
    if family in {"동일 거리 이력", "동일 경마장 이력", "동일 경마장×거리 이력"}:
        return "과거 이력은 있어도 해당 조건 이력이 없음; 조건 count로 구분"
    if family in {"기수 이력", "조교사 이력", "마주 이력", "말×기수 조합 이력", "말×조교사 조합 이력"}:
        return "식별자 결측 또는 해당 관계의 과거 이력 없음; companion count로 구분"
    return "말의 과거 이력 또는 유효 관측 부족; companion count로 구분"


def _model_role(name: str) -> tuple[str, str, str]:
    if name in STRUCTURAL_EXCLUSIONS:
        return "EXCLUDE_STRUCTURAL", "D_STRUCTURAL_EXCLUSION", STRUCTURAL_EXCLUSIONS[name]
    if name in REVIEW_REQUIRED:
        return "REVIEW_REQUIRED", "E_REVIEW_REQUIRED", REVIEW_REQUIRED[name]
    if name.startswith("current_") or name in {
        "meet_code", "race_grade", "distance_m", "registered_runner_count", "gate_no",
        "horse_sex", "horse_age", "carried_weight", "rating", "race_age_condition",
        "race_weight_condition", "race_prize_condition", "race_sex_condition", "race_type",
        "race_day_of_week", "race_first_prize", "race_second_prize", "race_third_prize",
        "race_fourth_prize", "race_fifth_prize", "race_bonus_1", "race_bonus_2",
        "race_bonus_3",
    }:
        return "MODEL_INPUT", "A_CORE_MODEL_INPUT", "경주 전 직접 관측 가능한 현재값"
    return (
        "MODEL_INPUT",
        "B_MODEL_INPUT_WITH_COMPANION",
        "PIT-safe Historical 값; count/availability 맥락과 함께 사용",
    )


def main() -> None:
    paths = ProjectPaths.from_root()
    registry_path = paths.root / "docs" / "place-feature-registry-v2.csv"
    with registry_path.open(encoding="utf-8-sig", newline="") as stream:
        registry = {
            row["feature_name"]: row
            for row in csv.DictReader(stream)
            if row["recommendation_group"] == "IMMEDIATE_BASELINE"
        }
    expected = registry_feature_names(paths.root)
    with connect_database(paths=paths, read_only=True) as connection:
        schema = {
            str(row[0]): str(row[1])
            for row in connection.execute(f"DESCRIBE {TABLE}").fetchall()
        }
        profiles: dict[str, tuple[int, int, int]] = {}
        for name in expected:
            result = connection.execute(
                f"""SELECT count({name}), count(*)-count({name}),
                           count(*) FILTER (WHERE try_cast({name} AS DOUBLE)=0)
                    FROM {TABLE}"""
            ).fetchone()
            assert result is not None
            profiles[name] = tuple(map(int, result))

    rows: list[dict[str, object]] = []
    for name in expected:
        source = registry[name]
        dtype = schema[name]
        non_null, null_count, zero_count = profiles[name]
        family = _family(name, source["category"])
        model_role, baseline_set, rationale = _model_role(name)
        rows.append(
            {
                "feature_name": name,
                "meaning": source["calculation_definition"],
                "feature_family": family,
                "data_type": dtype,
                "time_scope": "CURRENT" if source["historical_window_or_condition"] == "CURRENT" else "HISTORICAL",
                "value_role": _role(name, dtype),
                "nullable": null_count > 0,
                "non_null_count": non_null,
                "null_count": null_count,
                "null_rate": round(null_count / (non_null + null_count), 8),
                "zero_count": zero_count,
                "companion_feature": _companion(name),
                "missing_meaning": _missing_meaning(name, family, null_count > 0),
                "modeling_role": model_role,
                "baseline_set": baseline_set,
                "decision_rationale": rationale,
            }
        )

    output = paths.root / "docs" / "official-place-baseline-v2-model-input-inventory.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "version": VERSION,
        "feature_count": len(rows),
        "unique_feature_count": len({row["feature_name"] for row in rows}),
        "modeling_role_counts": dict(Counter(str(row["modeling_role"]) for row in rows)),
        "baseline_set_counts": dict(Counter(str(row["baseline_set"]) for row in rows)),
        "family_counts": dict(Counter(str(row["feature_family"]) for row in rows)),
        "proposed_model_input_count": sum(
            row["modeling_role"] == "MODEL_INPUT" for row in rows
        ),
        "structural_exclusions": STRUCTURAL_EXCLUSIONS,
        "review_required": REVIEW_REQUIRED,
    }
    summary_path = paths.exports / "validation" / VERSION / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
