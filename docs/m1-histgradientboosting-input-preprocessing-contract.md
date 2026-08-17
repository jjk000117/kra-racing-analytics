# M1 HistGradientBoosting 입력·전처리 실행 계약

기준일: 2026-08-18  
상태: 실행 전 계약 제안 완료, 모델 학습·prediction·성능 계산 미수행

## 결론

M1은 official place baseline v2와 동일한 117개 정보를 사용한다. 입력은 범주형 11개와 수치형
106개다. 범주형은 fold-train에서만 적합한 `OrdinalEncoder`로 인코딩하고 HGB에 categorical
mask를 명시한다. 수치형은 기존 Logistic과 같은 fold-train median 결측 대체를 유지하되 scaling은
하지 않는다. Historical observation count 8개는 기존 계약과 같이 결측을 0으로 대체한다.

첫 실험은 아래 두 설정까지만 비교한다. A는 제시된 sklearn 기본 복잡도이고, B는 leaf 수와 L2만
보수적으로 제한해 A의 이점이 큰 leaf 구조에 의존하는지를 확인한다. Feature·전처리·fold·seed는
두 설정에서 동일하다.

## 117개 입력 구성

- 범주형 11개: `meet_code`, `race_grade`, `horse_sex`, `race_age_condition`,
  `race_weight_condition`, `race_prize_condition`, `race_sex_condition`, `race_type`,
  `race_day_of_week`, `current_weather`, `current_track_condition`
- 수치형 106개
- `meet_code`와 `race_day_of_week`은 원천 타입은 정수지만 의미상 명목형으로 유지한다.
- Feature 순서와 hash는 기존 117개 계약을 그대로 사용한다:
  `cc18ef4bf88438ccbfbe836a29aec34f5356e52976b834124a065c89e57e8d2b`.

## 범주 cardinality와 fold별 unseen

개발 loader의 28,392행만 사용했다. 괄호 안은 `unseen 범주 수 / 평가행 수 / 평가행 비율`이다.

| Feature | 전체 cardinality | Fold 1 | Fold 2 | Fold 3 | Fold 4 |
|---|---:|---:|---:|---:|---:|
| meet_code | 2 | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% |
| race_grade | 10 | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% |
| horse_sex | 3 | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% |
| race_age_condition | 8 | 0 / 0 / 0% | 0 / 0 / 0% | 1 / 65 / 1.381% | 0 / 0 / 0% |
| race_weight_condition | 4 | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% |
| race_prize_condition | 20 | 1 / 14 / 0.314% | 0 / 0 / 0% | 5 / 181 / 3.846% | 3 / 52 / 1.089% |
| race_sex_condition | 3 | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% |
| race_type | 87 | 16 / 202 / 4.531% | 29 / 346 / 6.617% | 6 / 83 / 1.763% | 9 / 109 / 2.283% |
| race_day_of_week | 4 | 0 / 0 / 0% | 1 / 228 / 4.360% | 0 / 0 / 0% | 0 / 0 / 0% |
| current_weather | 4 | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% |
| current_track_condition | 5 | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% | 0 / 0 / 0% |

모든 범주형 Feature는 개발기간 전체에서 NULL 0건이다. `race_type`은 기념경주명 등 일회성 값이
많아 unseen이 자연스럽다. 이를 전체기간 vocabulary로 미리 학습하지 않는다.

## 범주형 처리 계약

각 fold에서 다음 순서를 사용한다.

1. fold-train의 11개 범주만으로 `OrdinalEncoder`를 적합한다.
2. `handle_unknown='use_encoded_value'`, `unknown_value=np.nan`,
   `encoded_missing_value=np.nan`으로 평가의 unseen을 결측 category로 전달한다.
3. 변환된 11개 열의 위치를 `HistGradientBoostingClassifier.categorical_features`에 명시한다.
4. 범주 코드를 일반 연속 수치로 취급하지 않는다.

전체 최대 cardinality 87은 `max_bins=255`보다 작다. One-hot도 가능하지만 117개 정보를 185~244개
변환 열로 확장하고 각 category를 독립 binary split으로 처리한다. M1의 tree-native 범주 분할을
사용하면서 고차원 dense 행렬을 피하기 위해 native categorical 방식을 권장한다.

## 수치형 결측과 count

- 일반 수치형: fold-train median으로 대체한다. 평가 구간은 transform만 수행한다.
- Historical count 8개: 기존 Logistic 계약과 동일하게 NULL을 0으로 대체한다.
  - `horse_recent3_race_time_count`, `horse_recent3_s1f_count`,
    `horse_recent3_g3f_count`, `horse_recent3_g1f_count`
  - `horse_recent5_race_time_count`, `horse_recent5_s1f_count`,
    `horse_recent5_g3f_count`, `horse_recent5_g1f_count`
- count와 companion 값의 정보 구조는 변경하지 않으며 새 missing indicator를 추가하지 않는다.
- HGB가 NaN을 직접 처리할 수 있어도 이번 M1에서는 결측 처리 차이를 추가 변수로 만들지 않는다.

## Scaling

HGB의 split은 값의 순서를 기준으로 하므로 scaling이 필요하지 않다. scaling을 제거해도 Feature
정보는 바뀌지 않으며, tree에 불필요한 평균·표준편차 적합 단계를 만들지 않는다. Logistic과의
차이는 알고리즘에 필요한 표현 방식으로 한정하고 Feature 집합·결측값 대체 원칙은 유지한다.

## M1 후보 설정

공통 고정값: `loss='log_loss'`, `max_depth=None`, `min_samples_leaf=20`, `max_bins=255`,
`early_stopping=False`, `random_state=20260817`, `class_weight=None`.

| 설정 | learning_rate | max_iter | max_leaf_nodes | l2_regularization | 가설 |
|---|---:|---:|---:|---:|---|
| M1-A | 0.1 | 100 | 31 | 0.0 | sklearn 기본 크기의 tree가 Logistic에 없는 비선형·interaction을 포착할 수 있는가 |
| M1-B | 0.1 | 100 | 15 | 1.0 | 더 작은 leaf와 L2가 제한된 개발 표본에서 과도한 분할을 줄여 fold 안정성을 높이는가 |

제시된 M1-A 설정은 합리적이다. `early_stopping=False`는 내부 무작위 validation 분할을 만들지 않아
고정 temporal fold 계약과 맞는다. M1-B 외의 learning rate, iteration, depth, leaf 또는 L2 탐색은
수행하지 않는다.

## Logistic과의 공정 비교 조건

- 동일한 117개 Feature, 순서와 hash
- 동일한 네 quarterly expanding fold와 동일 행·경주 모집단
- fold-train에서만 encoder·median을 적합하고 평가에는 transform만 적용
- 동일 target, race-level macro 우선 지표와 기존 metric 구현
- 동일 seed 및 no-information 기준선
- calibration 없이 raw probability끼리 우선 비교
- 후보별 같은 fold 결과와 실패·실행시간을 registry에 모두 기록
- M1 결과를 보고 Feature, fold 또는 설정을 소급 변경하지 않음
- 기존 Validation 및 2024-07 이후 데이터 접근 금지

## 다음 실행 조건

다음 단계에서 M1-A와 M1-B를 registry에 먼저 등록·봉인한 뒤 네 development fold에서만 실행한다.
두 설정 중 선택은 사전 정의된 macro Log Loss, macro Brier, calibration과 fold 방향 일관성으로만
판단한다. 이번 작업에서는 모델 적합, prediction, 성능 계산과 F1/F2/F3 구현을 수행하지 않았다.
