# Official place baseline v2 후속 개선 실험 설계

기준일: 2026-08-18  
상태: 실험 계획 확정, 새 Feature·모델·prediction 미생성  
개발 근거: 2023-01~2025-06 Snapshot·Validation 결과 및 기존 Feature registry만 사용

## 결론

후속 개선은 두 축만 우선 검증한다.

1. **모델 복잡도:** 같은 117개 입력에 Gradient Boosted Trees를 적용해 Logistic이 표현하지
   못하는 비선형·threshold·interaction의 추가 가치를 분리해 측정한다.
2. **Feature 정보:** Logistic을 그대로 유지한 채 PIT-safe 상대 경주시간과 pace-shape bundle을
   각각 추가해 원천 정보 개선 효과를 분리해 측정한다.

2025-07-01~2026-07-26은 모든 후보가 개발기간 안에서 확정·봉인될 때까지 공통
`post-selection temporal evaluation`으로 보존한다. 이번 설계에서는 해당 기간의 데이터베이스,
target, prediction과 기존 로컬 평가 산출물을 새로 조회하지 않았다. 이전 집계 PLC 노출과
baseline_v1의 2026년 확인은 기존 limitation으로만 승계한다.

## 현재 Logistic baseline의 주요 한계

Validation에서 raw Logistic은 무정보 기준선보다 macro Log Loss를 약 0.0593, macro Brier를
약 0.0244 개선했다. 따라서 현재 117개에 정보가 없다는 문제가 아니다. 남은 개선 가설은
**같은 정보를 선형 log-odds로만 결합하는 제약**과 **조건을 섞지 않은 속도 표현의 부재**다.

Logistic은 현재 형태에서 다음을 직접 표현하지 못한다.

- 연령·rating·부담중량·마체중 증감의 비선형 또는 임계효과
- 등록두수에 따라 달라지는 gate·PLC 기본확률 효과
- 거리·경마장·주로에 따라 달라지는 sectional 효과
- 말 이력 count가 적을 때 rate의 신뢰도를 낮추는 count×rate interaction
- 최근 폼과 장기 폼의 차이가 특정 수준을 넘을 때만 나타나는 변화
- current condition과 historical affinity의 조건부 결합

One-hot 범주형과 수치형의 주효과만 넣은 Logistic은 이러한 관계를 사람이 명시적으로
interaction으로 만들어야 한다. 반면 tree 계열은 threshold와 제한되지 않은 저차 interaction을
데이터에서 표현할 수 있다. 다만 Validation 세그먼트 차이는 가설 생성 근거일 뿐, 특정 세그먼트에
맞춘 Feature를 사후 제작하는 근거로 사용하지 않는다.

## 권장 모델 family

### 우선 실험: Histogram Gradient Boosted Trees

권장 구현은 sklearn `HistGradientBoostingClassifier` 한 종류다.

- 연속 Feature의 비선형·threshold 효과를 표현한다.
- 등록두수×gate, 거리×sectional, history count×rate 같은 interaction을 별도 수식 없이 표현한다.
- 현재 표본 규모에서 계산량이 과도하지 않고 기존 sklearn 환경을 재사용할 수 있다.
- 결측을 자체 처리할 수 있지만 공정한 비교를 위해 범주 encoding과 결측 계약은 Train-fold
  안에서 고정한다.

내부 CV에서 비교할 설정은 깊이·학습률을 무분별하게 탐색하지 않고 사전 정의한 2개 이하로
제한한다. 예를 들면 얕은 tree 기본안과 더 강한 규제안이다. 구체 설정은 실행 전에 문서로
봉인한다.

### 후순위: Explainable Boosting Machine

EBM/GAM 계열은 Feature별 비선형 shape와 소수의 사전 지정 pair interaction을 보여주기 쉬워
포트폴리오 해석에 유리하다. 그러나 새 패키지와 별도 interaction 제한 계약이 필요하다.
Gradient Boosting이 같은 117개에서 반복 가능한 개선을 보인 뒤, 해석 가능한 대안이 실제로
필요할 때만 검토한다. 첫 후속 모델 비교에는 포함하지 않는다.

Random Forest, SVM, neural network와 여러 boosting 구현을 동시에 나열하거나 비교하지 않는다.

## Feature engineering 우선순위

### 우선 실험 F1: Historical 상대 경주시간 bundle

| 항목 | 설계 |
|---|---|
| 경마적 의미 | 과거 경주에서 말의 기록이 같은 경주 참가마 기준으로 얼마나 빨랐는지 표현 |
| 기존 Feature와 차이 | 거리·경마장을 섞은 절대 race-time median 대신 과거 경주 내부 상대값 사용 |
| 후보 값 | 과거 `runner_time - race_median_time`, `runner_time - race_best_time`, 과거 경주 내 time percentile |
| 집계 | 최근 3회·5회 median과 valid count; 필요한 최소 묶음만 선택 |
| PIT | 각 Historical 경주 결과는 현재 `feature_as_of`보다 과거이며 같은 과거 경주의 결과만 사용하므로 가능 |
| 난이도 | 중간 |
| 추가 정보 | 경주거리와 race-wide pace를 상당 부분 제거한 상대적인 과거 수행 수준 |

현재 경주의 시간이나 현재 경주의 다른 말 결과는 절대 사용하지 않는다. Historical 경주 안에서
계산한 상대값을 그 이후 경주의 Feature로만 전달한다. 이 방식은 가장 먼저 race-time median이
제외됐던 논리적 문제를 직접 해결한다.

### 우선 실험 F2: Historical pace-shape bundle

| 항목 | 설계 |
|---|---|
| 경마적 의미 | 초반 진입 속도와 마지막 600m·200m의 가속/감속 형태를 표현 |
| 기존 Feature와 차이 | S1F/G3F/G1F 각각의 절대 median뿐 아니라 구간 사이의 관계를 표현 |
| 후보 값 | `G1F - G3F/3`, `S1F - G1F`, `(G3F-G1F)/2` 등 단위가 명확한 소수 shape 값 |
| 집계 | 과거 유효 경주의 최근 3회·5회 median과 count |
| PIT | 원천 sectional이 모두 과거 경주 결과이고 `historical.race_date < feature_as_of`이면 가능 |
| 난이도 | 중간 |
| 추가 정보 | 선행형·추입형을 직접 분류하지 않고 과거 구간 전개 형태를 연속값으로 제공 |

수식은 구현 전에 물리 단위와 중복을 다시 확인해 2~3개 이하로 봉인한다. 복잡한 pace index,
주관적 점수와 현재 경주의 sectional은 만들지 않는다.

### 후순위 F3: 경마장×거리·주로 조건 정규화

| 항목 | 설계 |
|---|---|
| 경마적 의미 | 같은 경마장·거리·주로 조건에서 기대되는 기록 대비 과거 수행 수준 |
| 기존 Feature와 차이 | 현재 sectional은 고정 길이만 공통화하며 조건별 기준수준은 제거하지 않음 |
| 후보 값 | 과거시점까지의 meet×distance 기준 median 대비 race time/sectional 편차 |
| PIT | 기준 통계도 반드시 해당 Historical event보다 앞선 데이터만 사용해야 가능 |
| 난이도 | 높음; nested PIT, 희소 조건, left-censoring 관리 필요 |
| 추가 정보 | 코스·거리·주로 조건 효과를 분리한 속도 수준 |

주로상태·함수율까지 세분하면 support가 빠르게 줄어든다. 먼저 meet×distance만 검증하고, 주로
보정은 충분한 count와 fallback 계층을 사전 정의할 수 있을 때만 확장한다.

### 후순위 F4: 환경 적성 및 수동 interaction

- 같은 주로상태·날씨의 historical start count/rate는 registry의 `DEFERRED` 후보를 승계한다.
- 현재 주로·함수율과 과거 조건 적성의 결합은 경마적으로 의미가 있지만 sparse count 위험이 크다.
- gate×등록두수, 부담중량×rating, current weight change×historical weight variability 같은 관계는
  Gradient Boosting이 같은 117개에서 먼저 표현하도록 둔다.
- tree 모델로도 안정적인 interaction 신호가 확인된 뒤 해석 가능한 소수 interaction만 Logistic
  후보로 명시한다. Validation 세그먼트별 손실을 보고 사후 interaction을 추가하지 않는다.

## 개발기간 평가 방식

### Inner temporal CV: 모델·Feature 개발 전용

기존 Train 2023-01~2024-06 안에서만 다음 4개 expanding quarterly fold를 사용한다.

| Fold | 학습 | 평가 |
|---:|---|---|
| 1 | 2023-01~06 | 2023-07~09 |
| 2 | 2023-01~09 | 2023-10~12 |
| 3 | 2023-01~12 | 2024-01~03 |
| 4 | 2023-01~2024-03 | 2024-04~06 |

모든 전처리, 범주 사전, 결측 통계와 Feature normalization 기준은 fold training에서만 적합한다.
평가는 race-level macro Log Loss를 우선하고 macro Brier, micro 지표, calibration intercept/slope와
fold 간 방향 일관성을 함께 기록한다. 임의 종합점수는 만들지 않는다.

### 기존 Validation: 최종 개발 비교 구간

2024-07~2025-06은 inner CV 결과로 후보 정의와 설정을 모두 봉인한 뒤 한 번만 사용한다.

- 모델 family 설정 선택은 inner CV에서 끝낸다.
- Feature bundle 정의와 계산식 선택도 inner CV에서 끝낸다.
- Validation에는 최대 4개 사전 정의 후보만 전달한다.
- Validation 결과를 본 뒤 같은 후보의 Feature·하이퍼파라미터를 다시 바꾸지 않는다.
- 변경이 필요하면 새 실험 버전으로 등록하고, 추가 Validation 사용 횟수를 명시한다.

기존 Validation은 baseline v2 선택에 이미 사용됐으므로 완전히 독립된 holdout은 아니다. 앞으로의
반복 노출을 제한하는 최종 개발 비교 구간으로 관리한다.

## 모델 복잡도와 Feature 효과를 분리하는 ablation

| ID | 모델 | 입력 | 검증하려는 가설 | 우선순위 |
|---|---|---|---|---|
| B0 | 봉인 Logistic | 기존 117 | 기준선 | 필수 |
| M1 | HistGradientBoosting | 기존 117 | 같은 정보의 비선형·interaction 효과 | 우선 |
| F1 | Logistic | 117 + 상대 경주시간 bundle | 새로운 속도정보의 독립 효과 | 우선 |
| F2 | Logistic | 117 + pace-shape bundle | 새로운 pace정보의 독립 효과 | 우선 |
| C1 | 선택 모델 | 117 + inner CV 우승 Feature bundle | 모델×Feature 결합 효과 | 조건부 |

C1은 M1이 B0보다 안정적으로 개선되고 F1 또는 F2도 Logistic 기준으로 개선될 때만 실행한다.
F1+F2 전체 조합도 각 bundle이 개별로 가치를 보이지 않으면 만들지 않는다. 모든 Feature를 하나씩
제거하거나 117개 family 전체를 반복 ablation하지 않는다.

비교 원칙:

- M1-B0: 모델 복잡도 효과
- F1-B0, F2-B0: Feature 정보 효과
- C1-M1: 선택 Feature가 비선형 모델에도 추가하는 효과
- C1-선택 F: 모델과 Feature의 결합 효과

개선 여부는 평균 하나만 보지 않고 4개 inner fold 중 방향, macro Log Loss·Brier 동시성,
calibration과 수렴·실행 안정성을 함께 제시한다. 작은 차이는 동률로 해석하고 단순 후보를 남긴다.

## 공통 temporal evaluation 보존 정책

2025-07-01~2026-07-26은 다음 후보가 모두 고정될 때까지 열지 않는다.

1. 봉인된 Logistic baseline v2
2. 같은 117개로 선택된 비선형 모델 후보
3. 필요하면 선택된 Feature bundle 기반 최종 후보

후보별 Feature hash, Snapshot version, 전처리, 모델 설정과 calibration을 봉인한 뒤 동일 기간에서
한 번에 평가한다. 결과를 보고 같은 버전의 모델을 다시 수정하지 않는다. 기존 정보 노출 때문에
`unseen Final Test`가 아니라 **공통 post-selection temporal evaluation**으로 표현한다.

## 실행 우선순위

### 필수

1. 평가기간 접근을 차단한 개발 전용 loader와 4-fold inner temporal CV harness 구현
2. 실험 registry: 후보 ID, Feature hash, 설정, fold, 지표, Validation 접근 횟수 기록
3. baseline v2 contract와 refit artifact read-only hash 보호

### 우선 실험

1. M1: 동일 117개 `HistGradientBoostingClassifier`
2. F1: Historical 상대 경주시간 bundle + Logistic
3. F2: Historical pace-shape bundle + Logistic
4. 조건을 만족할 때만 C1 결합 후보

### 후순위

- meet×distance 및 주로 보정 speed figure
- 환경 적성 Feature
- EBM 또는 해석용 수동 interaction
- 개별 Feature 단위 ablation

## 다음 Codex 작업의 정확한 범위

다음 작업은 **모델을 아직 비교하지 않고 개발 평가 기반만 구현**하는 것이 안전하다.

- 2023-01~2024-06만 읽는 development loader
- 위 4개 quarterly expanding fold 생성기
- fold별 Train-only preprocessing 보장 검사
- macro/micro Log Loss·Brier와 calibration 진단 함수 재사용
- 실험 후보와 Feature hash를 기록하는 run registry
- 2024-07 이후 SQL 접근을 거부하는 테스트
- 기존 baseline v2와 baseline_v1 산출물 hash 보호 테스트

이 단계에서는 M1 학습, 새 Feature 계산, 기존 Validation 재평가와 2025-07 이후 접근을 수행하지 않는다.
기반 구현이 통과한 다음 별도 작업에서 M1을 첫 실험으로 실행한다.

## 근거와 한계

- 근거: `official-place-logistic-baseline-v2-validation.md`,
  `official-place-baseline-v2-model-input-design.md`, `speed-sectional-feature-audit-v2.md`,
  `place-feature-registry-v2.csv`
- Validation 세그먼트 성능은 조건별 인과효과가 아니며 support가 다른 기술통계다.
- 현재 Feature와 target은 말 행 단위지만 주 지표는 경주 단위 macro다.
- 여러 후속 후보가 같은 Validation을 보면 개발 과적합 위험이 누적되므로 후보 예산과 접근 횟수를
  반드시 기록한다.
- 이번 설계에서는 새 모델 학습, prediction, Feature 구현, Snapshot 변경과 평가기간 조회를 하지 않았다.
