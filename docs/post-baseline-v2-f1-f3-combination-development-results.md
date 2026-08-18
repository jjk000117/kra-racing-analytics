# Post-baseline v2 F1+F3 조합 development 결과

## 결론

사전 확정한 유일한 조합인 F1+F3는 F3 단독보다 Macro Log Loss와 Macro Brier를 4/4 fold에서
모두 개선했다. 개발단계 최종 후보는 기존 117개와 F1 6개, F3 10개를 함께 사용하는 133개 입력
Logistic으로 결정한다.

| 후보 | 입력 수 | Macro Log Loss | 표준편차 | Macro Brier | 표준편차 |
|---|---:|---:|---:|---:|---:|
| B0 | 117 | 0.535538 | 0.007286 | 0.178477 | 0.002622 |
| F1 | 123 | 0.534350 | 0.007592 | 0.177942 | 0.002698 |
| F3 | 127 | 0.528864 | 0.006478 | 0.176203 | 0.002561 |
| F1+F3 | 133 | 0.527685 | 0.006912 | 0.175744 | 0.002715 |

F1+F3의 F3 대비 평균 변화는 Macro Log Loss -0.001179, Macro Brier -0.000459다. 개선
폭은 작지만 두 주요 지표가 네 fold에서 모두 같은 방향이므로 F1은 F3와 함께 사용해도 독립적인
추가 정보를 제공하는 것으로 판정했다.

## Fold별 F3 대비 변화

후보-F3 차이이므로 음수가 개선이다.

| Fold | F1+F3 Macro LL | Δ vs F3 | F1+F3 Macro Brier | Δ vs F3 |
|---|---:|---:|---:|---:|
| 1 | 0.534530 | -0.001434 | 0.177632 | -0.000508 |
| 2 | 0.525868 | -0.000585 | 0.174000 | -0.000286 |
| 3 | 0.517162 | -0.002263 | 0.172291 | -0.000835 |
| 4 | 0.533181 | -0.000432 | 0.179052 | -0.000207 |

F1+F3는 B0 대비 평균 Macro Log Loss -0.007853, Macro Brier -0.002733을 개선했다.
Micro Log Loss와 Micro Brier도 F3 대비 모든 fold에서 개선했다.

## Calibration과 안정성

- F3 평균 calibration intercept/slope: -0.0719 / 0.9352
- F1+F3 평균 calibration intercept/slope: -0.0740 / 0.9304

Calibration은 평균 기준으로 소폭 혼재돼 있으며 조합 채택 근거로 사용하지 않았다. 조합의 Macro
손실 표준편차는 F3보다 약간 증가했지만 네 fold 모두 손실 방향이 개선됐으므로 시간 불안정성의 명확한
증거로 보지 않았다.

모든 후보는 이전과 동일하게 fold당 수렴 경고 1건을 기록했다. B0/F1/F3 지표는 직전 독립 bundle
실험과 숫자상 동일하게 재현됐다. 모델 설정이나 전처리를 변경하지 않았다.

## 계약 및 보호 감사

- development loader: 28,392행·2,675경주
- 사용 기간: 2023-01-01 이상, 2024-07-01 미만
- strict temporal ordering 위반: 0
- 전처리·모델 fit scope: fold train only
- Validation 접근 횟수: 0
- 2024-07 이후 행 로드: 0
- 봉인 baseline run contract/refit artifact: hash 유지
- M1 결과와 직전 bundle 실험 결과: hash 유지
- engineered Feature 구현 코드: hash 유지

후보 Feature hash는 다음과 같다.

- B0: `cc18ef4bf88438ccbfbe836a29aec34f5356e52976b834124a065c89e57e8d2b`
- F1: `0b0c545fb5a2135cbd4b8362e3c7bd72231f05b43dbfdfaccec64198dc3469cc`
- F3: `04b3f28789d20b216dc7f6b4789f3480a5f7d42d724444dce996b81d1e84b0bd`
- F1+F3: `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`

## 판정과 다음 단계

판정은 `KEEP_COMBINATION`, 개발단계 선택 후보는 F1+F3다. F2나 추가 조합은 탐색하지 않는다.
다음 단계에서는 먼저 F1+F3 후보의 Validation 실행 계약을 봉인하고, 기존 접근 예산에 따라
2024-07~2025-06 Validation을 한 번만 사용해 B0와 비교한다. Validation 결과를 보고 Feature 정의,
window, 전처리 또는 Logistic 설정을 소급 변경하지 않는다.

재현 산출물은
`data/exports/modeling/post_baseline_v2_f1_f3_combination_development_v1/`의 `fold_metrics.csv`,
`summary_metrics.csv`, `fold_deltas.csv`, `experiment_registry.json`, `result.json`에 저장했다.
