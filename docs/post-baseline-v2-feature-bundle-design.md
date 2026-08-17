# Post-baseline v2 F1/F2/F3 Feature bundle 설계·감사

기준일: 2026-08-18  
상태: 논리 계약 봉인 제안, Feature·Snapshot·모델 미구현

## 기술 요약

M1은 동일 117개 정보에 모델 복잡도만 추가했지만 B0를 안정적으로 개선하지 못했다. 다음 실험은
Logistic을 고정하고 기존 입력이 행 단위로 직접 표현하지 못하는 정보만 세 묶음으로 추가한다.

- F1 6개: 과거 같은 경주 안의 시간 우위 크기와 두수 보정 순서를 recent3/5로 요약한다.
- F2 8개: 같은 과거 경주에서 함께 관측된 sectional로 마지막 가속과 초반-후반 형태를 만든다.
- F3 10개: cutoff 시점의 현재 출전마 집단 안에서 핵심 절대·과거정보의 상대 위치를 만든다.

각 묶음은 기존 117개를 유지한 채 독립적으로 더한다. 성능을 보기 전 정의를 바꾸지 않는다.
현재 경주 결과·시간·sectional·배당은 어느 계산에도 사용하지 않는다.

## F1은 margin과 percentile 두 표현만 유지한다

Historical race의 비교집단은 `is_valid_finish=true`, 정상 완주 상태, 유효 `race_time_seconds > 0`인
출전마다. DNS·주행중지·실격·취소·비정상 결과와 유효 시간이 없는 말은 제외한다. 비교 가능한 말이
3두 미만이면 그 경주의 상대시간 이벤트 전체를 NULL로 둔다.

과거 경주 이벤트 `h`에서:

- `time_advantage_h = median(valid_times_h) - runner_time_h`
  - 초 단위이며 양수일수록 경주 중앙값보다 빠르다.
- `time_percentile_h = (n_h - average_rank_ascending(time_h)) / (n_h - 1)`
  - 0~1이며 1이 가장 빠르다. 동률은 average rank를 쓴다.

두 값은 각각 시간 차이의 크기와 순서 정보를 제공한다. `runner-best`는 한 명의 극단값에 민감하고
`runner-median`과 같은 위치 이동을 공유하므로 제외한다. raw rank는 출전두수 차이에 취약하고
percentile과 중복되어 제외한다.

각 event 값을 최신 유효 3건과 5건에서 median으로 집계하고, window별 공통 valid count를 둔다.
따라서 F1은 `2 quantities × 2 windows + 2 counts = 6개`다. recent3는 단기 변화를, recent5는
조금 더 안정적인 수준을 표현하므로 둘을 유지한다.

같은 과거 경주 안에서 상대화하면 거리, 경마장, 날씨, 주로와 당일 공통 pace 수준을 상당 부분
제거한다. 하지만 상대했던 말의 질, 전개, 착차 측정, 경주별 field strength 차이는 남는다. 이는
class-adjusted speed figure가 아니며 그런 의미로 해석하지 않는다.

## F2는 정확히 두 개의 event-level pace quantity만 유지한다

모든 입력은 이미 서울·부산경남에서 같은 물리 구간과 초 단위로 정규화된 Historical S1F/G3F/G1F다.
동일 과거 경주 이벤트에서 필요한 sectional이 함께 유효할 때만 계산한다.

1. `late_kick_advantage = ((G3F - G1F) / 2) - G1F = (G3F - 3×G1F) / 2`
   - 단위: 200m당 초 차이
   - 양수: 마지막 200m가 그 직전 400m의 평균 200m보다 빠름
   - 음수: 마지막 200m 감속
2. `finish_vs_start_advantage = S1F - G1F`
   - 단위: 200m 구간 초 차이
   - 양수: 마지막 200m가 첫 200m보다 빠름
   - 음수: 마지막 구간이 첫 구간보다 느림

`G1F-G3F/3`은 `late_kick_advantage`의 정확한 `-2/3`배이므로 제거한다. `(G3F-G1F)/2`는
직전 400m의 평균 시간일 뿐 단독으로는 shape가 아니며 기존 G3F/G1F 수준과 겹쳐 제거한다.

기존 Feature는 S1F/G3F/G1F를 각각 별도로 median한 값이다. F2는 먼저 같은 event 안에서 차이를
계산한 뒤 median하므로 일반적으로 기존 median들의 선형조합과 같지 않고, 구간 간 공동 전개정보를
추가할 수 있다.

각 quantity마다 최근 유효 3건/5건 median과 별도 count를 둔다. 필요한 sectionals의 결측 조합이
다르므로 count를 공유하지 않는다. F2는 `2 quantities × 2 windows × (median+count) = 8개`다.

## F3는 오늘 상대 안의 위치가 해석 가능한 핵심 10개만 추가한다

117개 입력 전수 분류는 `docs/post-baseline-v2-f3-relative-classification.csv`에 저장했다.

- A: 경주 내 상대화가 논리적으로 유용 — 41개
- B: 조건부로 유용 — 18개
- C: 의미가 작거나 기존 값과 중복 — 37개
- D: 경주 공통·범주·lineage 성격으로 상대화 금지 — 21개

최종 F3는 A 전체를 기계적으로 확장하지 않고 다음 10개만 사용한다.

| 원본 | 상대 표현 | 선택 이유 |
|---|---|---|
| rating | 높은 값 우수 percentile | 오늘 상대 중 공식 능력 위치 |
| carried_weight | runner-field median kg | 높고 낮음이 우열은 아니지만 상대 부담 차이 |
| horse prior PLC rate | 높은 값 우수 percentile | 장기 PLC 수준의 상대 위치 |
| horse recent5 PLC rate | 높은 값 우수 percentile | 최근 PLC form의 상대 위치 |
| same-distance PLC rate | 높은 값 우수 percentile | 오늘 거리 적성의 상대 위치 |
| jockey recent10 PLC rate | 높은 값 우수 percentile | 상대 기수 최근 form |
| trainer recent10 PLC rate | 높은 값 우수 percentile | 상대 조교사 최근 form |
| recent5 S1F median | 낮은 시간이 우수한 percentile | 오늘 field 내 과거 초반속도 위치 |
| recent5 G3F median | 낮은 시간이 우수한 percentile | 오늘 field 내 과거 종반 600m 위치 |
| recent5 G1F median | 낮은 시간이 우수한 percentile | 오늘 field 내 과거 종반 200m 위치 |

장기·recent·조건별 rate를 모두 상대화하면 높은 상관의 rank 묶음만 늘어난다. recent3/10,
same-meet-distance, owner와 interaction rate는 첫 F3에서 제외한다. 특히 sparse rate는 원본 count가
작을수록 순위가 과신될 수 있다. 선택된 rate도 기존 companion count를 반드시 함께 유지하고,
percentile이 count를 대체하거나 신뢰도 보정을 했다고 해석하지 않는다.

## 공통 상대화 규칙

`n`은 해당 Feature가 non-null인 같은 현재 경주의 비교 가능 출전마 수다.

- 동률: average rank
- higher-is-better percentile: `(average_rank_ascending - 1)/(n - 1)`
- lower-is-better percentile: `(n - average_rank_ascending)/(n - 1)`
- 범위와 방향: percentile은 0=열위, 1=우위로 통일
- `n < 3`: 상대값 NULL
- 원본이 NULL인 말: 비교집단에서 제외하고 해당 말 상대값도 NULL
- field median difference: `runner_value - median(non-null field values)`; 부담중량은 우열 방향을 부여하지 않음
- 원본 117개와 기존 count는 모두 유지하고 상대 Feature만 추가
- 한 원본에서 rank+percentile+difference를 동시에 만들지 않음
- `registered_runner_count`가 전체 field 크기를 제공하므로 새 comparable count는 만들지 않는다.
  다만 구현 audit에서 non-null 비교 가능 수를 계산해 `n>=3` 조건과 NULL을 검증한다.

F3는 동일 `race_id`의 prediction cutoff 이전 값만 window 함수로 상대화한다. 역사적 rate와 sectional은
각 말에서 이미 `historical.race_date < feature_as_of`를 만족해야 한다. 현재 경주의 outcome, payout,
race time, sectional과 착차는 join하거나 참조하지 않는다.

## Bundle 간 중복 경계

- F1은 과거 **동일 경주 결과 안**의 race-time 상대성이다.
- F3 sectional percentile은 각 말의 기존 **과거 요약값을 현재 출전 field 안**에서 비교한다.
  비교 시점과 대상이 달라 둘을 중복으로 보지 않는다.
- F2는 같은 과거 event의 구간 간 차이이며 기존 개별 sectional median과 정확히 같지 않다.
- F3는 PLC·sectional마다 대표 window 하나만 선택해 rate/rank 파생의 반복을 줄였다.
- F1 race-time percentile을 다시 F3에서 상대화하지 않는다.
- F2 pace quantity를 F3에서 다시 field percentile로 만들지 않는다.

## PIT·leakage 방지 계약

1. F1/F2 source event는 반드시 `historical.race_date < current.feature_as_of`다.
2. F1 비교집단의 다른 말 결과도 동일한 과거 race에 한정되며 그 race 전체가 현재 시점보다 과거다.
3. F2는 같은 과거 event의 co-observed sectionals만 사용하고 현재 event sectionals는 사용하지 않는다.
4. F3는 동일 현재 race의 cutoff-known 원본 117개만 사용한다.
5. 현재 결과·배당·시간·sectional·착차·확정 배당 컬럼은 Feature SQL에 존재해서는 안 된다.
6. window ranking은 날짜뿐 아니라 `race_id` tie-break를 사용하며 future row가 window에 들어가면 실패한다.
7. DNS 정책과 modeling population proxy는 기존 확정 계약을 승계한다. 실제 운영에서는 cutoff 시점의
   최종 베팅 가능 roster가 필요하다는 기존 limitation을 유지한다.

## 구현 전 미확정 사항

설계 blocker는 없다. 다만 구현 단계에서 다음을 수치 감사해야 한다.

- F1 eligible historical race cohort와 `n>=3` 적용 후 가용률
- F2 두 quantity별 공동 sectional 가용률과 count 관계
- F3 각 원본별 comparable `n>=3` 충족률
- recent3 count ≤ recent5 count 및 값/count NULL 관계
- 동일 입력을 여러 bundle에서 중복 생성하지 않았는지

가용률은 구현 품질 판단에 사용하되 성능을 보기 전 Feature 정의를 바꾸는 근거로 사용하지 않는다.

## 독립 실험 계약

- B0: Logistic + 기존 117
- F1: Logistic + 117 + 6
- F2: Logistic + 117 + 8
- F3: Logistic + 117 + 10

동일 네 development temporal fold, 동일 B0 전처리·모델·지표를 사용한다. 각 bundle은 별도 Snapshot
candidate와 Feature hash로 관리하며 서로 결합하지 않는다. 이 문서와 registry를 실행 전에 봉인하고
development 결과를 본 뒤 수식·window·결측 규칙을 소급 변경하지 않는다.

차트는 사용하지 않았다. 이번 산출물은 관측 성능의 비교가 아니라 117개 정의와 파생 관계의 정확한
lookup·감사 계약이므로 표와 machine-readable registry가 더 적합하다.
