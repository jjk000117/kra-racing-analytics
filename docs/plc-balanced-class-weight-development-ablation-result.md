# Balanced Class Weight Development Ablation 결과

## 결론

사전 봉인 규칙에 따라 `DROP_BALANCED`로 판정한다. 동일한 137개 Feature와 temporal OOF
sigmoid 조건에서 `class_weight='balanced'`는 unweighted Logistic보다 Development 평균
calibrated Macro Log Loss를 `+0.00046319`, Macro Brier를 `+0.00028202` 악화했다. 두
primary 지표가 함께 비악화한 fold는 0/4였다.

PLC class imbalance를 직접 가중한 raw 확률은 크게 왜곡됐고 sigmoid calibration이 대부분을
복구했지만, 최종 probability objective에서 unweighted 절차를 대체할 근거는 없었다. 이는
class imbalance가 일반적으로 중요하지 않다는 뜻이 아니다.

## 계약과 모집단

- 계약: [`plc-balanced-class-weight-development-ablation-contract.json`](plc-balanced-class-weight-development-ablation-contract.json)
- Feature: 양쪽 동일 137개
- Feature hash: `7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e`
- Development: 28,392행·2,675경주, 2023-01-06~2024-06-30
- 양성 8,025, 음성 20,367, 양성률 `28.2650%`
- 전체 기준 balanced 가중치: 음성 `0.697010`, 양성 `1.768972`
- 유일한 모델 차이: `class_weight=None` 대 `class_weight='balanced'`
- 각 후보는 outer train 및 내부 OOF fit에서 자기 class-weight 계약을 동일하게 적용했다.

| Fold | Train 양성/음성 | 양성률 | 음성 weight | 양성 weight |
|---|---:|---:|---:|---:|
| 1 | 2,563 / 6,661 | 27.7862% | 0.692389 | 1.799454 |
| 2 | 3,845 / 9,837 | 28.1026% | 0.695436 | 1.779194 |
| 3 | 5,327 / 13,584 | 28.1688% | 0.696076 | 1.775014 |
| 4 | 6,624 / 16,994 | 28.0464% | 0.694892 | 1.782760 |

내부 temporal OOF fit에서도 각 당시 training subset의 class count로 같은 sklearn 공식을 다시
적용했다. 가중치는 결과를 보고 조정하지 않았다.

## Calibrated primary 결과

Delta는 balanced minus unweighted이며 음수가 개선이다.

| Fold | Unweighted LL | Balanced LL | Δ LL | Unweighted Brier | Balanced Brier | Δ Brier |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 0.534529 | 0.534623 | +0.000094 | 0.178184 | 0.178324 | +0.000141 |
| 2 | 0.524750 | 0.525150 | +0.000399 | 0.173762 | 0.174036 | +0.000275 |
| 3 | 0.518577 | 0.519419 | +0.000842 | 0.172838 | 0.173273 | +0.000435 |
| 4 | 0.531869 | 0.532386 | +0.000517 | 0.178491 | 0.178769 | +0.000278 |
| 평균 | 0.527431 | 0.527895 | +0.000463 | 0.175819 | 0.176101 | +0.000282 |

모든 fold에서 두 primary가 함께 악화했다. secondary로 판정을 뒤집지 않았다.

## Raw와 sigmoid calibration

| 후보 | Raw Macro LL | Calibrated | 변화 | Raw Macro Brier | Calibrated | 변화 |
|---|---:|---:|---:|---:|---:|---:|
| Unweighted | 0.525713 | 0.527431 | +0.001718 | 0.175062 | 0.175819 | +0.000757 |
| Balanced | 0.608696 | 0.527895 | -0.080802 | 0.210383 | 0.176101 | -0.034282 |

balanced raw 확률은 양성 class up-weighting 때문에 확률 수준이 크게 이동했다. 후보별 OOF
sigmoid가 이를 대부분 복구했지만 unweighted calibrated 확률보다 우수해지지는 못했다.
unweighted에서는 이 outer-fold OOF calibration이 평균 손실을 소폭 악화했다. calibration
방법은 결과 확인 후 변경하거나 선택하지 않았다.

## Secondary 결과

| 지표 | Unweighted | Balanced | Δ |
|---|---:|---:|---:|
| Micro Log Loss | 0.525029 | 0.525501 | +0.000472 |
| Micro Brier | 0.174783 | 0.175054 | +0.000271 |
| Calibration intercept | 0.194032 | 0.224441 | +0.030409 |
| Calibration slope | 1.196016 | 1.186953 | -0.009063 |
| Top-1 PLC hit | 0.613565 | 0.611444 | -0.002120 |
| Recall@3 | 0.513843 | 0.512021 | -0.001821 |
| NDCG@3 | 0.536050 | 0.534462 | -0.001588 |

## 재현성과 보호

- Unweighted 137 raw probability/calibration 지표는 직전 결과와 fold별 절대오차 0으로
  재현됐다(허용오차 `1e-12`).
- 모든 outer/inner fold에서 training date < prediction/evaluation date였다.
- Validation 접근 0, 2024-07-01 이후 로드 0, post-2025-07 접근 0이었다.
- 공통 source DB와 branch-local experiment DB는 read-only였고 SHA256이 실행 전후 동일했다.
- branch-local DB 테이블/행은 변경하지 않았다. 재현 가능한 CSV/JSON만 git-ignored
  `data/exports/modeling/plc_balanced_class_weight_development_ablation_v1/`에 저장했다.
- 다른 worktree와 기존 artifact는 변경하지 않았고 Push도 수행하지 않았다.

## 해석 한계

이 결과는 현재 137개 Feature, L2 Logistic, 네 Development fold와 고정 OOF sigmoid에만
해당한다. `DROP_BALANCED`는 custom weighting, resampling 또는 다른 objective를 검증한 결과가
아니다. ranking 변화만으로 probability-loss 판정을 바꾸지 않았으며 fresh generalization을
주장하지 않는다.
