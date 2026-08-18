# Post-baseline v2 race-aware learning experiment design

기준일: 2026-08-19  
상태: `SEALED_BEFORE_DEVELOPMENT_EXECUTION`

## 결론

다음 race-aware development 실험은 **RA1 linear pairwise Logistic ranker** 하나만 실행한다.
기존 133개 입력과 선형 모델 복잡도를 유지하면서, 말별 독립 binary likelihood 대신 같은 경주의
PLC 적중마가 비적중마보다 높은 score를 갖도록 경주별 pairwise loss를 학습한다. 이 선택은
Feature 효과와 비선형 모델 효과를 배제하고 `race_id`를 이용한 경쟁집합 학습 효과를 가장 직접적으로
검증한다.

Ranking score는 PLC 확률이 아니다. Probability 평가는 outer-fold Train 내부의 시간순 OOF
runner score로 고정 sigmoid calibrator를 적합한 뒤에만 수행한다. Raw score는 경주 내 순위 지표에만
사용하며 sigmoid는 단조변환이므로 순위를 바꾸지 않는다.

## PLC는 경주당 여러 양성이 있는 경쟁집합이다

`place_hit`은 착순 `ord`에서 추정하지 않고 공식 `canonical.winning_payout`의 PLC 적중마 집합과
출전마를 결합한 binary target이다. 모델링 모집단은 완료되고 공식 PLC 결과가 존재하며 출전마
복원이 가능한 경주다.

- DNS는 실제 출전하지 않았으므로 말 단위 모집단에서 제외한다.
- 경주 취소·결과 미확정 경주는 학습 경주에서 제외한다.
- 주행중지와 실격은 실제 출전했으므로 모집단에 남고, 공식 적중마가 아니면 `place_hit=0`이다.
- 같은 경주의 현재 결과·배당·기록은 Feature에 포함하지 않는다.

Development `2023-01-01 <= race_date < 2024-07-01`은 2,675경주·28,392행이다.

| 경주별 실제 출전행 | PLC 양성 수 | 경주 수 |
|---:|---:|---:|
| 7 | 2 | 7 |
| 7 | 3 | 10 |
| 8~16 | 3 | 2,651 |
| 8~12 | 4 | 7 |

따라서 거의 모든 경주에 양성 3두가 있지만 2두와 4두도 존재한다. RA1은 양성끼리 순서를
강제하지 않고 같은 relevance로 취급하며, 모든 양성-음성 조합만 비교한다.

현재 L133은 각 말의 `P(place_hit=1 | x)`를 runner-level Bernoulli likelihood로 학습한다.
F3가 상대 Feature를 제공하더라도 loss 자체는 같은 경주의 확률 순서와 양성 수를 직접 제약하지
않는다. 또한 한 경주의 출전마 오차가 상관되어도 각 행을 독립 관측처럼 합산한다. RA1은 이 한계를
경주 안의 positive-negative 비교로 직접 다룬다.

## 검토한 formulation

### A. Grouped pairwise ranking — 최종 권고

한 경주의 모든 PLC 양성 `p`와 모든 음성 `n`에 대해 `x_p - x_n`을 만들고 양성이 더 높은
score를 갖도록 선형 Logistic pairwise loss를 학습한다. 역방향 `x_n - x_p`도 함께 넣어 label
0/1을 대칭으로 구성한다.

장점:

- multi-positive를 자연스럽게 처리하며 양성 내부의 임의 순서를 만들지 않는다.
- `race_id`가 Feature가 아니라 pair 생성용 group key로만 사용된다.
- sklearn과 현재 전처리를 재사용할 수 있어 새 라이브러리가 필요 없다.
- 선형 score를 사용하므로 L133 대비 차이가 주로 학습 목적함수에 남는다.
- 시간순 CV와 새 경주 평가가 단순하다.

한계:

- pairwise score는 PLC marginal probability가 아니다.
- 한 경주의 양성 수를 직접 생성하는 joint probability model은 아니다.
- 경주당 pair 수가 다르므로 명시적인 race weight가 필요하다.

### B. Race-conditioned binary classification — 첫 실험에서 제외

Race fixed effect를 둔 conditional Logistic은 학습 경주의 공통 난이도는 제거할 수 있지만 새로운
평가 경주의 race intercept를 추정할 수 없다. 경주별 softmax와 예상 적중마 수를 결합하는 방식은
가능하지만 양성 수 2~4와 동착을 다루는 별도 확률 계약이 필요해 학습구조 효과만 분리하기 어렵다.

### C. Listwise·set formulation — 후순위

Multi-positive listwise softmax, Plackett-Luce 확장 또는 set neural network는 경주 전체를 직접
입력할 수 있다. 그러나 softmax 합 제약과 PLC marginal probability의 관계가 불명확하고 custom
loss·padding·masking이 필요하다. 현재 2,675 development 경주와 첫 race-aware 실험 목적에 비해
복잡도가 높아 후순위로 둔다.

Tree LambdaMART도 현실적인 ranking 후보지만 비선형 모델 family와 ranking objective가 동시에
변해 원인 분리가 어렵고 현재 LightGBM/XGBoost 의존성도 없다. RA1 결과 이후에만 별도 후보로
검토한다.

## RA1 입력과 학습 계약

### Feature

- 정확히 기존 133개, hash
  `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`
- Feature 추가·삭제·순서 변경 없음
- F1/F3 정의 변경, F2 재도입, interaction 생성 없음
- `race_id`는 group integrity와 pair 생성에만 사용하며 Feature에 넣지 않음

### Preprocessing

각 outer/inner fold의 Train runner 행에서만 기존 L133 ColumnTransformer를 적합한다.

- 범주형: Train 최빈값 대체 + `OneHotEncoder(handle_unknown="ignore")`
- 일반 수치형: Train median 대체 + `StandardScaler`
- Historical/F1 count: NULL을 0으로 대체한 뒤 scaling
- 평가행 통계·category vocabulary 사용 금지

Pair는 preprocessing 후 transformed row의 차이로 만든다. 한 경주의 양성 수를 `m`, 음성 수를
`n`이라 할 때 모든 `m*n` pair와 역방향을 만들고, directed pair 하나의 sample weight를
`1 / (2*m*n)`으로 둔다. 따라서 각 학습 경주의 총 weight는 1이다. Pair sampling은 하지 않는다.
양성 또는 음성이 없는 경주는 pair 학습에서 제외하되 건수와 원인을 기록한다.

### 선형 pairwise 모델

- `sklearn.linear_model.LogisticRegression`
- `penalty="l2"`, `C=1.0`
- `solver="lbfgs"`, `max_iter=2000`
- `fit_intercept=False`
- `class_weight=None`, `random_state=20260817`
- 설정 후보 추가와 hyperparameter 탐색 없음

Intercept는 두 runner의 차이에서 상쇄되므로 사용하지 않는다. Runner score는 적합된 coefficient와
각 runner transformed vector의 내적으로 계산한다.

## Probability 계약

RA1 score를 곧바로 확률로 해석하지 않는다. 각 outer fold에서 다음 고정 절차를 사용한다.

1. outer Train 내부에서 첫 3개월 학습 후 다음 3개월 예측, 이후 3개월씩 expanding하는 inner OOF를 만든다.
2. 각 inner fold에서 preprocessing과 pairwise ranker를 inner Train에만 적합한다.
3. OOF runner score와 `place_hit`만 사용해 단일 sigmoid calibrator를 적합한다.
4. outer Train 전체에 preprocessing·ranker를 적합하고 outer evaluation score를 만든다.
5. 고정 calibrator로 PLC probability를 생성한다.

다른 calibration 후보를 비교하지 않으며 raw-vs-sigmoid 선택도 하지 않는다. Calibrator는 순위를
바꾸지 않는다. L133 기준선도 같은 outer fold와 Train 내부 expanding OOF sigmoid 절차로 다시
계산해 probability 비교 조건을 맞춘다. 이는 Validation L133을 재선택하는 작업이 아니다.

## Development temporal CV와 leakage 방지

기존 네 quarterly expanding fold를 그대로 사용한다.

| Fold | Train | Evaluation | Train 경주/행 | Evaluation 경주/행 |
|---|---|---|---:|---:|
| 1 | 2023-01~06 | 2023-07~09 | 854 / 9,224 | 427 / 4,458 |
| 2 | 2023-01~09 | 2023-10~12 | 1,281 / 13,682 | 494 / 5,229 |
| 3 | 2023-01~12 | 2024-01~03 | 1,775 / 18,911 | 432 / 4,707 |
| 4 | 2023-01~2024-03 | 2024-04~06 | 2,207 / 23,618 | 468 / 4,774 |

모든 split은 날짜 경계 전에 `race_id` 단위로 만든다. 한 경주의 모든 말은 반드시 같은 partition에
있어야 하며 Train/evaluation race 교집합은 0이어야 한다. Evaluation target은 metric 계산에만
사용하며 preprocessing, pair 생성, model, calibrator fit에 사용하지 않는다. Loader는
`race_date < 2024-07-01`을 코드와 테스트로 강제한다.

## 평가 지표

### Probability quality

고정 sigmoid probability로 다음을 L133+sigmoid와 같은 평가 함수로 비교한다.

- Macro/Micro Log Loss
- Macro/Micro Brier
- Calibration intercept/slope

Primary probability guardrail은 Macro Log Loss와 Macro Brier다. Micro와 calibration 계수는
진단이며 승격 규칙을 뒤집지 않는다.

### Within-race ranking

Primary ranking 지표:

- Macro NDCG@3: binary relevance와 multi-positive ideal DCG로 경주별 계산 후 평균
- Micro Recall@3: 모든 실제 PLC 적중마 중 score 상위 3두가 회수한 비율

반복성·해석 보조:

- Top-1 PLC hit rate
- Top-2/Top-3에 적중마가 하나 이상 있는 경주 비율
- Micro/Macro Recall@1/2/3
- 경주별 실제 PLC 적중마의 평균 predicted rank와 field-size-normalized percentile rank
- 경주별 Average Precision의 평균(MAP)

동률은 average rank를 metric 계산에 사용한다. 정확히 K두를 선택해야 하는 Top-K 집합은 score
내림차순, `horse_id` 오름차순의 결정론적 tie-break를 사용하고 tie 발생 건수를 함께 보고한다.

## 사전 판정 규칙

모든 비교는 RA1과 동일 fold에서 재현한 L133+sigmoid를 기준으로 하며 결과 확인 후 수정하지 않는다.
부동소수점 동률 허용오차는 절대 `1e-12`다.

### PROMOTE_RACE_AWARE

다음을 모두 만족한다.

1. 평균 NDCG@3와 평균 Recall@3가 모두 L133보다 개선된다.
2. 두 ranking 지표가 각각 최소 3/4 fold에서 개선된다.
3. 평균 Macro Log Loss와 Macro Brier가 모두 L133보다 악화하지 않는다.

### CONDITIONAL

다음 중 하나다.

- 두 ranking 지표가 평균 및 각각 3/4 fold에서 개선되지만, probability primary 중 하나 이상이
  악화하되 각 상대 악화가 1% 이하이다.
- 두 probability primary가 모두 악화하지 않지만 ranking primary 중 하나만 3/4 fold 반복성을
  만족한다.

CONDITIONAL은 승격이 아니며 추가 Validation 접근을 허가하지 않는다. 원인 진단 후 별도 결정을
요구한다.

### DROP_RACE_AWARE

다음 중 하나면 탈락한다.

- NDCG@3 또는 Recall@3가 평균적으로 개선되지 않는다.
- 두 ranking primary가 모두 3/4 fold 반복성을 충족하지 못한다.
- Macro Log Loss 또는 Macro Brier의 상대 악화가 1%를 초과한다.

Calibration만 개선되거나 Top-1만 개선되는 경우 승격하지 않는다. 결과를 보고 model setting,
pair weight, calibration 또는 지표를 변경하지 않는다.

## 보호 범위와 다음 구현 단계

이번 설계에서는 모델 학습·prediction·Validation 접근·2025-07 이후 접근을 수행하지 않았다.
기존 L133 PROMOTE, descriptive diagnostic, baseline run contract와 refit artifact를 변경하지 않았다.

다음 Codex 작업의 정확한 범위는 다음과 같다.

1. JSON 계약 검증기와 development-only loader guard 구현
2. race-integrity 및 pair 생성·race weight 단위 테스트
3. L133+sigmoid와 RA1+sigmoid의 동일 네 fold 실행
4. 사전 정의 probability/ranking 지표와 fold delta 저장
5. 규칙에 따른 `PROMOTE_RACE_AWARE` / `CONDITIONAL` / `DROP_RACE_AWARE` 자동 판정

Validation과 post-selection 기간은 이 결과와 무관하게 계속 닫아 둔다.
