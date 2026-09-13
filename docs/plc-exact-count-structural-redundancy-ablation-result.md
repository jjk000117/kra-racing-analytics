# Exact-count Structural Redundancy Ablation 결과

## 결론

사전 봉인 규칙에 따라 `DROP_EXACT_COUNT_SIMPLIFICATION`으로 판정한다. 값과 NULL
pattern까지 완전히 동일한 count 중복 7개를 제거했을 때 Development 평균 Macro Log
Loss는 `+0.00006689`, Macro Brier는 `+0.00001948` 악화했다. 두 primary가 함께
비악화한 fold는 1/4로, 요구한 3/4를 충족하지 못했다.

차이는 매우 작다. 이 결과는 대표 count가 더 중요하다거나 제거 후보가 일반적으로 무의미하다는
뜻이 아니다. 동일한 열을 반복 입력하면 현재 L2 Logistic의 정규화 효과가 달라질 수 있으며,
봉인된 LR1 학습 절차에서는 축약이 probability loss를 유지하지 못했다는 Development 결과다.
LR1 144개 계약은 유지한다.

## 계약과 exact group

- Upstream: [`plc-final-feature-diagnostic-result.md`](plc-final-feature-diagnostic-result.md)
- 계약: [`plc-exact-count-structural-redundancy-ablation-contract.json`](plc-exact-count-structural-redundancy-ablation-contract.json)
- 계약 commit: `d14a225`
- 모집단: 2023-01-06~2024-06-30, 28,392행·2,675경주
- Baseline: LR1 144, hash `7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a`
- Challenger: 137, hash `3f8ba91bcfbfc6b96479f9e5b6729f3d12ba8d9049e4bf0e745effdfe02a32e7`

진단 CSV의 `exact_value_and_null_pattern=True` pair 13개를 연결 성분으로 재구성했다.

| Group | 유지 | 제거 |
|---|---|---|
| recent3 valid count | `horse_recent3_race_time_count` | `horse_recent3_g3f_count`, `horse_recent3_g1f_count`, `horse_recent3_race_relative_time_count` |
| recent5 valid count | `horse_recent5_race_time_count` | `horse_recent5_g3f_count`, `horse_recent5_g1f_count`, `horse_recent5_race_relative_time_count` |
| recent5 start/weight count | `horse_recent5_start_count` | `horse_recent5_weight_count` |

완전 선형이지만 값이 다른 pair, 상금/bonus, near-constant, `race_type`은 제외했다.

## Primary 결과

Delta는 challenger minus LR1이며 음수가 개선이다.

| Fold | LR1 Macro LL | Challenger | Δ LL | LR1 Macro Brier | Challenger | Δ Brier | 동시 비악화 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.531234 | 0.531265 | +0.000031 | 0.176398 | 0.176405 | +0.000007 | 아니오 |
| 2 | 0.524450 | 0.524415 | -0.000035 | 0.173443 | 0.173427 | -0.000016 | 예 |
| 3 | 0.517616 | 0.517685 | +0.000069 | 0.172387 | 0.172410 | +0.000023 | 아니오 |
| 4 | 0.530945 | 0.531148 | +0.000202 | 0.178302 | 0.178366 | +0.000065 | 아니오 |
| 평균 | 0.526061 | 0.526128 | +0.000067 | 0.175132 | 0.175152 | +0.000019 | 1/4 |

봉인 규칙은 두 primary 평균이 모두 비악화이고 두 지표가 함께 비악화한 fold가 최소 3/4일
때만 KEEP이다. 두 평균이 모두 아주 작게 악화했고 반복성도 1/4이므로 DROP이다.

## Secondary 결과

| 지표 | LR1 평균 | Challenger 평균 | Δ |
|---|---:|---:|---:|
| Micro Log Loss | 0.523939 | 0.524014 | +0.000075 |
| Micro Brier | 0.174186 | 0.174209 | +0.000023 |
| Calibration intercept | -0.064502 | -0.065855 | -0.001353 |
| Calibration slope | 0.926758 | 0.925864 | -0.000894 |
| Top-1 PLC hit | 0.613443 | 0.613977 | +0.000534 |
| Recall@3 | 0.513817 | 0.513850 | +0.000033 |
| NDCG@3 | 0.536004 | 0.536286 | +0.000282 |

순위 지표의 작은 상승은 primary 판정을 뒤집지 않는다. Micro probability loss도 primary와
같은 악화 방향이었다.

## 재현성과 보호

- LR1의 4개 fold probability/calibration 지표는 기존 결과와 절대오차 0으로 재현됐다
  (허용오차 `1e-12`).
- 모든 fold에서 training date < evaluation date였고 race overlap은 없었다.
- Validation 접근 0, 2024-07-01 이후 로드 0, post-2025-07 접근 0이었다.
- 공통 source DB와 branch-local experiment DB의 SHA256은 실행 전후 동일했다.
- branch-local DB에는 테이블이나 행을 추가하지 않았다. 결과 CSV/JSON만 git-ignored
  `data/exports/modeling/plc_exact_count_structural_redundancy_ablation_v1/`에 저장했다.
- LR1 registry/code/reference result와 sealed contract의 hash도 유지됐다.
- 실행 경고는 sklearn `penalty` deprecation뿐이며 수렴 실패는 없었다.

## 산출물

- `src/kra_analytics/exact_count_ablation.py`
- `tests/test_exact_count_ablation.py`
- `docs/plc-exact-count-structural-redundancy-ablation-contract.json`
- `docs/plc-exact-count-structural-redundancy-ablation-result.md`
- git-ignored 재현 산출물: `fold_metrics.csv`, `summary_metrics.csv`, `fold_deltas.csv`,
  `fold_context.csv`, `result.json`
