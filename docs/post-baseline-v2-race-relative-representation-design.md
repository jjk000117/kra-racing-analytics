# Post-baseline v2 Race-relative Representation 설계 감사

기준일: 2026-09-09  
상태: `R1` 논리 계약 제안, Feature·Snapshot·모델 미구현

## 결론

현재 `LT1` 137개는 117개 baseline, F1 6개, F3 10개, T1 4개로 구성된다. 이 중 F3는 오늘
경쟁자 사이의 위치를 직접 나타내고 F1은 과거 경주 안의 상대 경기력을 현재 말의 history로 요약한다.
F3가 development와 별도 Validation에서 반복 개선됐다는 사실은 상대 표현의 연구 우선순위를
뒷받침하지만, 새로운 상대값의 추가 성능은 아직 검증되지 않았다.

첫 후속 bundle은 **기존 absolute 값은 유지하면서 higher-is-better field percentile 7개만 추가하는
`R1`**으로 제한한다. 동일 원본의 percentile·z-score·median gap·best gap을 동시에 만들지 않는다.
Race-level field-strength summary는 다른 질문이므로 첫 R1에서 분리한다.

## 현재 137개 안의 상대 표현

| 구분 | Feature | 상대 기준 | 표현·방향 | NULL/가용성 | 확인된 성능 근거 |
|---|---|---|---|---|---|
| F1 | recent3/5 race-relative time advantage median | 각 과거 경주의 유효 완주마 median time | 양수=과거 경주 내 빠름 | 유효 완주·시간·비교마 3두 이상, count 동반 | F1은 B0 대비 development 4/4 개선 |
| F1 | recent3/5 race-time percentile median | 각 과거 경주의 유효 완주마 | 0=열위, 1=우위, average rank | 같은 F1 조건, count 동반 | 위와 동일 |
| F1 | recent3/5 race-relative time count | 위 과거 비교집단 | 유효 관측 수 | 0은 관측 없음 | 관리와 결측 맥락 |
| F3 | rating field percentile | 오늘 경주의 rating 보유마 | 0=열위, 1=우위 | 본인 NULL 또는 비교마 3두 미만이면 NULL | F3는 development 4/4 개선 |
| F3 | carried weight vs field median | 오늘 경주의 부담중량 보유마 | kg 차이, 양수=중앙값보다 무거움 | 같은 규칙 | F3 bundle 근거에 포함 |
| F3 | prior/recent5/same-distance PLC field percentile | 오늘 경주의 해당 PIT history 보유마 | 0=열위, 1=우위 | 같은 규칙, 원본 count 유지 | F3 bundle 근거에 포함 |
| F3 | jockey/trainer recent10 PLC field percentile | 오늘 경주의 관계자 PIT history 보유마 | 0=열위, 1=우위 | 같은 규칙 | F3 bundle 근거에 포함 |
| F3 | recent5 S1F/G3F/G1F field percentile | 오늘 경주의 sectional history 보유마 | 짧을수록 우위가 높도록 변환 | 같은 규칙 | F3 bundle 근거에 포함 |

F1의 상대 기준은 **과거 경주의 field**이고 F3의 상대 기준은 **현재 경주의 field**다. T1 네 개는
순서 trend이지 상대 표현이 아니다. 따라서 R1은 F1·F3와 이름과 의미가 겹치지 않는 현재 field
cross-section만 추가한다.

## 117개 absolute Feature 전수 분류 요약

| 분류 | 주요 family | 판단 |
|---|---|---|
| 이미 F3 상대화 | rating, 부담중량, 말 prior/recent5/same-distance PLC, 기수·조교사 recent10 PLC, recent5 sectional | 재생성 금지 |
| R1 채택 | 말 same-meet/same-meet-distance PLC, 기수·조교사 same-meet PLC, 마주 prior PLC, 말×조교사 prior PLC, F1 recent5 time percentile | 현재 상대 강도라는 새 문맥과 높은 가용성 |
| 후순위 | 말×기수 recent10/same-meet PLC | development 계산 가능률 약 56%로 첫 bundle에는 희소 |
| 중복·거친 표현 | recent3 Top3, win/finish/average rank의 다수 window | recent level이 이미 풍부하고 recent3 Top3는 동률 행 91.54% |
| 상대화 부적합 | count, availability, binary flag, ID/lineage, 경주 공통 조건, 범주형 조건 | 순위가 표본 신뢰도나 의미를 훼손하거나 경주 내 값이 동일 |
| 별도 연구 질문 | field median/top-k/spread 등 race-level strength | 말의 상대 위치가 아니라 경주 난이도·확률 기준선 문제 |

## 상대화 방식 비교

| 방식 | 보존 정보 | 장점 | 위험·중복 | 첫 R1 |
|---|---|---|---|---|
| Percentile | 경주 내 순서와 두수 보정 위치 | 단위가 다른 rate를 0~1로 통일, Logistic에 단조 효과로 투입 가능 | 절대 격차 소실, 이산 rate의 tie가 많음 | 채택 |
| Median difference | 중앙 경쟁자 대비 원단위 격차 | scale과 실질 격차 보존, outlier에 강함 | rate family에서는 범위가 같아 percentile과 중복 | 제외 |
| Z-score | 평균 대비 표준편차 단위 거리 | field dispersion까지 반영 | 작은 field·낮은 분산·outlier에 민감, std=0 처리 필요 | 제외 |
| Best gap | 최상위 경쟁자와의 원단위 격차 | 선두와의 거리 해석 용이 | 단일 extreme에 민감, percentile과 강한 중복 | 제외 |

Percentile은 F3와 같은 average-rank 정의를 재사용한다. 유효 비교마 수를 `n`, 오름차순 rank를
`r`, 같은 값의 개수를 `t`라 하면 higher-is-better percentile은

`(r + (t - 1) / 2 - 1) / (n - 1)`

이다. 동률은 average rank, 최저 0, 최고 1이다. 본인 원본이 NULL이거나 같은 경주의 유효 비교마가
3두 미만이면 NULL이다.

## 제안 R1: 7개

| Feature | 원본 | 정확한 계산 | 개발 가용률 | 기존 F3와 다른 정보 |
|---|---|---|---:|---|
| `horse_same_meet_plc_hit_rate_field_percentile` | `horse_same_meet_plc_hit_rate` | 현재 race 내 higher-is-better percentile | 93.84% | 전체/동일거리와 다른 경마장 적응 상대위치 |
| `horse_same_meet_distance_plc_hit_rate_field_percentile` | `horse_same_meet_distance_plc_hit_rate` | 동일 | 73.33% | 경마장×거리 결합 적성의 상대위치 |
| `jockey_same_meet_plc_hit_rate_field_percentile` | `jockey_same_meet_plc_hit_rate` | 동일 | 99.72% | recent10 일반 성적이 아닌 해당 경마장 성적 |
| `trainer_same_meet_plc_hit_rate_field_percentile` | `trainer_same_meet_plc_hit_rate` | 동일 | 99.92% | recent10 일반 성적이 아닌 해당 경마장 성적 |
| `owner_prior_plc_hit_rate_field_percentile` | `owner_prior_plc_hit_rate` | 동일 | 99.71% | F3에 없던 현재 field의 마주 이력 위치 |
| `horse_trainer_prior_plc_hit_rate_field_percentile` | `horse_trainer_prior_plc_hit_rate` | 동일 | 91.92% | 말×조교사 조합을 경쟁 조합과 직접 비교 |
| `horse_recent5_race_time_percentile_median_field_percentile` | `horse_recent5_race_time_percentile_median` | 동일 | 94.29% | 과거 경주 내 상대력이 오늘 field에서 차지하는 위치 |

모든 원본 absolute Feature와 companion count는 그대로 유지한다. R1은 이를 대체하지 않는다.
마지막 Feature는 F1을 다시 계산하지 않고, 이미 PIT-safe하게 계산된 F1 recent5 수준을 현재 field에서
한 번만 상대화한다. F1 자체는 과거 상대력이고 R1은 오늘 상대와의 위치라 기준 집단이 다르다.

## Development-only 가용성 감사

대상은 `2023-01-01 <= race_date < 2024-07-01`의 28,392행·2,675경주이며 target과 모델 성능을
읽지 않았다. 경주별 등록두수는 8~16두이고 11두 경주가 1,259경주로 가장 많다.

| 원본 | 2023 | 2024-H1 | 서울 | 부산경남 | tie 행 비율 |
|---|---:|---:|---:|---:|---:|
| horse same-meet PLC | 93.04% | 95.44% | 94.18% | 93.38% | 37.89% |
| horse same-meet-distance PLC | 72.50% | 75.00% | 73.54% | 73.05% | 60.02% |
| jockey same-meet PLC | 99.76% | 99.65% | 99.81% | 99.60% | 0.25% |
| trainer same-meet PLC | 99.89% | 99.97% | 99.92% | 99.91% | 14.00% |
| owner prior PLC | 99.70% | 99.74% | 99.69% | 99.75% | 6.25% |
| horse×trainer prior PLC | 91.05% | 93.66% | 92.32% | 91.36% | 39.98% |
| F1 recent5 time percentile median | 93.47% | 95.92% | 94.51% | 93.98% | 20.98% |

동률 비율은 결함이 아니라 작은 history count에서 rate가 같은 이산성이다. average rank로 처리하며
별도 jitter를 만들지 않는다. Same-meet-distance는 가장 희소하지만 양 경마장과 두 시기 모두 72% 이상이라
첫 질문을 검증할 수 있다. 계산 불가를 0으로 바꾸지 않고 fold Train median 처리 계약을 적용한다.

## Field-strength Feature 판단

`field median rating`, `field top3 rating mean`, `field rating spread`, `field median recent PLC`는
PIT-safe하게 만들 수 있다. 그러나 같은 경주의 모든 말 행에 같은 값이 반복되므로 runner 순위는 바꾸지
않고 경주 전체의 intercept·확률 수준만 조정한다. 등록두수와 경주 조건도 이미 있으므로, 이를 R1에
섞으면 horse-relative 표현 효과와 race-level 난이도 효과를 분리할 수 없다. 첫 R1에서는 제외하고
향후 별도 `FS1` 가설로 남긴다.

## PIT·leakage 계약

1. R1 계산 입력은 prediction cutoff에 이미 존재하는 현재 row의 PIT-safe Historical Feature뿐이다.
2. 모든 원천 history는 기존 `historical.race_date < feature_as_of` 계약을 승계한다.
3. 현재 경주의 `place_hit`, 착순, race time, sectional 결과, 착차, 배당·확정배당을 참조하지 않는다.
4. 같은 현재 `race_id` 안에서 본인 원본이 non-null인 말만 비교집단에 포함한다.
5. 유효 비교마 3두 미만이면 NULL이며, count·availability를 새로 sparse conditioning하지 않는다.
6. tie는 average rank로 처리하고 field size 차이는 `(n-1)` 분모로 정규화한다.

## 후속 실험 계약

- Control: `LT1`, 동일 Logistic + 137개
- Candidate: `LR1`, 동일 Logistic + 기존 137개 + R1 7개 = 144개
- 동일 development 기간, 모집단, target, 네 expanding quarterly fold, Train-only 전처리, raw probability,
  평가 함수와 seed를 사용한다.
- R1은 모두 연속형이며 fold Train median 대체와 기존 scaling을 적용한다.
- Macro Log Loss와 Macro Brier의 평균 방향, 동시 개선 fold 수, 변동성과 calibration 악화 여부로
  기존 bundle 정책에 따라 KEEP/CONDITIONAL/DROP한다.
- 결과를 본 뒤 원본, 표현, 7개 구성이나 NULL 규칙을 바꾸지 않는다.
- Validation은 접근하지 않는다.

설계 blocker는 없다. 구현 단계에서 registry 1:1, percentile 범위, average-rank 표본 재계산,
비교마 3두 규칙, NULL 전파, 경주별 동일 원천 재현, PIT와 protected hash를 감사해야 한다.

## 확인된 사실

- LT1 137개에는 F1의 과거 경주 상대정보 6개와 F3의 현재 field-relative 정보 10개가 있다.
- F3는 development 4/4 fold와 별도 Validation 12/12개월에서 두 Macro 손실을 개선했다.
- R1 원본 7개의 development 계산 가능률은 73.33%~99.92%다.
- 말×기수 rate 후보는 약 56%, recent3 Top3 rate는 tie 91.54%라 첫 bundle에서 제외했다.
- 이번 감사에서는 target, 모델 prediction, Validation 및 2024-07 이후 데이터를 사용하지 않았다.

## Relative representation에 대한 미검증 가설

- 경마장 및 경마장×거리 성적의 오늘 field 내 위치가 기존 same-distance·same-meet absolute 값을 넘어
  추가 정보를 제공한다.
- 관계자·마주·말×조교사 strength의 상대위치가 absolute rate와 count의 additive 효과를 보완한다.
- 과거 경주 상대력의 최근 수준을 오늘 경쟁자 사이에서 다시 위치시키는 것이 F1 수준 자체와 다르다.

## 후속 실험 질문

동일 Logistic과 temporal CV에서 R1 7개만 추가한 `LR1(144)`이 `LT1(137)`보다 Macro Log Loss와
Macro Brier를 여러 fold에서 반복 개선하는가? 개선되지 않으면 R1을 DROP하고 사후에 표현 방식을
바꾸지 않는다.
