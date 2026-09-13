# Near-constant Finish-rate Ablation 결과

## 결론

사전 봉인 규칙에 따라 `KEEP_NEAR_CONSTANT_FINISH_RATE_SIMPLIFICATION`으로 판정한다.
진단에서 99% near-constant로 표시된 finish-rate 5개만 제거했을 때 Development 평균
Macro Log Loss는 `-0.00026290`(-0.04998%), Macro Brier는
`-0.00006898`(-0.03939%) 개선됐다. 두 primary가 함께 비악화한 fold는 3/4로 봉인된
최소 조건을 충족했다.

개선 폭은 작다. 이 결과는 제거 Feature가 일반적으로 무의미하거나 유지한 다른 변수가 더
중요하다는 뜻이 아니다. 현재 LR1 Logistic/L2 fit과 Development 기간에서 해당 다섯 열을
제거해도 probability loss가 유지·개선됐다는 범위로만 해석한다.

## 계약과 진단 근거

- Upstream: [`plc-final-feature-diagnostic-result.md`](plc-final-feature-diagnostic-result.md)
- 계약: [`plc-near-constant-finish-rate-ablation-contract.json`](plc-near-constant-finish-rate-ablation-contract.json)
- 계약 commit: `c65244b`
- 모집단: 2023-01-06~2024-06-30, 28,392행·2,675경주
- Baseline: LR1 144, hash `7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a`
- Challenger: 139, hash `6b6b737fface03ed636302454db0d2ed9ffcdaf0e8b96f64cc5cfcba1b3cbaf9`
- Feature 감소: 5개, 3.4722%

| 제거 Feature | dominant=1 비율(비결측) | 결측률 |
|---|---:|---:|
| `horse_recent3_finish_rate` | 99.5858% | 5.6037% |
| `horse_recent5_finish_rate` | 99.3881% | 5.6037% |
| `horse_recent10_finish_rate` | 99.0411% | 5.6037% |
| `horse_same_distance_finish_rate` | 99.2508% | 25.7220% |
| `horse_same_meet_distance_finish_rate` | 99.2460% | 26.1940% |

`horse_prior_finish_rate`와 `horse_same_meet_finish_rate`는 diagnostic 99% flag를 받지 않아
유지했다. recent10 count, 관계자 count, prize/bonus, exact-duplicate count, `race_type`, PLC
hit rate와 다른 Feature도 변경하지 않았다.

## Primary 결과

Delta는 challenger minus LR1이며 음수가 개선이다.

| Fold | LR1 Macro LL | Challenger | Δ LL | LR1 Macro Brier | Challenger | Δ Brier | 동시 비악화 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.531234 | 0.531016 | -0.000218 | 0.176398 | 0.176335 | -0.000063 | 예 |
| 2 | 0.524450 | 0.523704 | -0.000746 | 0.173443 | 0.173229 | -0.000214 | 예 |
| 3 | 0.517616 | 0.517465 | -0.000151 | 0.172387 | 0.172369 | -0.000018 | 예 |
| 4 | 0.530945 | 0.531008 | +0.000063 | 0.178302 | 0.178321 | +0.000019 | 아니오 |
| 평균 | 0.526061 | 0.525798 | -0.000263 | 0.175132 | 0.175063 | -0.000069 | 3/4 |

봉인 규칙은 두 primary 평균이 모두 비악화이고, 두 지표가 함께 비악화한 fold가 최소 3/4일
때 KEEP이다. 두 평균이 개선됐고 fold 1~3에서 조건을 충족해 KEEP이다.

## Secondary 결과

| 지표 | LR1 평균 | Challenger 평균 | Δ |
|---|---:|---:|---:|
| Micro Log Loss | 0.523939 | 0.523686 | -0.000254 |
| Micro Brier | 0.174186 | 0.174123 | -0.000064 |
| Calibration intercept | -0.064502 | -0.063284 | +0.001217 |
| Calibration slope | 0.926758 | 0.929677 | +0.002919 |
| Top-1 PLC hit | 0.613443 | 0.614476 | +0.001033 |
| Recall@3 | 0.513817 | 0.514059 | +0.000242 |
| NDCG@3 | 0.536004 | 0.536369 | +0.000365 |

Secondary도 대체로 개선 방향이지만 primary 판정만 적용했다.

## 재현성과 보호

- LR1의 4개 fold probability/calibration 지표는 기존 결과와 절대오차 0으로 재현됐다
  (허용오차 `1e-12`).
- 모든 fold에서 training date < evaluation date였고 race overlap은 없었다.
- Validation 접근 0, 2024-07-01 이후 로드 0, post-2025-07 접근 0이었다.
- 공통 source DB와 branch-local experiment DB의 SHA256은 실행 전후 동일했다.
- branch-local DB에는 테이블이나 행을 추가하지 않았다. 결과 CSV/JSON만 git-ignored
  `data/exports/modeling/plc_near_constant_finish_rate_ablation_v1/`에 저장했다.
- 다른 worktree를 수정하지 않았다.
- 실행 경고는 sklearn `penalty` deprecation뿐이며 수렴 실패는 없었다.

## 산출물

- `src/kra_analytics/near_constant_finish_rate_ablation.py`
- `tests/test_near_constant_finish_rate_ablation.py`
- `docs/plc-near-constant-finish-rate-ablation-contract.json`
- `docs/plc-near-constant-finish-rate-ablation-result.md`
- git-ignored: `fold_metrics.csv`, `summary_metrics.csv`, `fold_deltas.csv`,
  `fold_context.csv`, `removed_feature_profile.csv`, `result.json`
