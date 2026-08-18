# Post-baseline v2 improvement one-time Validation 계약

## 상태와 후보

상태는 `SEALED_BEFORE_ONE_TIME_VALIDATION`이다. Development 탐색은 종료했으며 one-time
Validation 후보는 다음 하나로 고정한다.

- Logistic Regression
- 기존 official baseline v2 117개
- F1 6개
- F3 10개
- 총 133개
- Feature hash:
  `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`

Feature 순서·이름·F1/F3 계산식·PIT·결측 규칙은
`docs/post-baseline-v2-improvement-validation-contract.json`에 전체 저장했다. Registry와 구현 순서가
일치하지 않거나 hash가 달라지면 계약 생성 및 향후 Validation 실행은 실패해야 한다.

## 전처리와 Logistic

- 범주형: Train 최빈값 대체 후 `OneHotEncoder(handle_unknown="ignore")`
- 일반 수치형: Train median 대체 후 `StandardScaler`
- 기존 Historical count와 신규 F1 count: NULL을 관측 0건으로 해석해 0 대체 후 scaling
- 신규 F1/F3 연속형: Train median 대체 후 scaling
- missing indicator 추가 없음
- Validation 통계로 imputation, scaling, category vocabulary를 적합하지 않음

Logistic은 L2, `C=1.0`, `solver="lbfgs"`, `max_iter=2000`, `class_weight=None`,
`random_state=20260817`로 고정한다. sklearn `penalty` deprecation warning은 수렴 실패와 구분해
기록한다. `ConvergenceWarning`은 허용하지 않고 실행 실패로 처리한다.

## Calibration

Validation에 전달할 improvement probability는 두 개뿐이다.

1. F1+F3 raw Logistic
2. F1+F3 Train temporal OOF sigmoid

OOF는 최초 3개월로 학습한 뒤 다음 3개월을 예측하고, 학습기간을 3개월씩 expanding한다. 각 fold는
`max(training date) < min(prediction date)`를 만족하고 전처리도 fold train에서만 적합한다.
Calibrator는 Train 기간의 OOF raw probability만 사용한다.

Sigmoid가 raw보다 Validation Macro Log Loss와 Macro Brier를 모두 낮출 때만 sigmoid를 선택한다.
하나라도 개선하지 못하면 raw를 선택한다. Calibration intercept/slope는 보조 진단이며 다른
calibration 방법은 허용하지 않는다.

## One-time Validation 비교와 승격 규칙

Validation 기간은 2024-07-01 이상 2025-07-01 미만이다. 비교 대상은 다음뿐이다.

- B0: 봉인된 `official_place_logistic_baseline_v2` raw Logistic
- 개선 후보: 위 규칙으로 선택된 F1+F3 raw 또는 sigmoid

판정은 후보-B0의 Macro Log Loss와 Macro Brier를 주 지표로 한다.

- **PROMOTE**: 두 전체 Macro 지표를 모두 개선하고 각 지표가 관측 Validation 월의 절반 이상에서
  개선
- **CONDITIONAL**: 전체 Macro 지표 중 하나만 개선하거나, 둘 다 개선하지만 월별 반복성이 위 기준에
  미달
- **REJECT**: 전체 Macro 지표가 모두 개선되지 않거나 명확한 일반화 악화

Micro 지표, calibration, 월별 및 경마장·등록두수·등급·거리 진단은 보조 자료다. 작은 수치상 우위는
작은 효과로 명시하며 과장하지 않는다. 접근 후 판정 규칙을 변경하지 않는다.

## 접근 예산과 이후 정책

- 현재 Validation 접근: 0회
- 예약된 접근: F1+F3 후보 1회
- 이번 단계에서 access count 증가: 없음
- 후보 변경 후 동일 Validation 재접근: 금지
- 2025-07 이후 공통 temporal evaluation: 아직 금지

Validation 후 선택된 Feature·전처리·Logistic·calibration을 봉인한 뒤에만 Train+Validation으로
재적합한다. 새로운 Feature 작업은 별도 버전으로 분리한다.

## 보호 감사와 blocker

기존 baseline run contract/refit artifact, 기존 117개 hash, Feature registry·구현, M1 결과,
독립 bundle development 결과와 F1+F3 development 결과의 SHA256을 machine-readable 계약에
기록했다. 생성 전 검증에서 모두 기대 상태와 일치했다.

Validation 데이터·target·prediction을 읽지 않았고 모델 적합도 수행하지 않았다. 실행 전 남은
blocker는 없다. 다음 단계에서는 JSON 계약을 먼저 재검증하고, access count를 1로 기록하는 동일
트랜잭션성 절차 안에서 one-time Validation을 실행해야 한다.
