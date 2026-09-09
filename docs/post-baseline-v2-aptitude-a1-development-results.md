# Post-baseline v2 Aptitude A1 Development 결과

## 결론

동일 Logistic·동일 4개 expanding temporal fold에서 `LT1(137)`과 `LA1(144)`만 비교했다.
A1은 평균 Macro Log Loss와 Macro Brier를 모두 매우 작게 악화했고 두 지표 동시 개선은
2/4 fold에 그쳐 사전 규칙에 따라 **`DROP_A1`**으로 판정한다.

이 결과는 봉인된 A1 bundle 전체에 대한 판정이다. 결과를 보고 최소 count, 개별 Feature,
전처리 또는 Logistic 설정을 변경하지 않았으며 Validation과 2024-07 이후 데이터에는 접근하지
않았다.

## 계약과 재현

- Development: `2023-01-01 <= race_date < 2024-07-01`
- 모집단: 28,392행·2,675경주
- LT1: 137개, hash `1dcf5f5a630d67f216fa6dc27932d2c6532ec0a50af6360b7521917682f802e8`
- LA1: 144개, hash `99a7847fd97d7f0f41e10b181db3e67a1243f5a0d8397ae18a0811ac57c4fbb3`
- A1: 7개, hash `9f15c6caa05da889780ac29de73ec11441e470fba759925c00af936c3c5773d2`
- Logistic: L2, C=1.0, lbfgs, max_iter=2000, class_weight=None, 기존 random state
- 확률: raw Logistic; calibration은 평가하지 않음
- LT1 기존 여섯 지표 재현 오차: 모두 0, tolerance `1e-12`

| Fold | Train 행/경주 | Eval 행/경주 | Train 종료 | Eval 시작 |
|---|---:|---:|---|---|
| fold_1 | 9,224 / 854 | 4,458 / 427 | 2023-06-30 | 2023-07-01 |
| fold_2 | 13,682 / 1,281 | 5,229 / 494 | 2023-09-24 | 2023-10-06 |
| fold_3 | 18,911 / 1,775 | 4,707 / 432 | 2023-12-31 | 2024-01-05 |
| fold_4 | 23,618 / 2,207 | 4,774 / 468 | 2024-03-31 | 2024-04-05 |

모든 fold는 `max(train_date) < min(eval_date)`이고 train/eval 경주 중복은 0이다.

## Primary 결과

| Fold | LT1 Macro LL | LA1 Macro LL | Delta | LT1 Macro Brier | LA1 Macro Brier | Delta |
|---|---:|---:|---:|---:|---:|---:|
| fold_1 | 0.534392 | 0.535329 | +0.000937 | 0.177540 | 0.177971 | +0.000431 |
| fold_2 | 0.524648 | 0.523516 | -0.001132 | 0.173545 | 0.173020 | -0.000525 |
| fold_3 | 0.517213 | 0.517870 | +0.000657 | 0.172304 | 0.172543 | +0.000238 |
| fold_4 | 0.531758 | 0.531346 | -0.000412 | 0.178548 | 0.178453 | -0.000095 |
| **평균** | **0.527003** | **0.527015** | **+0.000012** | **0.175484** | **0.175497** | **+0.000012** |

- Macro Log Loss 개선: 2/4 fold
- Macro Brier 개선: 2/4 fold
- 두 지표 동시 개선: 2/4 fold
- 평균 상대 변화: Macro LL +0.00235%, Macro Brier +0.00697%

평균 악화 폭은 실질적으로 매우 작지만 방향이 개선이 아니며 fold 반복성도 사전 KEEP 조건을
충족하지 못한다.

## Secondary 결과

| 지표 | LT1 평균 | LA1 평균 | LA1-LT1 |
|---|---:|---:|---:|
| Micro Log Loss | 0.524884 | 0.524780 | -0.000105 |
| Micro Brier | 0.174525 | 0.174510 | -0.000016 |
| Calibration intercept | -0.078281 | -0.081334 | -0.003052 |
| Calibration slope | 0.929170 | 0.921906 | -0.007264 |

Micro 지표는 아주 작게 개선됐지만 primary race-macro 손실 실패를 뒤집지 않는다. LA1의 평균
calibration slope는 1에서 조금 더 멀어졌으며 현저한 붕괴는 아니다.

모든 fit에서 수렴 실패는 없었다. 기록된 경고는 sklearn 1.8의 명시적 `penalty='l2'`
deprecated 경고뿐이며, 비교 계약을 유지하기 위해 설정을 변경하지 않았다.

## A1 가용성·전처리

- count 3개: 실제 0을 유지하고 fold Train에서 constant 0 imputation 후 scaling
- rate/median 3개와 거리변화: 각 fold Train median imputation 후 scaling
- fitted imputation 값은 독립 계산한 fold Train median과 전부 `1e-12` 이내 일치
- Eval 또는 전체 Development 통계 사용: 0건

동일 주로상태 rate의 Eval 가용률은 fold별 27.48%, 42.26%, 35.82%, 48.41%로 변했지만,
성능 방향은 단순히 가용률 증가와 일관되게 연결되지 않았다. 낮은 가용성 subgroup을 이용한
사후 최적화는 수행하지 않았다.

## Standardized coefficient

| Feature | 평균 | 범위 | 부호 일관성 |
|---|---:|---:|---|
| same-grade count | +0.047 | +0.020~+0.074 | 양 4/4 |
| same-grade PLC rate | +0.004 | -0.004~+0.015 | 양 2 / 음 2 |
| same-track-condition count | +0.003 | -0.023~+0.042 | 양 2 / 음 2 |
| same-track-condition PLC rate | -0.009 | -0.016~-0.003 | 음 4/4 |
| same-distance F1 count | -0.186 | -0.268~-0.051 | 음 4/4 |
| same-distance F1 median | +0.039 | +0.024~+0.050 | 양 4/4 |
| distance change | -0.132 | -0.147~-0.117 | 음 4/4 |

일부 Feature의 방향은 반복되지만 bundle 전체가 out-of-time primary loss를 개선하지 않았으므로
계수만으로 A1 일부를 선택하지 않는다.

## 사실·가설·남은 질문

확인된 사실:

- A1은 LT1 통제 후 race-macro probability loss를 평균적으로 개선하지 않았다.
- fold 2·4에서는 개선, fold 1·3에서는 악화해 시간 반복성이 부족했다.
- Micro 손실은 아주 작게 개선됐지만 경주 단위 평균 손실과 방향이 달랐다.

기각된 가설:

- 봉인된 7개 aptitude 표현을 하나의 bundle로 더하면 LT1보다 안정적인 추가 out-of-time PLC
  probability information을 제공한다는 가설은 이번 development 계약에서 지지되지 않았다.

아직 알 수 없는 것:

- 개별 A1 Feature의 독립 가치, shrinkage·bucket·interaction의 효과는 이번 실험 범위 밖이다.
- Validation이나 더 긴 기간에서의 결과는 확인하지 않았다.
- 이는 aptitude 개념 전체의 부재가 아니라 **현재 봉인 정의의 bundle 추가가치 부재**를 뜻한다.

## 보호와 다음 단계

공용 DB, L133/T1/A1 계약, Validation contract/ledger/result, H133/RA1 결과의 실행 전후
SHA256은 모두 동일했다. PLC 라인에서 A1은 종료하며 Validation으로 승격하지 않는다.
