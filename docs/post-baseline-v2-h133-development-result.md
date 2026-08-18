# 133-Feature HGB 제한 실험 결과

## 결론

판정은 **C. `DROP_NONLINEAR`**이다. 동일 133개 입력에서 보수적 HGB는 Logistic보다 Macro Log
Loss와 Macro Brier를 평균적으로 모두 악화시켰고, 두 지표 모두 개선 fold가 `0/4`였다.

따라서 현재 HGB/nonlinear 경로는 종료하고 **Logistic 133을 주 모델 후보로 유지**한다. HGB의
추가 설정 탐색, 다른 boosting family 추가와 Validation 접근은 수행하지 않는다.

## 실행 계약

- Development: `2023-01-01 <= race_date < 2024-07-01`
- 전체 모집단: 28,392행, 2,675경주
- OOF 평가 합계: 19,168행, 1,821경주
- Fold: 기존 quarterly expanding temporal fold 4개
- Target: 공식 PLC `place_hit`
- 입력: 기존 117 + F1 6 + F3 10 = 133개
- Feature hash: `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`
- 비교: raw L133 vs raw H133

H133은 범주형 11개를 fold-train `OrdinalEncoder`와 HGB native categorical mask로 처리했다.
수치형 122개는 scaling 없이 일반 연속형은 fold-train median, Historical/F1 count는 0으로
대체했다. 133개 확장으로 인한 별도 기술 수정은 필요하지 않았다.

실제 HGB 설정:

```text
loss='log_loss'
learning_rate=0.1
max_iter=100
max_leaf_nodes=15
max_depth=None
min_samples_leaf=20
max_bins=255
l2_regularization=1.0
early_stopping=False
random_state=20260817
class_weight=None
```

## Fold별 성능

손실은 낮을수록 좋다. Delta는 `H133 - L133`이다.

| Fold | Model | Macro LL | Macro Brier | Micro LL | Micro Brier | Cal. intercept | Cal. slope |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | L133 | 0.534530 | 0.177632 | 0.534185 | 0.177206 | -0.1252 | 0.8879 |
| 1 | H133 | 0.539602 | 0.180247 | 0.538419 | 0.179729 | -0.0658 | 0.8926 |
| 2 | L133 | 0.525868 | 0.174000 | 0.524179 | 0.173308 | -0.1355 | 0.9284 |
| 2 | H133 | 0.528587 | 0.175258 | 0.526292 | 0.174293 | -0.0287 | 0.9658 |
| 3 | L133 | 0.517162 | 0.172291 | 0.514770 | 0.171251 | +0.0049 | 0.9443 |
| 3 | H133 | 0.519569 | 0.173218 | 0.517317 | 0.172180 | -0.0199 | 0.9978 |
| 4 | L133 | 0.533181 | 0.179052 | 0.528817 | 0.177246 | -0.0401 | 0.9610 |
| 4 | H133 | 0.537501 | 0.180549 | 0.533345 | 0.178786 | +0.0218 | 0.9922 |

| Fold | Δ Macro LL | Δ Macro Brier | Δ Micro LL | Δ Micro Brier |
|---|---:|---:|---:|---:|
| 1 | +0.005072 | +0.002615 | +0.004233 | +0.002523 |
| 2 | +0.002719 | +0.001258 | +0.002112 | +0.000985 |
| 3 | +0.002407 | +0.000928 | +0.002546 | +0.000929 |
| 4 | +0.004320 | +0.001496 | +0.004527 | +0.001540 |

## 평균과 시간 반복성

| Metric | L133 평균 ± SD | H133 평균 ± SD | H133−L133 | 개선 fold |
|---|---:|---:|---:|---:|
| Macro Log Loss | 0.527685 ± 0.006912 | 0.531315 ± 0.007943 | +0.003630 | 0/4 |
| Macro Brier | 0.175744 ± 0.002715 | 0.177318 ± 0.003165 | +0.001574 | 0/4 |
| Micro Log Loss | 0.525488 ± 0.007129 | 0.528843 ± 0.007927 | +0.003355 | 0/4 |
| Micro Brier | 0.174752 ± 0.002578 | 0.176247 ± 0.003120 | +0.001494 | 0/4 |

H133은 Macro Log Loss를 약 0.69%, Macro Brier를 약 0.90% 악화시켰다. H133의 fold 간 표준편차도
두 주요 지표 모두 L133보다 높았다. 특정 fold에 국한된 문제가 아니라 4개 기간에서 같은 방향이다.

## Calibration은 개선됐지만 선택 근거가 되지 않는다

| Model | intercept 평균 ± SD | slope 평균 ± SD |
|---|---:|---:|
| L133 | -0.0740 ± 0.0587 | 0.9304 ± 0.0271 |
| H133 | -0.0232 ± 0.0311 | 0.9621 ± 0.0419 |

H133은 평균 intercept와 slope가 이상적인 `0/1`에 더 가까웠다. 그러나 calibration만으로 후보를
KEEP하지 않는 사전 계약에 따라, 모든 fold에서 악화한 Log Loss와 Brier가 판정을 지배한다.

## 사전 구조 진단 영역

### 주요 1차원 비선형 구간

| 영역 | L133 잔차 range | H133 잔차 range | 변화 | 판단 |
|---|---:|---:|---:|---|
| rating | 0.0249 | 0.0139 | -0.0110 | 폭은 감소했으나 fold 방향 반복성 4→2로 약화 |
| field-relative carried weight | 0.0390 | 0.0365 | -0.0025 | 소폭 감소에 그침 |
| historical G3F | 0.0280 | 0.0322 | +0.0043 | 악화, 방향 반복성 4→2 |

HGB는 rating의 집계 잔차 폭을 줄였지만 시간적 모양을 안정적으로 재현하지 못했다. G3F는 오히려
잔차 폭이 커졌다. 전체 손실 악화를 상쇄할 정도의 구조 개선은 아니다.

### 조건부 interaction

| 관계 | L133 interaction spread | H133 spread | 변화 | 판단 |
|---|---:|---:|---:|---|
| gate × registered runners | 0.0545 | 0.0481 | -0.0064 | 일부 감소, fold 패턴 상관은 0.52→0.51로 동일 |
| S1F × distance | 0.0621 | 0.0594 | -0.0027 | 미미한 감소 |

HGB가 일부 interaction 잔차 폭을 줄였지만, 감소가 작고 overall probability loss는 모든 fold에서
악화했다.

### 낮은/높은 경주 내 probability-gap

사전 진단의 L133 probability-gap 구간을 그대로 고정해 두 모델을 비교했다. 낮은 gap 경주의
race Brier는 H133이 fold 1~4에서 각각 `+0.00029`, `+0.00174`, `+0.00209`, `+0.00253` 높았다.
즉 가장 중요한 사전 구조적 한계에서 H133은 `0/4` fold 개선했다.

낮은 gap 경주의 예측확률 합은 fold 3·4에서는 실제 3에 가까워졌지만 fold 1·2에서는 더 멀어졌다.
높은 gap 경주의 합도 일부 개선됐지만 runner-level Brier 개선으로 이어지지 않았다. 확률 질량 합만
가까워지는 것과 개별 말 확률의 정확도 개선은 동일하지 않다.

## 실행 안정성과 보호

- H133 평균 적합시간: 약 2.58초/fold
- L133 평균 적합시간: 약 2.28초/fold
- H133 경고·실패: 0건
- L133: 기존 sklearn `penalty='l2'` deprecation 경고만 fold당 1건, 수렴 실패 0건
- temporal ordering 위반: 0건
- preprocessing fit scope: fold-train only
- Validation 접근: `1 → 1`
- 최대 조회일: 2024-06-30
- 2024-07 이후 조회: 0건
- PROMOTE Validation 결과, F1/F3 구현, M1 결과, baseline run contract와 refit artifact hash 유지

## 최종 판정

**C. `DROP_NONLINEAR`**

- Macro LL/Brier 평균 모두 악화
- 두 주요 지표의 개선 fold가 모두 0/4
- Micro 지표도 0/4 개선
- calibration 개선은 손실 악화를 상쇄하지 못함
- 사전 structural diagnostic의 핵심 low-gap 영역도 0/4 개선

추가 HGB tuning이나 다른 boosting model 탐색은 권장하지 않는다. 현재까지의 증거는 “구조적
잔여오차가 관찰됐다”와 “보수적 HGB가 그것을 유용하게 학습했다”가 서로 다른 명제임을 보여준다.
주 모델 후보는 Logistic 133으로 유지한다.

## 재현 산출물

- 실행 코드: `src/kra_analytics/h133_experiment.py`
- CLI: `kra-analytics model run-h133-development`
- 출력: `data/exports/modeling/post_baseline_v2_h133_development_v1/`
- 출력에는 fold/summary/delta, structural 1D/interaction/race-gap와 registry JSON이 포함된다.
