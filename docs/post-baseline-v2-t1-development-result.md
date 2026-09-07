# Post-baseline v2 T1 development 실험 결과

## 결론

사전 계약에 따라 `KEEP_T1`으로 판정한다. 동일한 raw Logistic 절차에서 T1 4개를 추가한
LT1은 L133보다 Macro Log Loss와 Macro Brier 평균을 모두 낮췄고, 두 지표의 동시 개선이
4개 temporal fold 중 3개에서 반복됐다. 다만 상대 개선폭은 각각 0.129%, 0.148%로 작으므로
강한 성능 향상이 아니라 **작지만 반복된 trend 정보의 추가 가치**로 해석한다.

현재 프로젝트 대표 후보 `L133+sigmoid`와 별개로, 이 실험은 기존 Feature-bundle development
정책에 맞춰 raw Logistic끼리 비교했다. sigmoid 선택이나 Validation 재접근은 수행하지 않았다.

## 실행 계약

- 기간: `2023-01-01 <= race_date < 2024-07-01`
- 표본: 28,392행, 2,675경주
- 비교: L133 133개 대 LT1 137개
- L133 hash: `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`
- 모델: 기존 L2 Logistic (`C=1`, `lbfgs`, `max_iter=2000`, seed `20260817`)
- 평가: 기존 4개 quarterly expanding temporal fold, raw probability
- 전처리: 각 fold Train에서만 median imputation과 StandardScaler 적합

| Fold | Train 행/경주 | Evaluation 행/경주 | Evaluation 기간 |
|---|---:|---:|---|
| 1 | 9,224 / 854 | 4,458 / 427 | 2023-07-01~2023-09-24 |
| 2 | 13,682 / 1,281 | 5,229 / 494 | 2023-10-06~2023-12-31 |
| 3 | 18,911 / 1,775 | 4,707 / 432 | 2024-01-05~2024-03-31 |
| 4 | 23,618 / 2,207 | 4,774 / 468 | 2024-04-05~2024-06-30 |

모든 fold에서 `max(train_date) < min(evaluation_date)`를 만족했다.

## 주 지표

| 후보 | Macro Log Loss 평균 ± SD | Macro Brier 평균 ± SD | Micro Log Loss | Micro Brier |
|---|---:|---:|---:|---:|
| L133 | 0.527685 ± 0.006912 | 0.175744 ± 0.002715 | 0.525488 | 0.174752 |
| LT1 | 0.527003 ± 0.006682 | 0.175484 ± 0.002621 | 0.524884 | 0.174525 |

| Fold | Δ Macro Log Loss | Δ Macro Brier | 두 지표 동시 개선 |
|---|---:|---:|---|
| 1 | -0.000138 | -0.000092 | 예 |
| 2 | -0.001220 | -0.000456 | 예 |
| 3 | +0.000051 | +0.000014 | 아니오 |
| 4 | -0.001423 | -0.000505 | 예 |

평균 delta는 Macro Log Loss `-0.000682`(-0.129%), Macro Brier `-0.000260`(-0.148%)다.
두 지표의 개선 fold 수와 동시 개선 fold 수는 모두 3/4다. Fold 3의 악화는 매우 작지만,
완전한 일관성은 아니므로 후속 단계에서 효과 크기를 과대해석하지 않는다.

## Calibration과 실행 상태

| 후보 | Calibration intercept 평균 | Calibration slope 평균 | 평균 적합 시간 |
|---|---:|---:|---:|
| L133 | -0.07399 | 0.93042 | 1.758초 |
| LT1 | -0.07828 | 0.92917 | 1.767초 |

Calibration은 소폭 악화됐지만 현저한 붕괴는 관찰되지 않았다. 각 적합에서 발생한 유일한
경고는 sklearn 1.8의 `penalty` deprecation 안내였으며 수렴 경고나 실행 실패는 없었다.

## T1 전처리와 계수 안정성

- Fold evaluation non-null 비율은 네 Feature 모두 79.27%, 77.55%, 82.69%, 89.78%였다.
- 모든 Feature와 fold에서 실제 imputation 값은 fold Train median과 `1e-12` 이내로 일치했다.
- 결측을 0으로 대체하거나 missing indicator를 추가하지 않았다.

| Feature | 표준화 계수 평균 | 범위 | 양/음 fold |
|---|---:|---:|---:|
| race-time percentile trend | +0.14968 | +0.14200~+0.16205 | 4 / 0 |
| S1F improvement trend | +0.00262 | -0.01737~+0.01480 | 2 / 2 |
| G3F improvement trend | +0.04460 | -0.00448~+0.11814 | 3 / 1 |
| G1F improvement trend | -0.04260 | -0.12149~+0.00668 | 1 / 3 |

Race-time percentile trend는 네 fold에서 방향과 크기가 가장 안정적이었다. 나머지 세 계수는
방향 또는 크기 변동이 커 개별 Feature 선택의 근거로 쓰지 않으며, 봉인된 T1 bundle 전체만
판정한다.

## 재현성과 보호 감사

- L133 재실행 Macro Log Loss/Brier는 기존 저장값과 각각 정확히 일치했다(delta 0).
- L133 133개 이름·순서·hash와 LT1의 137개 고유 Feature를 확인했다.
- 기존 T1 설계/구현, L133/F1/F3/M1/H133/RA1, baseline run/refit 및 Validation ledger hash는
  실행 전후 동일했다.
- Validation ledger는 model-selection 1회, descriptive re-access 1회 그대로다.
- 쿼리 guard와 실제 최대 날짜 모두 `2024-07-01` 미만이며 Validation 및 이후 데이터 접근은 0건이다.

재현 가능한 상세 산출물은
`data/exports/modeling/post_baseline_v2_t1_development_v1/`의 JSON/CSV에 저장했다.

## 판정 이후 범위

`KEEP_T1`은 development 기간에서 trend bundle의 작은 추가 가치가 반복됐다는 뜻이다.
LT1을 official 모델로 승격하거나 기존 `L133+sigmoid`를 변경한다는 뜻은 아니다. 이번 결과를
보고 T1 정의, window 또는 개별 Feature를 소급 수정하지 않는다.

