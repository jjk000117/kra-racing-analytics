# RA1 race-aware development experiment

## 결론

봉인된 계약을 그대로 실행한 결과는 `DROP_RACE_AWARE`다. 동일한 133개 정보를 사용한
선형 pairwise Logistic은 runner-level L133보다 시간적으로 반복 가능한 추가 정보를
제공하지 못했다. Macro NDCG@3는 평균 `+0.000348` 높았지만 Micro Recall@3는
`-0.000271` 낮았고, 확률 손실은 모든 fold에서 악화했다. 계약에 따라 추가 pairwise
설정 탐색은 하지 않는다.

## 실행 전 계약 검증

- 계약: `post_baseline_v2_race_aware_ra1_v1`
- 계약 SHA256: `d6d9fe6ccfe9b9e73605101062ab838ff0f7af3ef92f28c6f7f0f4d9b70d6570`
- 입력: 기존 117 + F1 6 + F3 10 = 133개
- Feature hash: `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`
- 이름·순서·hash, F1/F3 구현, 전처리, ranker 설정, nested sigmoid, 네 fold와 판정
  규칙 검증을 모두 통과했다.
- Validation model-selection 접근 1회와 descriptive re-access 1회는 작업 전후 동일했다.
- baseline v2 run contract/refit artifact와 기존 Validation·M1·H133·Feature 구현 파일의
  SHA256는 작업 전후 동일했다.

## Development 모집단과 fold

접근 범위는 `2023-01-01 <= race_date < 2024-07-01`뿐이다. 실제 데이터는
2,675경주·28,392행이며 마지막 경주일은 2024-06-30이다.

| Fold | Train 기간 | Train 경주/행 | Evaluation 기간 | Evaluation 경주/행 |
|---|---|---:|---|---:|
| 1 | 2023-01-06~2023-06-30 | 854 / 9,224 | 2023-07-01~09-24 | 427 / 4,458 |
| 2 | 2023-01-06~2023-09-24 | 1,281 / 13,682 | 2023-10-06~12-31 | 494 / 5,229 |
| 3 | 2023-01-06~2023-12-31 | 1,775 / 18,911 | 2024-01-05~03-31 | 432 / 4,707 |
| 4 | 2023-01-06~2024-03-31 | 2,207 / 23,618 | 2024-04-05~06-30 | 468 / 4,774 |

모든 fold에서 `max(train date) < min(evaluation date)`, 경주 교집합 0, 경주 partition
분할 0을 확인했다. 전처리와 모델은 각 outer/inner Train에서만 적합했다.

## RA1 구현과 pair 감사

각 Train 경주에서 모든 PLC 양성–음성 조합과 반대 방향 pair를 만들었다. 변환된 runner
vector의 차이를 사용하고 directed pair weight는 `1 / (2 × positive × negative)`로 두어
경주별 전체 weight를 정확히 1로 맞췄다.

| Fold full Train | 경주 | Directed pairs | 경주별 weight min/max |
|---|---:|---:|---:|
| 1 | 854 | 39,992 | 1.0 / 1.0 |
| 2 | 1,281 | 59,062 | 1.0 / 1.0 |
| 3 | 1,775 | 81,546 | 1.0 / 1.0 |
| 4 | 2,207 | 102,020 | 1.0 / 1.0 |

Outer full-Train pair는 합계 282,620개다. Nested OOF 내부 학습까지 포함하면 총 684,066개
directed pair를 처리했다. 관측된 모든 Train 경주는 양성과 음성을 함께 가져 single-label
제외 경주는 0이었다. Cross-race, positive-positive, negative-negative, reverse 누락은 모두
0건이며 표본 차분 재계산 최대 절대오차도 0이었다.

RA1 score는 확률로 직접 사용하지 않았다. 각 outer Train 안에서 최초 3개월 학습 후 다음
3개월 예측을 반복하는 expanding OOF score를 만들고, 그 score와 target으로 단일 sigmoid를
적합했다. 모든 inner fold에서 시간 순서 위반과 evaluation 통계 유입은 0건이었다.

## Fold별 핵심 결과

값은 `RA1 - L133` 차이다. 손실은 음수, 순위 지표는 양수가 개선이다.

| Fold | Δ Macro LL | Δ Macro Brier | Δ NDCG@3 | Δ Micro Recall@3 |
|---|---:|---:|---:|---:|
| 1 | +0.034811 | +0.015052 | +0.000550 | -0.001560 |
| 2 | +0.023500 | +0.010120 | +0.005722 | +0.006073 |
| 3 | +0.022398 | +0.008451 | +0.002380 | +0.001542 |
| 4 | +0.026983 | +0.010589 | -0.007258 | -0.007138 |

| 지표 | L133 평균 ± SD | RA1 평균 ± SD | 개선 fold |
|---|---:|---:|---:|
| Macro Log Loss | 0.529077 ± 0.007297 | 0.556000 ± 0.011740 | 0/4 |
| Macro Brier | 0.176366 ± 0.002877 | 0.187419 ± 0.004982 | 0/4 |
| Micro Log Loss | 0.526634 ± 0.007373 | 0.553641 ± 0.012001 | 0/4 |
| Micro Brier | 0.175296 ± 0.002761 | 0.186326 ± 0.005086 | 0/4 |
| Macro NDCG@3 | 0.534570 ± 0.001976 | 0.534918 ± 0.005584 | 3/4 |
| Micro Recall@3 | 0.511621 ± 0.002297 | 0.511350 ± 0.006848 | 2/4 |

RA1의 Macro Log Loss와 Brier 상대 악화는 각각 5.09%, 6.27%다. Calibration
intercept/slope 평균도 L133 `0.169/1.188`에서 RA1 `0.330/1.356`으로 0/1에서 더 멀어지고
fold 변동성이 커졌다.

보조 순위 지표에서는 Top-1 적중률이 61.20%에서 61.50%, Macro AP가 0.63954에서
0.64091로 소폭 높아졌다. 반면 Top-3 최소 한 적중 포함률은 92.98%에서 92.42%,
Micro Recall@3는 51.16%에서 51.14%로 낮아졌다. 일부 보조 지표의 작은 개선만으로는
사전 계약상 승격할 수 없다.

## 자동 판정

- NDCG@3 평균 개선: 통과, fold 반복 3/4 통과
- Micro Recall@3 평균 개선: 실패, fold 반복 2/4 실패
- Macro Log Loss no-worse: 실패
- Macro Brier no-worse: 실패
- 각 확률 손실 상대 악화 1% 이내: 실패
- 최종: `DROP_RACE_AWARE`

즉, 경주 내 positive-vs-negative 경쟁을 직접 학습한 선형 RA1은 L133과 거의 같은 순위
정보를 다른 목적함수로 재표현했을 뿐, 안정적인 순위 개선을 만들지 못했고 확률 품질은
명확히 악화했다. 이 결과는 선형 pairwise 경로에 한정되며 race-aware 학습 전체의 불가능성을
뜻하지는 않지만, 현 계약에 따라 추가 pairwise tuning은 진행하지 않는다.

## 보호·재현성

- Validation 및 2024-07-01 이후 행 접근: 0
- 2025-07 이후 접근 및 post-selection 평가: 0
- 현재 경주 결과의 Feature 사용: 0; `place_hit`은 Train pair relevance와 평가에만 사용
- Feature 추가·제거·순서 변경: 0
- sealed baseline/L133/F1/F3/M1/H133 산출물 변경: 0
- 실행 산출물: `data/exports/modeling/post_baseline_v2_ra1_development_v1/`
  - `result.json`, `experiment_registry.json`
  - `fold_metrics.csv`, `summary_metrics.csv`, `fold_deltas.csv`
  - `pair_audit.csv`, `pair_by_race_audit.csv`, `nested_oof_folds.csv`

다음 단계에서는 RA1 설정을 더 탐색하지 않는다. L133+sigmoid를 대표 후보로 유지하고,
공통 post-selection temporal evaluation을 열기 전 현재까지 봉인된 후보 범위와 평가 실행
여부를 별도로 결정한다.

## 구현 검증

- Pytest: 71 passed, 1 skipped(이미 소비된 one-time Validation 재실행 방지 테스트)
- Ruff: 통과
- mypy: 35 source files 통과
- `git diff --check`: 통과
- Logistic `penalty` 인자의 sklearn 향후 deprecation 경고만 있었고 수렴 경고·실행 실패는 0건
