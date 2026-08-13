# Official place baseline v2 모델 입력 설계

기준일: 2026-08-12  
대상: `mart.place_feature_snapshot_v2_candidate` 85,566행 × 125 Feature
상태: 입력 후보 계약 확정, 모델 미학습

## 기술 요약

125개 Feature를 실제 물리 컬럼·registry·결측 프로파일과 대조한 결과, 새 official
baseline에는 117개를 모델 입력으로 제안한다. 현재 사전정보 28개는 Core input이고,
PIT-safe Historical 정보 89개는 count와 함께 해석하는 input이다. 정의상 복원 가능한
count/flag 6개는 구조 제외한다. 거리·경마장을 혼합한 절대 경주시간 중앙값 2개는 현재
형태로 일관된 경기력 지표가 아니므로 `EXCLUDE_LOGICAL`로 확정한다.

모델 성능, target 관계, correlation, VIF, Feature importance와 ablation은 사용하지 않았다.
기존 `place_logistic_baseline_v1`과 평가 산출물도 변경하지 않았다.

## 판정 결과

| 모델링 역할 | 수 | 의미 |
|---|---:|---|
| `MODEL_INPUT` | 117 | official baseline 입력 후보 |
| `AUDIT_ONLY` | 0 | 125개 Feature 안에는 없음 |
| `EXCLUDE_STRUCTURAL` | 6 | 다른 입력으로 정의상 정확히 복원 |
| `EXCLUDE_LOGICAL` | 2 | 조건 혼합으로 의미가 일관되지 않아 모델 입력 제외 |

125개 밖의 ID·날짜·lineage·타깃·모집단 상태 22개는 관리·감사용이며 모델 입력이 아니다.
전체 125개 inventory, 타입, 역할, 결측률, companion과 판정은
`docs/official-place-baseline-v2-model-input-inventory.csv`가 통제 문서다.

## A. Core model input — 28개

경주 전 직접 관측되는 값이며 별도 Historical count가 없어도 의미가 성립한다.

`meet_code`, `race_grade`, `distance_m`, `registered_runner_count`, `gate_no`,
`horse_sex`, `horse_age`, `carried_weight`, `rating`, `race_age_condition`,
`race_weight_condition`, `race_prize_condition`, `race_sex_condition`, `race_type`,
`race_day_of_week`, `race_first_prize`, `race_second_prize`, `race_third_prize`,
`race_fourth_prize`, `race_fifth_prize`, `race_bonus_1`, `race_bonus_2`,
`race_bonus_3`, `current_weather`, `current_track_condition`,
`current_track_moisture_percent`, `current_horse_weight_kg`,
`current_horse_weight_change_kg`

경마장·거리·등급·등록두수는 경주 구조를, 성별·나이·부담중량·rating·마체중은 현재
출전마 상태를, 날씨·주로·함수율은 현재 환경을 나타낸다. 경주조건·상금 필드는 등급과
부분적으로 겹칠 수 있지만 정의상 동일하지 않아 유지한다.

## B. Model input with companion information — 89개

다음 Historical 값은 가용성·표본 깊이를 함께 전달해야 한다. count 자체도 신뢰도와 경험량을
구분하므로 입력으로 유지한다.

### 말 장기·recent form

`horse_prior_start_count`, `horse_prior_finish_rate`, `horse_prior_plc_hit_rate`,
`horse_prior_avg_finish_rank`, `horse_days_since_last_start`,
`horse_prior_win_rate`, `horse_prior_top3_rate`, `horse_prior_best_finish_rank`,
`horse_prior_finish_rank_std`, `horse_prior_rating_mean`, `horse_last_rating`,
`horse_rating_change_last_start`, `horse_prior_carried_weight_mean`,
`horse_recent3_start_count`, `horse_recent3_finish_rate`, `horse_recent3_win_rate`,
`horse_recent3_top3_rate`, `horse_recent3_avg_finish_rank`,
`horse_recent3_best_finish_rank`, `horse_recent3_avg_rating`,
`horse_recent3_rating_change`, `horse_recent5_start_count`,
`horse_recent5_finish_rate`, `horse_recent5_plc_hit_rate`,
`horse_recent5_avg_finish_rank`, `horse_recent5_win_rate`,
`horse_recent5_top3_rate`, `horse_recent5_best_finish_rank`,
`horse_recent5_avg_rating`, `horse_recent5_rating_change`,
`horse_recent10_start_count`, `horse_recent10_finish_rate`,
`horse_recent10_win_rate`, `horse_recent10_top3_rate`,
`horse_recent10_avg_finish_rank`, `horse_recent10_best_finish_rank`,
`horse_recent10_avg_rating`, `horse_recent10_rating_change`

recent3은 단기 폼, recent5는 중기 폼, recent10은 더 안정적인 이력을 나타내므로 window가
다르다는 이유로 제거하지 않는다. 세 window 모두 start count, 완주율, 승률, Top3율,
평균·최고 착순, 평균·변화 rating을 가진다. PLC 적중률은 기존 v1 승계로 recent5에만 있고
recent3/10에는 없다. 이는 불균형이지만 정의 오류는 아니며 후속 registry 확장 판단 대상으로
기록한다.

### 조건 적성

`horse_same_distance_start_count`, `horse_same_distance_finish_rate`,
`horse_same_distance_plc_hit_rate`, `horse_same_distance_avg_finish_rank`,
`horse_same_meet_start_count`, `horse_same_meet_finish_rate`,
`horse_same_meet_plc_hit_rate`, `horse_same_meet_avg_finish_rank`,
`horse_same_meet_distance_start_count`, `horse_same_meet_distance_finish_rate`,
`horse_same_meet_distance_plc_hit_rate`, `horse_same_meet_distance_avg_finish_rank`

전체 prior → 동일 경마장/거리 → 동일 경마장×거리로 조건이 좁아진다. 좁은 조건일수록
결측률이 높으므로 각각의 start count를 유지한다. 이 묶음은 부분 중복이지 자동 제거 대상이 아니다.

### Sectional과 가용성 count

`horse_recent3_race_time_count`, `horse_recent5_race_time_count`,
`horse_recent3_s1f_median`, `horse_recent3_s1f_count`,
`horse_recent5_s1f_median`, `horse_recent5_s1f_count`,
`horse_recent3_g3f_median`, `horse_recent3_g3f_count`,
`horse_recent5_g3f_median`, `horse_recent5_g3f_count`,
`horse_recent3_g1f_median`, `horse_recent3_g1f_count`,
`horse_recent5_g1f_median`, `horse_recent5_g1f_count`

현재 구현은 race time/S1F/G3F/G1F마다 recent3·recent5 median/count만 있다.
recent10, 동일거리, 동일 경마장, 동일 경마장×거리 sectional 요약은 없다. G3F/G1F는
경마장별 원천을 동일한 최종 600m/200m 구간으로 공통화했으므로 사용 가능하다. S1F도
공통 물리 의미로 사용한다. 새로운 speed figure나 조건 보정은 이번 계약에 없다.

### 마체중·관계자

`horse_last_weight_kg`, `horse_last_weight_change_kg`,
`horse_recent5_weight_mean`, `horse_recent5_weight_std`,
`horse_recent5_weight_count`, `jockey_prior_start_count`,
`jockey_prior_plc_hit_rate`, `jockey_recent10_start_count`,
`jockey_recent10_plc_hit_rate`, `jockey_same_meet_start_count`,
`jockey_same_meet_plc_hit_rate`, `trainer_prior_start_count`,
`trainer_prior_plc_hit_rate`, `trainer_recent10_start_count`,
`trainer_recent10_plc_hit_rate`, `trainer_same_meet_start_count`,
`trainer_same_meet_plc_hit_rate`, `horse_jockey_recent10_start_count`,
`horse_jockey_recent10_plc_hit_rate`, `horse_jockey_same_meet_start_count`,
`horse_jockey_same_meet_plc_hit_rate`, `owner_prior_start_count`,
`owner_prior_plc_hit_rate`, `horse_trainer_prior_start_count`,
`horse_trainer_prior_plc_hit_rate`

관계자 ID 자체는 넣지 않고 ID에서 PIT-safe하게 계산한 통계만 사용한다. 말×관계자 통계는
희소할 수 있으므로 count와 rate를 함께 유지한다.

## C. Audit only

125개 Feature 중 `AUDIT_ONLY`는 0개다. 다음 22개 비-Feature 컬럼은 추적·PIT·타깃 감사에만
사용하고 모델 입력에서 제외한다.

`snapshot_id`, `snapshot_version`, `race_id`, `horse_id`, `race_date`,
`feature_as_of`, `jockey_id`, `trainer_id`, `owner_id`, `source_batch_id`,
`policy_version`, `history_window_start_date`, `source_max_event_date`,
`history_complete`, `population_proxy`, `place_hit`, `result_status`,
`is_valid_start`, `is_valid_finish`, `population_exclusion_reason`,
`semantic_version`, `created_at`

`place_hit`은 target이고 나머지는 식별·lineage·모집단 감사 정보다. 식별자 자체와 식별자로
계산된 Historical statistics를 구분한다.

## D. Structural exclusion — 6개

| 제외 Feature | 유지하는 정보 | 관계 |
|---|---|---|
| `horse_prior_finish_count` | prior start count + finish rate | `start_count × finish_rate` |
| `horse_prior_win_count` | prior start count + win rate | `start_count × win_rate` |
| `horse_prior_top3_count` | prior start count + top3 rate | `start_count × top3_rate` |
| `horse_history_available` | prior start count | `start_count > 0` |
| `jockey_history_available` | jockey prior start count | `count > 0` |
| `trainer_history_available` | trainer prior start count | `count > 0` |

전체 85,566행에서 세 count 복원 관계와 세 flag 관계 위반은 각각 0건이다. 이 제외는
상관관계가 아니라 정의상 중복을 근거로 한다. count와 rate 자체는 서로 다른 정보이므로 유지한다.

## E. Logical exclusion — 2개

- `horse_recent3_race_time_median`
- `horse_recent5_race_time_median`

두 값은 여러 거리·경마장의 절대 경주시간을 한 말의 최근 이력 안에서 섞는다. `distance_m`과
`meet_code`를 함께 넣어도 절대시간 자체의 조건 차이가 없어지지 않는다. Validation 성능으로
포함 여부를 다시 선택하지 않고 official baseline 입력에서 확정 제외한다. 관측 깊이를 나타내는
race-time count는 속도 크기가 아니므로 유지한다. 후속에는 동일거리 또는 동일 경마장×거리
요약이나 별도 정규화값을 새 Feature 버전으로 설계한다.

## 구조적 중복과 부분 중복

현재 표본에서 다음 count가 완전히 같았다.

- recent3: race time count = G3F count = G1F count
- recent5: race time count = G3F count = G1F count
- `horse_recent5_start_count = horse_recent5_weight_count`

이는 현재 원천의 높은 가용성 때문에 우연히 같은 것이다. 향후 sectional 또는 마체중이 빠지면
달라질 수 있어 정의상 중복으로 보지 않고 각각 유지한다.

부분 중복은 다음과 같이 명시적으로 허용한다.

- 전체 prior / recent3 / recent5 / recent10: 시간 민감도가 다름
- 전체 / 동일거리 / 동일 경마장 / 동일 경마장×거리: 조건 통제 수준이 다름
- count / rate: 경험량과 결과 비율이 다름
- count / average: 표본 신뢰도와 수준이 다름

## 결측 의미와 향후 전처리 원칙

- 현재 정보: 미공개·원천 결측·parsing 실패를 의미한다. 현재 마체중 증감은 3,395행이 NULL이다.
- 말 이력: 과거 출전 자체가 없거나 유효 관측이 부족하다. prior/recent count로 구분한다.
- 조건 이력: 전체 이력은 있어도 동일거리·경마장 조건 이력이 없을 수 있다.
- 관계 이력: 개체 ID 또는 해당 관계의 과거 이력이 없을 수 있다.
- sectional: 말 이력 부족과 해당 기록 미관측을 companion count로 구분한다.
- 구조적 경마장/거리 미존재: 공통 S1F/G3F/G1F에서는 관측된 거리 전체에 원천이 있어 현재
  Snapshot에는 확인되지 않았다. 경마장 전용 raw 필드는 모델 후보에 포함하지 않았다.

따라서 향후 전처리에서 연속값을 단순 중앙값으로만 대체하면 안 된다. 대체값은 Train에서만
학습하되 count를 함께 입력하고, 현재 사전정보 자체의 결측은 별도 missing indicator가 필요한지
전처리 계약에서 결정한다. 구체적인 대체 통계는 이번 단계에서 계산하지 않았다.

## Feature family별 official 입력 수

| Family | 입력 수 |
|---|---:|
| 현재 경주 조건 | 14 |
| 현재 출전마·경주 기본정보 | 9 |
| 현재 마체중 | 2 |
| 기타 경주 전 관측정보 | 3 |
| 말 장기 이력 | 13 |
| recent form | 25 |
| 동일 거리 이력 | 4 |
| 동일 경마장 이력 | 4 |
| 동일 경마장×거리 이력 | 4 |
| race time 이력 | 2 |
| S1F 이력 | 4 |
| G3F 이력 | 4 |
| G1F 이력 | 4 |
| 마체중 이력 | 5 |
| 기수 이력 | 6 |
| 조교사 이력 | 6 |
| 마주 이력 | 2 |
| 말×기수 조합 이력 | 4 |
| 말×조교사 조합 이력 | 2 |
| 합계 | 117 |

## 후속 family-level ablation 계약

실험 순서는 성능 결론이 아니라 비교 단위를 고정하기 위한 것이다.

1. 현재 경주·출전마 기본정보: 기본정보 + 경주조건 + 현재 환경
2. 말 장기 성적: prior 성적·rating·부담중량·휴식일
3. recent form: recent3/5/10
4. 조건 적성: 동일거리 + 동일 경마장 + 동일 경마장×거리
5. 속도·sectional: S1F + G3F + G1F + race-time availability
6. 마체중: 현재 마체중 + Historical 마체중
7. 관계자: 기수 + 조교사 + 마주
8. 말×관계자 interaction: 말×기수 + 말×조교사

각 실험은 family 전체와 그 companion count를 함께 추가·제거해야 한다. count만 남기거나 rate만
남기는 방식으로 family 효과를 왜곡하지 않는다.

## 모델 학습 전 남은 결정

1. 현재 사전정보 NULL에 별도 missing indicator를 만들지 전처리 계약에서 결정한다.
2. 범주형 변수의 저빈도 수준 처리와 미지 범주 정책을 Train-only 원칙으로 정한다.
3. 117개 입력을 사용하는 첫 알고리즘과 전처리 절차를 별도 모델 계약으로 봉인한다.

Snapshot·PIT·모집단 관점의 blocker는 없다. 다만 2024~2026만 사용하는 모델은 left-censoring과
짧은 관측기간 제한을 그대로 가진다. 2022·2023 확장은 별도 데이터 버전에서 수행한다.

## 근거와 재현성

- Feature 정의: `docs/place-feature-registry-v2.csv`
- 125개 전수 판정: `docs/official-place-baseline-v2-model-input-inventory.csv`
- Snapshot 구현·감사: `docs/place-feature-snapshot-v2-build.md`
- 판정 생성기: `scripts/design_official_baseline_v2_inputs.py`
- 검증 요약: `data/exports/validation/official_place_baseline_v2_input_contract/summary.json`
