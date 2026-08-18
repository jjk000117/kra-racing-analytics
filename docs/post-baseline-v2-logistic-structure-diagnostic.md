# 133-Feature Logistic 구조적 한계 진단

## 기술 요약

**최종 판정은 `MODEL_COMPLEXITY_JUSTIFIED`다.** 다만 근거는 모든 Feature에서 광범위한
비선형성이 나타났기 때문이 아니라, 다음 두 구조가 네 temporal fold에서 반복됐기 때문이다.

1. 경주 내 예측확률 격차가 작은 경주는 큰 경주보다 race-level Brier가 fold별
   `0.0121~0.0348` 높았고, 예측확률 합도 `0.387~0.537` 낮았다. 실제 PLC 적중마 수는 거의
   항상 3두였으므로, runner-level 독립 Logistic이 경쟁이 팽팽한 경주의 확률 질량을 충분히
   배분하지 못하는 패턴이다.
2. `gate × registered_runner_count`의 주변효과 제거 후 interaction 잔차 패턴은 fold 간 중앙
   상관 `0.52`, 9개 공통 cell 중 4개가 네 fold에서 같은 부호였다. `S1F × distance`도 interaction
   spread `0.060`, fold 패턴 상관 `0.46`으로 반복됐다.

반면 historical rate × count의 대부분과 absolute × field-relative 관계는 cell 잔차가 있더라도
fold 패턴 상관이 낮았다. 특히 기수·조교사 rate × count의 interaction spread는 사실상 0에
가까웠다. 따라서 다음 단계는 Feature를 다시 늘리는 실험보다 **133개 입력을 고정한 제한적
nonlinear 모델 1개**가 우선이다. 이 진단은 새 모델의 성능 개선을 입증하지 않는다.

## 분석 범위와 계약

- Source population: `2023-01-01 <= race_date < 2024-07-01`
- 전체 development: 28,392행, 2,675경주
- OOF 진단 cohort: 19,168행, 1,821경주
- Evaluation folds: 기존 quarterly expanding fold 4개
- Model: 기존 Train-only 전처리와 raw Logistic probability
- Input: 기존 117 + F1 6 + F3 10 = 133개
- Feature hash: `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`
- Residual: `place_hit - predicted_probability`

첫 6개월은 fold 학습에만 사용되므로 OOF 잔차 진단에는 포함되지 않는다. sigmoid는 전역 단조
보정이며 interaction을 새로 표현하지 못하므로 구조 진단에서는 raw fold prediction을 사용했다.

## 주요 연속형 관계는 일부 반복되지만 전부 안정적이지 않다

각 fold 안에서 대표 연속형을 5개 empirical quantile bin으로 나눴다. 아래 range는 bin별 평균
잔차의 fold 내 최대-최소 차이의 중앙값이다. shape correlation은 5-bin 잔차 모양의 fold 간
상관 중앙값이다.

| Feature | 잔차 range | 같은 low→high 방향 fold | fold shape 상관 | 해석 |
|---|---:|---:|---:|---|
| `rating` | 0.025 | 4/4 | 0.62 | rating 0과 상위 rating에서 선형 slope만으로 설명되지 않는 굴곡이 반복됨 |
| `rating_field_percentile` | 0.042 | 3/4 | 0.50 | field 내 상대 rating 효과에 중간 구간 굴곡이 남음 |
| `carried_weight_vs_field_median_kg` | 0.039 | 3/4 | 0.69 | 상대 부담중량 효과가 단일 직선보다 구간별로 달라질 가능성 |
| `horse_recent5_g3f_median` | 0.028 | 4/4 | 0.58 | 느린 G3F 쪽에서 잔차 방향이 네 fold에 반복 |
| F1 recent5 time advantage | 0.021 | 4/4 | 0.05 | 끝점 방향은 같지만 전체 bin 모양은 반복되지 않아 약한 근거 |
| 동일거리 PLC rate | 0.045 | 3/4 | -0.27 | range는 크지만 모양이 불안정해 구조적 비선형성 근거로 사용하지 않음 |

`rating`, 상대 부담중량, G3F는 제한적인 비선형 근거다. 반대로 rate 계열에서 큰 잔차 range가
보여도 fold 모양이 뒤집히는 경우가 많아, 전체 집계만으로 nonlinear 관계라고 단정하지 않았다.

## absolute × field-relative는 이미 F3가 상당 부분 흡수했다

2차원 cell 평균 잔차에서 각 변수의 주변 잔차를 제거해 interaction 잔차를 계산했다. 표본 100행
미만 cell은 반복성 판단에서 제외했다.

| 관계 | interaction spread 중앙값 | fold 패턴 상관 | 네 fold 공통 cell 중 동일 부호 | 판단 |
|---|---:|---:|---:|---|
| rating × rating percentile | 0.040 | 0.01 | 0/5 | 이질성은 있으나 시간 반복성 약함 |
| prior PLC rate × field percentile | 0.031 | 0.03 | 2/7 | 일부 cell만 반복 |
| recent5 PLC rate × field percentile | 0.028 | -0.10 | 0/6 | 반복 근거 약함 |
| S1F × field percentile | 0.038 | 0.02 | 3/7 | 일부 반복이나 전체 모양 불안정 |
| G3F × field percentile | 0.033 | 0.27 | 2/7 | 약한 반복성 |
| jockey rate × field percentile | 0.026 | -0.08 | 1/5 | 반복 근거 약함 |
| trainer rate × field percentile | 0.049 | -0.22 | 0/5 | 큰 cell 차이지만 시간적으로 불안정 |

F3가 Validation까지 개선된 사실과 별개로, absolute와 percentile을 다시 곱하는 interaction을
대량 생성할 근거는 부족하다. 남은 오차는 일부 존재하지만 공통 방향이 약하다.

## rate × observation count는 말 계열 일부만 후보이며 관계자 계열은 약하다

| 관계 | interaction spread 중앙값 | fold 패턴 상관 | 판단 |
|---|---:|---:|---|
| horse prior PLC rate × starts | 0.040 | -0.36 | cell 차이는 있으나 모양이 뒤집혀 불안정 |
| same-distance PLC rate × starts | 0.037 | 0.07 | 약한 반복성 |
| recent5 PLC rate × starts | 0.027 | 0.10 | 약한 반복성 |
| jockey recent10 rate × starts | 0.004 | -0.93 | 실질적 interaction 근거 없음 |
| trainer recent10 rate × starts | 0.003 | -0.03 | 실질적 interaction 근거 없음 |

따라서 관측 count 신뢰도를 표현하는 대규모 새 Feature bundle을 우선할 근거는 없다. 말 장기
rate에서 count-dependent shrinkage 가설은 남지만, 이번 자료에서는 모델 구조와 새 정보 부족을
명확히 분리할 만큼 안정적이지 않다.

## 반복되는 조건부 관계는 제한적이지만 존재한다

| 관계 | interaction spread 중앙값 | fold 패턴 상관 | 동일 부호 공통 cell | 해석 |
|---|---:|---:|---:|---|
| gate × registered runners | 0.054 | 0.52 | 4/9 | 게이트의 의미가 field size에 따라 달라짐 |
| S1F × distance | 0.060 | 0.46 | 1/9 | 일부 거리 조건에서 초반 속도의 의미가 다름 |
| G3F × distance | 0.057 | -0.14 | 1/9 | spread는 크지만 패턴 방향 불안정 |
| G1F × distance | 0.048 | -0.24 | 1/9 | 반복 근거 약함 |
| recent form × long-term form | 0.044 | -0.17 | 1/6 | 일관된 interaction 근거 약함 |
| F1 time percentile × rating percentile | 0.049 | 0.01 | 3/9 | 일부 cell 반복, 전체 모양은 불안정 |
| G3F × meet | 0.027 | 0.18 | 2/6 | 경마장별 분리가 즉시 필요할 정도는 아님 |

가장 분명한 조건부 구조는 `gate × field size`다. sectional × distance는 S1F에서만 중간 정도의
fold 반복성이 있었고, 복잡한 speed Feature를 즉시 추가할 근거로는 부족하다.

## 경주 내부 경쟁구조가 가장 일관된 잔여오차다

일반적인 8~12두 경주에서 예측확률 합은 대체로 3 부근이었다. 즉 runner-level Logistic도 평균적인
PLC 적중마 수 제약을 상당 부분 간접 학습했다. 그러나 경주 내 최대·최소 예측확률 격차로 경주를
4분위로 나누면 다음 패턴이 4/4 fold에서 반복됐다.

| Fold | 낮은 격차−높은 격차 race Brier | 낮은 격차 평균 잔차 | 높은 격차 평균 잔차 | 낮은−높은 예측확률 합 |
|---|---:|---:|---:|---:|
| 1 | +0.0247 | +0.0168 | -0.0219 | -0.404 |
| 2 | +0.0348 | +0.0098 | -0.0261 | -0.387 |
| 3 | +0.0145 | +0.0388 | -0.0094 | -0.537 |
| 4 | +0.0121 | +0.0226 | -0.0160 | -0.402 |

경쟁이 팽팽해 예측확률 격차가 작은 경주에서는 확률 합이 낮고 실제 hit 대비 과소예측하는 반면,
격차가 큰 경주에서는 과대예측 방향이었다. 낮은 격차 경주의 Brier도 모든 fold에서 더 나빴다.
이는 단순 전역 calibration보다 **경주 단위 경쟁 강도와 확률 질량 배분**을 직접 표현할 모델이
검토될 근거다.

경주 내 예측순위별 actual/predicted rate는 전반적으로 가까웠지만, 중상위 구간 잔차 방향은 fold별로
달랐다. 따라서 “상위마만 항상 과소예측한다” 같은 단순 순위 편향은 확인되지 않았다.

## 모델 구조 문제와 새 정보 부족의 구분

### 모델 구조 문제로 보는 근거

- 낮은/높은 경주 내 확률격차의 잔차·Brier 차이가 4/4 fold에서 같은 방향이다.
- `gate × registered_runner_count` interaction 패턴이 여러 fold에서 반복된다.
- rating, 상대 부담중량, G3F의 1차원 잔차 모양이 중간 이상의 fold 반복성을 보인다.
- 이 관계들은 현재 133개 원본에 이미 양쪽 변수가 있으므로 새 원천 없이도 nonlinear 모델이 표현할
  수 있다.

### 새 정보 또는 표현 부족 가능성이 더 큰 부분

- sectional × distance의 일부 차이는 단순 tree interaction으로 잡힐 수 있지만, 물리적으로는
  거리·주로 보정 speed representation이 더 적절할 수도 있다.
- rating 0은 연속적인 낮은 rating과 다른 “미부여” 상태일 가능성이 있어 전용 표현 문제가 섞인다.
- absolute × field-relative와 rate × count의 다수 패턴은 fold 반복성이 낮아, 현재 증거만으로
  interaction Feature를 추가할 수 없다.

## 최종 판정과 다음 실험

판정: **A. `MODEL_COMPLEXITY_JUSTIFIED`**

다음 실험은 하나로 제한한다.

- **M2: 기존 M1-B 수준의 보수적 HistGradientBoosting 설정을 133개 입력에 그대로 적용**
- 비교 기준: 동일 4개 development fold의 Logistic 133
- Feature 추가·삭제, 설정 탐색, Validation 접근 없음
- 목적: F1/F3로 보강된 동일 정보에서 제한된 nonlinear split과 interaction만으로 반복 개선되는지 확인

M1이 117개 입력에서 실패했으므로 성공을 전제하지 않는다. M2가 네 fold에서 안정적으로 개선되지
않으면 모델 복잡도 경로를 중단하고 Logistic 133을 강한 기준선으로 유지하는 것이 적절하다.

## 한계와 강건성

- quantile bin 진단은 기술통계이며 독립적인 가설검정이나 인과 추론이 아니다.
- 같은 경주의 말은 독립이 아니므로 행 수만으로 불확실성을 과소평가하면 안 된다.
- 2차원 cell은 100행 이상만 해석했지만 경주 중복과 조건 구성 차이가 남는다.
- fold별 모델과 학습량이 달라 잔차 변화에는 시간 변화와 모델 업데이트가 함께 포함된다.
- raw Logistic 잔차를 사용했으며, 전역 sigmoid는 전체 calibration을 바꿀 수 있지만 발견된 interaction
  자체를 표현하지 못한다.
- 네 fold 모두 수렴 문제는 없었다. 기존 고정 계약의 `penalty='l2'`에 대한 sklearn 향후 제거 경고만
  1회씩 기록됐으며, 계약을 바꾸지 않기 위해 이번 단계에서는 수정하지 않았다.
- Validation은 재접근하지 않았고 이 보고서는 development에서 다음 실험의 정당성만 판단한다.

## 재현 산출물

- 실행 코드: `src/kra_analytics/logistic_structure_diagnostics.py`
- CLI: `kra-analytics model diagnose-logistic-structure`
- 결과 디렉터리:
  `data/exports/modeling/post_baseline_v2_logistic_structure_diagnostic_v1/`
- 주요 CSV: 1D bins, 2D cells, pattern summaries, race-level structure, within-race rank,
  probability-gap contrasts

## 추가 질문

M2가 실패할 경우 race-aware 모델을 바로 구현할지, 아니면 PLC 확률의 경주별 합 제약을 사후 보정으로
다룰지는 별도 설계가 필요하다. 이 선택은 M2 결과를 보기 전에는 확정하지 않는다.
