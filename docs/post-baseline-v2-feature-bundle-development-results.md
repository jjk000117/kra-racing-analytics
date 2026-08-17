# Post-baseline v2 Feature bundle development 결과

## 결론

동일한 Logistic, 기존 117개 입력, fold-train 전처리와 네 quarterly expanding fold를 고정한
development 실험에서 F1과 F3는 KEEP, F2는 DROP으로 판정했다. F1은 개선 폭이 작지만 Macro Log
Loss와 Macro Brier를 4/4 fold에서 모두 개선했다. F3는 네 fold에서 두 지표를 모두 더 큰 폭으로
개선했다. F2는 네 fold 모두 두 지표를 악화했다.

| 후보 | 입력 수 | Macro Log Loss 평균 | B0 대비 | Macro Brier 평균 | B0 대비 | LL/Brier 개선 fold | 판정 |
|---|---:|---:|---:|---:|---:|---:|---|
| B0 | 117 | 0.535538 | - | 0.178477 | - | - | 기준 |
| F1 | 123 | 0.534350 | -0.001188 | 0.177942 | -0.000535 | 4/4, 4/4 | KEEP |
| F2 | 125 | 0.535743 | +0.000205 | 0.178527 | +0.000050 | 0/4, 0/4 | DROP |
| F3 | 127 | 0.528864 | -0.006674 | 0.176203 | -0.002274 | 4/4, 4/4 | KEEP |

차이는 후보-B0이므로 음수가 개선이다. 작은 차이를 확대 해석하지 않기 위해 F1은 “작지만 반복된
추가 정보”, F3는 “상대적으로 크고 반복된 추가 정보”로 구분한다.

## 실행 계약

- 기간: 2023-01-01 이상, 2024-07-01 미만만 로드
- fold: 기존 네 quarterly expanding temporal fold
- 모델: official v2와 동일한 raw Logistic Pipeline
- 기존 Feature: 기존 전처리 계약 유지
- 신규 count: fold-train constant 0 imputation
- 신규 연속형: fold-train median imputation 및 기존 numeric scaling
- target: 공식 PLC `place_hit`
- Validation 접근 횟수: 0

B0의 fold별 모든 지표는 이전 M1 실험의 B0와 동일해 비교 기준이 재현됐다. 모든 fold에서 training
최대일은 evaluation 최소일보다 앞섰고 전처리와 모델은 fold train에서만 적합했다.

## Fold별 주요 지표

| Fold | 후보 | Macro LL | Δ LL | Macro Brier | Δ Brier |
|---|---|---:|---:|---:|---:|
| 1 | B0 | 0.543989 | - | 0.180554 | - |
| 1 | F1 | 0.542536 | -0.001453 | 0.179901 | -0.000653 |
| 1 | F2 | 0.544425 | +0.000436 | 0.180658 | +0.000105 |
| 1 | F3 | 0.535963 | -0.008026 | 0.178140 | -0.002414 |
| 2 | B0 | 0.533160 | - | 0.176667 | - |
| 2 | F1 | 0.532604 | -0.000555 | 0.176334 | -0.000333 |
| 2 | F2 | 0.533329 | +0.000169 | 0.176702 | +0.000035 |
| 2 | F3 | 0.526453 | -0.006706 | 0.174287 | -0.002380 |
| 3 | B0 | 0.524859 | - | 0.175192 | - |
| 3 | F1 | 0.522771 | -0.002088 | 0.174403 | -0.000789 |
| 3 | F2 | 0.525053 | +0.000194 | 0.175244 | +0.000052 |
| 3 | F3 | 0.519425 | -0.005433 | 0.173126 | -0.002067 |
| 4 | B0 | 0.540145 | - | 0.181495 | - |
| 4 | F1 | 0.539489 | -0.000656 | 0.181130 | -0.000365 |
| 4 | F2 | 0.540165 | +0.000020 | 0.181503 | +0.000008 |
| 4 | F3 | 0.533613 | -0.006532 | 0.179259 | -0.002237 |

## 평균·변동성과 calibration

- F1 Macro LL 표준편차 0.007592, Macro Brier 0.002698로 B0의 0.007286/0.002622와
  비슷하다. 시간에 따라 악화 폭이 커지는 패턴은 없다.
- F3 Macro LL 표준편차 0.006478, Macro Brier 0.002561로 B0보다 작았다. fold별 개선은
  -0.005433~-0.008026 LL 범위로 반복됐다.
- F2는 악화 폭이 fold 1에서 가장 크고 fold 4에서 작아졌지만 개선 fold는 없다.
- 평균 calibration intercept/slope는 B0 -0.0916/0.9206, F1 -0.0922/0.9171,
  F2 -0.0951/0.9176, F3 -0.0719/0.9352다. F3는 calibration도 전반적으로 0/1에
  가까워졌지만 KEEP 판정은 손실 지표 개선에 근거했다.

모든 후보에서 fold마다 동일한 수렴 경고 1건이 기록됐다. B0에도 동일하게 발생했고 실행 실패나
후보 간 설정 차이는 아니므로 이번 계약을 소급 변경하지 않았다.

## 가용성 보조 진단

- F1/F2 신규 요약값 결측행 비율은 fold 1~4에서 8.46%→3.67%로 감소했다.
- F3에서 하나 이상의 신규 값이 결측인 행은 29.07%, 28.09%, 29.17%, 19.96%였다.
- 완전 가용/결측 행의 손실 차이는 크지만 경주 구성과 이력 깊이가 다른 관찰집단 비교다. 이는
  imputation 오류나 Feature 효과의 인과 증거가 아니며 bundle 정의 변경에 사용하지 않았다.

## 판정과 다음 단계

- F1: **KEEP** — 개선은 작지만 두 주요 지표가 4/4 fold에서 같은 방향이다.
- F2: **DROP** — 두 주요 평균이 모두 악화하고 개선 fold가 0/4다.
- F3: **KEEP** — 두 주요 지표가 4/4 fold에서 개선됐고 평균 개선과 fold 안정성이 가장 크다.

다음 실험은 F1+F3 한 가지 조합만 같은 development 계약에서 B0, F1, F3와 비교하는 것이
타당하다. F2 또는 다른 조합을 다시 탐색하지 않는다. F1+F3가 독립 효과를 유지하는지 확인한 뒤에만
Validation 후보를 봉인한다.

## 재현 산출물

`data/exports/modeling/post_baseline_v2_feature_bundle_development_v1/`에 다음을 저장했다.

- `fold_metrics.csv`
- `summary_metrics.csv`
- `fold_deltas_vs_b0.csv`
- `availability_diagnostics.csv`
- `experiment_registry.json`
- `result.json`

Validation, 2024-07 이후 target/prediction, post-selection 기간은 접근하지 않았다. 봉인 baseline
run contract/refit artifact와 M1 result hash도 실행 전후 동일했다.
