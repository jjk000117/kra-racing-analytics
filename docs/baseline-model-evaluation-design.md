# 6D 연승 기준모델 및 평가 설계

결정일: 2026-08-09  
상태: 설계 확정·구현, Validation 선택 및 Train+Validation 재적합 완료, Final Test 미실행

## 1. 목적과 범위

첫 기준모델은 말 단위 PLC 적중확률을 예측하는 재현 가능한 최소 파이프라인이다. 이 단계에서는
Feature Snapshot 29개 중 관리·감사용 `horse_prior_plc_hit_count`를 제외한 28개만 모델에 입력한다.
모델 학습, 전처리기 적합, Calibration 적합과 Final Test 평가는 다음 구현 단계로 미룬다.

타깃은 `place_hit`이며 모델 입력에 포함하지 않는다. 현재 경주의 결과·배당·매출과 관리·lineage
컬럼도 입력에서 제외한다.

## 2. 날짜 분할과 역할

| 구간 | 날짜 | 역할 | 금지사항 |
|---|---|---|---|
| Warm-up | 2024-01-05~2024-09-30 | 후속 행의 PIT 이력 Feature 계산 | 학습·선택·Calibration·평가 표본 사용 금지 |
| Train | 2024-10-01~2025-09-30 | 전처리 통계, 모델 계수와 Calibration 함수 적합 | Validation·Final Test 정보를 이용한 적합 금지 |
| Validation | 2025-10-01~2025-12-31 | 원본/보정 확률 비교와 최종 절차 선택 | 전처리·모델·Calibration 재적합 금지 |
| Final Test | 2026-01-01~2026-07-26 | 모든 선택 후 단 한 번의 최종 일반화 평가 | 결과를 이용한 선택·재적합 금지 |

동일 경주의 모든 말은 반드시 같은 구간에 둔다. Warm-up 경주의 과거 이벤트가 Train 이후
Snapshot의 이력값에 반영되는 것은 허용되지만 Warm-up Snapshot 행은 학습 행이 아니다.

## 3. 입력 계약

Snapshot Feature는 기존 29개를 유지한다. 첫 기준모델 입력은 아래 28개다.

- 범주형 3개: `meet_code`, `race_grade`, `horse_sex`
- 현재 경주 수치형 6개: `distance_m`, `registered_runner_count`, `gate_no`, `horse_age`,
  `carried_weight`, `rating`
- 말 전체 이력 7개: `horse_prior_start_count`, `horse_prior_finish_count`,
  `horse_prior_finish_rate`, `horse_prior_plc_hit_rate`, `horse_prior_avg_finish_rank`,
  `horse_days_since_last_start`, `horse_history_available`
- 말 최근 5회 4개: `horse_recent5_start_count`, `horse_recent5_finish_rate`,
  `horse_recent5_plc_hit_rate`, `horse_recent5_avg_finish_rank`
- 말 동일거리 2개: `horse_same_distance_start_count`, `horse_same_distance_plc_hit_rate`
- 기수 이력 3개: `jockey_prior_start_count`, `jockey_prior_plc_hit_rate`,
  `jockey_history_available`
- 조교사 이력 3개: `trainer_prior_start_count`, `trainer_prior_plc_hit_rate`,
  `trainer_history_available`

`horse_prior_plc_hit_count`는 Snapshot과 감사 결과에 보존하되 모델 입력에서는 제외한다.
`horse_prior_start_count`와 `horse_prior_plc_hit_rate`는 각각 이력 깊이와 출전 대비 적중 빈도를
표현하므로 유지한다.

## 4. 전처리 계약

전처리기는 모델과 하나의 Pipeline으로 묶는다. 모든 학습 가능한 통계와 범주 사전은 Train에서만
구한다.

### 범주형

- Train에서만 최빈값 대체 규칙과 One-Hot 범주를 학습한다.
- Validation·Final Test의 미관측 범주는 오류나 재적합 없이 all-zero로 처리한다.
- 원천에서 이미 `UNKNOWN`인 값은 하나의 정상 범주로 유지한다.

### 수치형

- count의 계약상 0은 관측 이력 0회를 뜻하므로 결측값으로 바꾸지 않는다.
- rate·평균·경과일과 기본정보의 NULL은 각 수치 컬럼의 Train 중앙값으로 대체한다.
- 중앙값 대체 뒤 Train 평균·표준편차로 표준화한다.
- Boolean history flag는 0/1로 변환하고 별도 결측 대체 없이 유지한다.
- 결측의 의미는 기존 `*_history_available` 플래그로 표현한다. 첫 기준모델에는 추가 결측 플래그를
  만들지 않는다.

Train 내부 시간순 OOF 예측을 만들 때도 각 fold의 전처리기는 해당 fold의 과거 학습 부분에서만
새로 적합한다. 전체 Train 통계를 미리 OOF fold에 적용하지 않는다.

## 5. 비교 모델

### 무정보 기준선

Train의 PLC 양성률 하나를 계산해 모든 행에 동일한 확률로 부여한다. Validation과 Final Test의
양성률은 이 확률 계산에 사용하지 않는다. 이 기준선은 Feature가 없는 확률예측보다 모델이 실제로
개선되는지를 확인한다.

### Logistic Regression 기준모델

- 이진 Logistic Regression
- L2 정규화, `C=1.0`
- `class_weight=None`: 학습 모집단의 실제 확률 수준을 인위적으로 바꾸지 않는다.
- `solver=lbfgs`, 충분한 반복 한도로 수렴 여부를 확인한다.
- 임계값 분류가 아니라 `predict_proba`의 PLC 확률을 평가한다.
- 28개 입력과 고정 설정을 사용하며 첫 실행에서 하이퍼파라미터 탐색은 하지 않는다.

## 6. Calibration 절차

복잡도를 제한하기 위해 sigmoid/Platt Calibration 하나만 후보로 둔다.

1. 적합 범위를 날짜순으로 정렬하고 최초 3개월을 초기 학습창으로 둔다.
2. 모든 후속 fold는 현재까지의 과거 전체로 학습하고 바로 다음 3개월을 OOF 예측한다.
3. 예측한 3개월을 학습창에 편입한 뒤 다음 3개월을 같은 방식으로 예측한다.
4. 각 fold의 전처리기와 Logistic Regression은 해당 fold의 과거 학습창만으로 새로 적합한다.
5. 모든 3개월 holdout 예측을 합친 OOF 확률에 sigmoid calibrator를 적합한다.
6. 기준모델은 전체 적합 범위로 다시 적합하고, 그 확률에 OOF calibrator를 적용한다.

Train 단계에서는 이 원칙이 2024-10~12 학습→2025-01~03 예측에서 시작해 2025-07~09 예측까지
이어진다. 특정 날짜 목록은 현재 분할에서 이 원칙을 구현한 결과일 뿐이며 고정 계약은
**과거 전체로 학습하고 이후 3개월을 예측하는 expanding-window 규칙**이다.

Validation에서 보정 확률이 주 평가 지표를 개선하지 않으면 Calibration을 적용하지 않은 원본
Logistic 확률을 최종 절차로 선택한다. Isotonic, 복수 fold 체계와 다른 Calibration 방법은 첫
기준모델 범위에 넣지 않는다.

## 7. 평가 지표와 선택 규칙

### 주 지표

1. 경주별 Log Loss를 계산한 뒤 경주 간 동일 가중 평균한 macro Log Loss
2. 경주별 Brier Score를 계산한 뒤 경주 간 동일 가중 평균한 macro Brier Score

출전두수가 많은 경주가 평가를 과도하게 지배하지 않도록 macro 결과를 주 지표로 사용한다.
전체 말 행을 동일 가중한 micro Log Loss와 micro Brier Score도 함께 보고한다.

모델 선택은 Validation macro Log Loss를 우선하고 macro Brier Score를 보조 기준으로 사용한다.
아주 작은 차이에 임의의 실용적 우월성을 부여하지 않고 수치와 표본 수를 그대로 보고한다.

### Calibration 진단

- 10개 동일 표본 수 구간의 calibration table/curve
- 예측확률 평균과 실제 적중률
- calibration intercept와 slope
- 확률 계산 시 수치 안정성을 위해 평가 사본만 `[1e-6, 1-1e-6]`로 제한

intercept와 slope는 `logit(P(place_hit=1)) = intercept + slope × logit(예측확률)`의 무정규화
Logistic Regression 계수로 고정한다. 모든 예측확률이 같은 무정보 기준선은 두 계수를 동시에
식별할 수 없으므로 intercept는 Validation 관측 양성률의 logit, slope는 NULL로 기록한다.

Calibration 지표는 확률 왜곡을 확인하는 가드레일이며 임의 종합점수로 합치지 않는다.

### 보조 진단

- 경마장, 등급, 등록두수 구간, 월, 말 이력 가용 여부별 표본 수·양성률·Log Loss·Brier Score
- 수렴 여부, 예측확률 최소·최대, NULL/무한대 확률 여부
- 무정보 기준선 대비 Logistic 원본과 선택된 최종 확률의 개선 여부

Accuracy, 고정 임계값 Precision/Recall, ROI와 확정배당은 첫 모델 선택 기준에서 제외한다.

## 8. 선택과 봉인 절차

1. Train만 이용해 무정보 기준선, Logistic OOF 예측과 Calibration을 만든다.
2. Validation에서 `무정보`, `Logistic 원본`, `Logistic+sigmoid`를 비교한다.
3. macro Log Loss 우선, macro Brier와 Calibration 진단을 보조로 최종 절차를 하나 선택한다.
4. 선택 내용과 전처리·모델 설정을 고정한다.
5. Final Test를 보지 않은 상태에서 고정된 절차를 Train+Validation으로 재적합한다.
6. Logistic Regression은 동일한 28개 입력, 전처리 규칙과 하이퍼파라미터를 사용한다.
7. sigmoid가 선택됐다면 기존 calibrator를 재사용하지 않고 Train+Validation에서 동일한
   expanding-window 3개월 OOF 예측을 다시 만들어 calibrator를 재적합한다.
8. 모든 재적합이 끝난 뒤 Final Test를 단 한 번 평가한다.

## 9. Final Test 직전 최종 적합 정책

선택안 2를 확정한다. Validation에서 최종 절차를 선택하고 모든 설정을 봉인한 뒤 Final Test를
보기 전에 Train+Validation 전체로 동일한 절차를 재적합한다.

- 전처리 통계와 범주 사전은 Train+Validation에서 새로 적합한다.
- Logistic Regression의 28개 입력과 하이퍼파라미터는 Validation 선택 후 변경하지 않는다.
- sigmoid가 선택된 경우 Train에서 만든 calibrator는 폐기하고, Train+Validation 범위 안에서
  `과거 전체 학습 → 이후 3개월 OOF 예측`을 반복해 새 calibrator를 적합한다.
- Final Test의 행·타깃·분포·지표는 이 과정의 어떠한 선택이나 적합에도 사용하지 않는다.

Train+Validation 재적합은 Validation을 더 이상 독립 평가셋으로 주장하지 않는 대신 Final Test 전
사용 가능한 과거 데이터를 모두 활용한다. 모델 선택의 근거는 재적합 전 Validation 결과로 보존하고,
최종 일반화 성능은 봉인된 Final Test 결과로만 보고한다.

## 10. 설계 확정 당시 실행 금지 범위

설계만 확정한 당시 단계에서는 다음을 수행하지 않았다.

- 모델 학습 또는 하이퍼파라미터 탐색
- 전처리기나 결측 대체 통계 적합
- Calibration 적합
- Validation·Final Test 예측 및 평가
- Snapshot 재생성 또는 기존 PIT·분할 결과 재검증

구현과 Validation 실행 결과는 `docs/baseline-validation-result.md`에 기록한다. Validation에서
`logistic_raw`가 선택됐으며 sigmoid는 최종 절차에서 제외됐다.
