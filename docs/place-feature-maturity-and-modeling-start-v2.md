# Historical warm-up 및 official place baseline v2 모델링 시작일

## 결론

2022년 전체를 Historical warm-up으로 사용하고 **2023-01-01을 official place baseline v2의 모델링 시작일로 권고한다.** 모델 성능이나 타깃과 Feature의 관계는 사용하지 않았으며, 117개 MODEL_INPUT의 월별 결측·관측 count와 모집단 규모만으로 판단했다.

2022년 초의 left-censoring은 뚜렷하지만 2022년 중반부터 horse·기수·조교사·마주와 기본 속도/sectional 이력이 크게 성숙한다. 2023년 1월에는 horse long-term 93.91%, same-meet 93.83%, 속도·sectional·마체중 이력 93.91%, 기수 99.33%, 조교사 100%, 마주 99.55%가 최소 한 건 이상의 과거 관측을 갖는다. 한편 recent10 완전창과 horse×jockey는 계속 점진적으로 성숙하므로 완전한 단절점은 없다. 이 때문에 임의 threshold 대신 한 해 전체를 warm-up으로 사용하는 달력 경계를 채택한다.

## 분석 계약

- 원천: `mart.place_feature_snapshot_v2_candidate`
- 분석 Grain: 월 × valid-start 출전마 행; 경주 수는 별도 distinct 집계
- 프로파일 기간: 2022-01 ~ 2023-07
- Feature: 기존 117개 MODEL_INPUT
- 모델 학습·예측·성능평가·Feature 선택: 수행하지 않음
- PLC 양성률: 모집단 기술통계로만 기록
- Historical 관측 여부: NULL만 보지 않고 각 family의 `prior_start_count`, recent count, 조건별 count 또는 companion count를 사용
- recent3/5/10은 `count > 0`과 별도로 각각 3/5/10회가 모두 확보된 `full window` 비율을 계산

## 월별 표본 규모

| 월 | 경주 수 | 출전마 행 | PLC 양성률 |
|---|---:|---:|---:|
| 2022-01 | 136 | 1,663 | 24.53% |
| 2022-02 | 102 | 1,321 | 23.16% |
| 2022-03 | 136 | 1,470 | 27.69% |
| 2022-04 | 153 | 1,606 | 28.58% |
| 2022-05 | 153 | 1,572 | 29.01% |
| 2022-06 | 135 | 1,411 | 28.63% |
| 2022-07 | 181 | 1,700 | 30.12% |
| 2022-08 | 116 | 1,216 | 28.54% |
| 2022-09 | 112 | 1,241 | 27.16% |
| 2022-10 | 167 | 1,778 | 28.18% |
| 2022-11 | 144 | 1,571 | 27.56% |
| 2022-12 | 144 | 1,582 | 27.31% |
| 2023-01 | 115 | 1,346 | 25.63% |
| 2023-02 | 150 | 1,683 | 26.80% |
| 2023-03 | 148 | 1,614 | 27.57% |
| 2023-04 | 167 | 1,726 | 29.08% |
| 2023-05 | 131 | 1,350 | 28.96% |
| 2023-06 | 143 | 1,505 | 28.50% |
| 2023-07 | 152 | 1,559 | 29.31% |

월별 경주는 102~181경주, 출전마는 1,216~1,778행으로 모든 월에 표본이 존재한다. PLC 양성률은 모델 시작일 결정에 사용하지 않았다.

## 주요 Historical family maturity

다음은 출전마 행 기준 관측 가용률이다. recent 계열은 지정된 N회가 모두 확보된 비율이다.

| 시점 | horse long-term | recent3 full | recent5 full | recent10 full | same-distance | same-meet | horse×jockey | horse×trainer |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022-01 | 7.22% | 0.00% | 0.00% | 0.00% | 3.49% | 7.22% | 2.41% | 7.22% |
| 2022-06 | 92.70% | 72.93% | 29.55% | 0.07% | 72.22% | 91.64% | 50.89% | 90.57% |
| 2022-09 | 90.57% | 76.55% | 58.98% | 6.04% | 69.46% | 90.41% | 53.91% | 89.12% |
| 2022-12 | 90.27% | 72.19% | 60.11% | 19.72% | 64.16% | 89.57% | 50.63% | 88.75% |
| 2023-01 | 93.91% | 75.11% | 58.69% | 22.66% | 60.03% | 93.83% | 48.22% | 91.98% |
| 2023-03 | 95.85% | 85.63% | 69.52% | 35.25% | 76.33% | 95.85% | 61.09% | 93.99% |
| 2023-07 | 91.21% | 82.17% | 73.89% | 43.10% | 71.26% | 90.44% | 52.92% | 86.27% |

속도/race-time, S1F, G3F, G1F 및 마체중 이력은 각 시점의 horse long-term 가용률과 거의 같다. 2023-01에는 모두 93.91%다. 기수·조교사·마주 이력은 2022년 중반부터 약 99~100%다.

월별 비율이 단조 증가하지 않는 것은 계산 오류가 아니라 새 말과 새로운 말×관계가 계속 유입되기 때문이다. 따라서 더 늦게 시작해도 horse 및 interaction left-censoring이 완전히 사라지지는 않는다.

## 2022 warm-up의 효과

2022년 초 3개월 가중평균과 이후 구간을 비교하면 다음과 같다.

| 구간 | horse | recent3 full | recent5 full | recent10 full | same-distance | horse×jockey |
|---|---:|---:|---:|---:|---:|---:|
| 2022 초(1~3월) | 53.97% | 2.63% | 0.02% | 0.00% | 28.15% | 22.97% |
| 2022 중반(6~8월) | 91.56% | 74.62% | 43.38% | 1.39% | 71.78% | 52.72% |
| 2022 후반(10~12월) | 90.43% | 73.21% | 59.32% | 13.43% | 67.80% | 49.95% |
| 2023 초(1~3월) | 95.24% | 80.94% | 64.72% | 29.08% | 70.39% | 55.01% |
| 2023 중반(5~7월) | 93.29% | 84.93% | 74.49% | 42.32% | 75.37% | 56.82% |

2022 warm-up은 기본 horse history와 recent3, same-condition, 관계자 이력을 크게 개선한다. recent10처럼 깊은 창은 2023년에도 계속 성숙하므로 count companion을 함께 사용하는 기존 계약이 중요하다.

## 시작일 후보 비교

| 후보 | 확보 경주/행 | 시작월 주요 상태 | 장점 | 한계 |
|---|---:|---|---|---|
| 2022-07-01 | 7,221 / 76,523 | horse 91.18%, recent5 full 47.24%, recent10 full 1.29% | 가장 긴 모델링 기간 | 깊은 recent history가 거의 없고 warm-up이 6개월뿐 |
| **2023-01-01** | **6,357 / 67,435** | horse 93.91%, recent5 full 58.69%, recent10 full 22.66% | 한 해 전체 warm-up, 명확한 달력 경계, 충분한 장기 표본 | recent10과 horse×jockey는 아직 부분 관측 |
| 2023-07-01 | 5,503 / 58,211 | horse 91.21%, recent5 full 73.89%, recent10 full 43.10% | 깊은 recent 창이 더 성숙 | 6개월을 추가로 잃고 신규 말·조합의 left-censoring은 여전히 존재 |

## 최종 권고

**모델링 시작일은 2023-01-01이 적절하다.** 2022년 전체를 Historical warm-up으로 사용하는 설명이 명확하고, 2023년 초에는 대부분의 장기·조건·관계자·속도·sectional·마체중 family가 충분한 과거 관측을 확보한다. 2023년 7월까지 기다리면 recent5/10은 개선되지만, 신규 개체와 조합 유입 때문에 모든 family가 단조롭게 완전해지는 것은 아니며 6개월의 유효 모델링 기간을 추가로 잃는다.

이 권고는 “모든 행에 완전한 10회 이력이 있다”는 뜻이 아니다. 충분한 이력이 없는 행은 기존 count companion과 NULL 계약으로 명시적으로 구분해야 한다.

## 산출물

- `data/exports/validation/place_feature_maturity_v2/monthly_sample.csv`
- `data/exports/validation/place_feature_maturity_v2/monthly_model_input_availability.csv`
- `data/exports/validation/place_feature_maturity_v2/monthly_family_maturity.csv`
- `data/exports/validation/place_feature_maturity_v2/monthly_family_maturity_wide.csv`
- `data/exports/validation/place_feature_maturity_v2/modeling_start_candidates.csv`
- `data/exports/validation/place_feature_maturity_v2/summary.json`
- 재현 스크립트: `scripts/profile_place_feature_maturity_v2.py`
