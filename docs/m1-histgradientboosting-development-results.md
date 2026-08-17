# M1 HistGradientBoosting development 실험 결과

기준일: 2026-08-18  
판정: **C — 모델 복잡도만으로 개선 없음, M1 폐기**

## 기술 요약

동일한 117개 입력과 네 quarterly expanding development fold에서 B0 Logistic, M1-A, M1-B를
비교했다. M1-A는 macro/micro Log Loss와 Brier가 모든 fold에서 B0보다 악화했다. M1-B는
calibration intercept/slope는 B0보다 0/1에 가까웠지만 평균 네 손실 지표가 모두 악화했고 macro
Brier는 4/4 fold에서 악화했다. 따라서 HGB의 추가 복잡도가 현재 117개 정보에서 안정적인 확률
성능 개선을 제공한다는 증거는 없다.

M1-B가 두 HGB 설정 중에는 명확히 우수하지만 official 후보로 유지하지 않는다. 추가 HGB 설정
탐색도 수행하지 않는다. 다음 단계는 모델 복잡도 축을 닫고, 별도 계약으로 F1/F2/F3 Feature 정보
가설을 설계하는 것이다.

## 범위와 평가 정의

- 데이터: 2023-01-01~2024-06-30, 2,675경주·28,392행
- 입력: official v2와 동일한 117개, hash
  `cc18ef4bf88438ccbfbe836a29aec34f5356e52976b834124a065c89e57e8d2b`
- Fold: 사전 확정한 네 expanding quarterly fold
- B0: 기존 v2 One-hot·median·scaling과 raw Logistic
- M1: fold-train ordinal encoding, native categorical mask, median/0 대체, scaling 없음
- 지표: race-level macro Log Loss/Brier, row-level micro Log Loss/Brier,
  `logit(y) = intercept + slope × logit(p)` calibration
- 표준편차: 네 사전 정의 fold의 모집단 표준편차(`ddof=0`)

Validation 및 2024-07-01 이후 데이터는 읽지 않았다.

## 네 fold 평균에서 두 HGB 모두 B0를 넘지 못했다

| 모델 | Macro Log Loss | Macro Brier | Micro Log Loss | Micro Brier | Cal. intercept | Cal. slope |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 0.535538 | 0.178477 | 0.533347 | 0.177419 | -0.0916 | 0.9206 |
| M1-A | 0.542701 | 0.181670 | 0.539901 | 0.180441 | -0.0907 | 0.8578 |
| M1-B | 0.536636 | 0.179373 | 0.534176 | 0.178288 | -0.0162 | 0.9835 |

B0 대비 M1-A 평균 차이는 macro Log Loss `+0.007163`, macro Brier `+0.003192`다.
M1-B는 각각 `+0.001098`, `+0.000896`이다. 낮을수록 좋은 네 손실 지표 모두 B0가 가장 좋다.

M1-B의 calibration은 개선됐지만 손실 악화를 상쇄하지 않는다. 이번 목적은 calibration만 맞추는
것이 아니라 raw probability의 전반적인 품질 개선이므로 후보 유지 근거가 되지 않는다.

## Fold별 비교에서 M1-A는 전면 악화, M1-B도 일관된 개선이 없었다

| Fold | B0 Macro LL | M1-A Δ | M1-B Δ | B0 Macro Brier | M1-A Δ | M1-B Δ |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 0.543989 | +0.010192 | -0.000468 | 0.180554 | +0.005203 | +0.001048 |
| 2 | 0.533160 | +0.005679 | +0.000120 | 0.176667 | +0.002517 | +0.000555 |
| 3 | 0.524859 | +0.007033 | +0.001852 | 0.175192 | +0.002626 | +0.000807 |
| 4 | 0.540145 | +0.005750 | +0.002888 | 0.181495 | +0.002424 | +0.001174 |

- M1-A 개선 fold: 네 손실 지표 모두 `0/4`
- M1-B 개선 fold: macro LL `1/4`, macro Brier `0/4`, micro LL `2/4`, micro Brier `0/4`
- M1-B macro LL 차이는 fold 1 `-0.000468`에서 fold 4 `+0.002888`로 후반부에 악화했다.
- M1-B의 Log Loss 일부 개선과 Brier 악화가 같은 방향을 가리키지 않아 안정적인 개선으로 볼 수 없다.

세부 수치는 `docs/m1-hgb-fold-comparison.csv`에 보존했다.
Fold가 4개이고 차이가 작아 축 범위에 따라 시각적 과장이 생길 수 있으므로 차트 대신 동일 자릿수의
정확한 비교표를 사용했다.

## Fold 변동성과 시간 안정성도 후보 유지 근거가 되지 않았다

| 모델 | Macro LL 표준편차 | Macro Brier 표준편차 | Micro LL 표준편차 | Micro Brier 표준편차 |
|---|---:|---:|---:|---:|
| B0 | 0.007286 | 0.002622 | 0.007697 | 0.002481 |
| M1-A | 0.008272 | 0.003270 | 0.008498 | 0.003257 |
| M1-B | 0.007038 | 0.002822 | 0.006956 | 0.002701 |

M1-B의 Log Loss 표준편차는 B0보다 소폭 작지만 Brier 변동성은 더 크다. 평균 손실 악화와
후반 fold의 B0 대비 차이 증가까지 고려하면 안정성 개선으로 해석하지 않는다. M1-A는 평균과
변동성 모두 불리하다.

## Unseen category는 HGB 악화의 주된 설명이 아니다

평가행 중 하나 이상의 unseen category를 가진 비율은 fold 1~4에서 각각 4.53%, 9.83%, 6.50%,
3.37%였다. unseen이 가장 높은 fold 2에서 M1-B의 macro LL 차이는 `+0.000120`으로 거의 같았고,
unseen이 가장 낮은 fold 4에서 오히려 `+0.002888`로 가장 크게 악화했다. 네 fold만으로 통계적
관계를 주장할 수는 없지만, 높은 unseen 비율과 특이한 HGB 성능 저하가 함께 나타났다는 증거는
없다. Train-only unknown 처리는 정상 작동했다.

## 학습시간과 실행 품질

| 모델 | 평균 fit 초 | 표준편차 | 실행 문제 |
|---|---:|---:|---|
| B0 | 1.985 | 0.796 | 수렴 문제 0; sklearn `penalty` deprecation 경고만 fold당 1건 |
| M1-A | 2.736 | 0.614 | 경고·실패 0 |
| M1-B | 2.215 | 0.754 | 경고·실패 0 |

HGB 실행시간은 충분히 작고 운영상 blocker는 없다. 성능 판정은 실행 실패가 아니라 관측된 손실
악화에 따른 것이다.

## 계약 및 보호 감사

- Feature 수 117, hash 일치
- 모든 fold에서 `max(train_date) < min(evaluation_date)`
- encoder·imputer·model은 각 fold train에서만 fit
- 평가행에는 transform·raw probability 생성만 수행
- registry의 B0/M1-A/M1-B 상태: `DEVELOPMENT_COMPLETE`
- 각 실험의 fold 지표 4개 기록 완료
- Validation 접근 횟수: 세 실험 합계 0
- sealed baseline v2 run contract/refit artifact hash: 실행 전후 일치
- baseline v2 재학습·수정: 없음

## 최종 판단과 다음 단계

판정은 **C. 개선 없음 또는 악화 → M1 폐기**다.

M1-B는 HGB 내부 대표 설정으로는 A보다 낫지만 B0 대비 평균 손실과 Brier 일관성을 통과하지 못해
M1 대표 후보로 채택하지 않는다. 추가 HGB 설정 탐색은 하지 않는다. F1/F2/F3 Feature 실험 설계로
넘어갈 준비가 됐으며, 다음에는 모델을 Logistic으로 고정해 새로운 정보의 효과를 모델 복잡도와
분리해야 한다.

## 한계와 검증 상태

- 네 fold는 개발 의사결정용이며 장기 post-selection 성능을 뜻하지 않는다.
- unseen 진단은 fold 4개에 대한 기술 비교이지 인과 또는 통계 검정이 아니다.
- 범주 처리 방식은 모델에 맞게 달라 B0와 M1의 차이가 순수 함수형 복잡도만이 아니라 native
  categorical representation도 포함한다. 사용 정보 117개는 동일하다.
- 핵심 지표는 원본 fold 결과에서 재계산했고 registry와 CSV가 일치했다.

검증 판정: **공유 가능(위 한계 포함)**.
