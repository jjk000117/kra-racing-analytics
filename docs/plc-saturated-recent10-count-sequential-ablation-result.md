# Saturated Recent10 Count Sequential Ablation 결과

## 결론

사전 봉인 규칙에 따라 `KEEP_SATURATED_RECENT10_COUNT_SIMPLIFICATION`으로 판정한다.
직전 KEEP된 139개 finish-rate simplified baseline에서 near-constant recent10 start count
2개를 추가 제거했을 때 Development 평균 Macro Log Loss는 `-0.00008543`
(-0.01625%), Macro Brier는 `-0.00000187`(-0.00107%) 개선됐다. 두 primary가 함께
비악화한 fold는 3/4로 최소 조건을 충족했다.

Macro Brier 차이는 사실상 매우 작다. 이 결과는 기수·조교사 이력이나 count가 일반적으로
무의미하다는 뜻이 아니다. finish-rate simplification을 유지한 현재 139개 Logistic/L2
조건에서 포화된 두 recent10 count를 추가 제거해도 봉인된 Development probability-loss
기준을 통과했다는 범위로만 해석한다.

## 계약과 순차 baseline

- Upstream: [`plc-final-feature-diagnostic-result.md`](plc-final-feature-diagnostic-result.md)
- 직전 결과: [`plc-near-constant-finish-rate-ablation-result.md`](plc-near-constant-finish-rate-ablation-result.md)
- 계약: [`plc-saturated-recent10-count-sequential-ablation-contract.json`](plc-saturated-recent10-count-sequential-ablation-contract.json)
- 계약 commit: `f63edec`
- 모집단: 2023-01-06~2024-06-30, 28,392행·2,675경주
- Baseline: 139개, hash `6b6b737fface03ed636302454db0d2ed9ffcdaf0e8b96f64cc5cfcba1b3cbaf9`
- Challenger: 137개, hash `7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e`
- 이번 단계 Feature 감소: 2개, 1.4388%
- LR1 144 대비 누적 감소: finish-rate 5개와 recent10 count 2개, 총 7개

| 제거 Feature | dominant=10 비율(비결측) | 결측률 |
|---|---:|---:|
| `jockey_recent10_start_count` | 99.4717% | 0.0000% |
| `trainer_recent10_start_count` | 99.8662% | 0.0000% |

finish-rate 5개는 baseline과 challenger 양쪽에서 제거된 상태를 유지했다. 그 밖의 count/rate,
prize/bonus, exact duplicate, `race_type`, PLC rate는 변경하지 않았다.

## Primary 결과

Delta는 challenger minus 139-feature baseline이며 음수가 개선이다.

| Fold | Baseline Macro LL | Challenger | Δ LL | Baseline Macro Brier | Challenger | Δ Brier | 동시 비악화 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.531016 | 0.530536 | -0.000480 | 0.176335 | 0.176280 | -0.000056 | 예 |
| 2 | 0.523704 | 0.523621 | -0.000084 | 0.173229 | 0.173200 | -0.000030 | 예 |
| 3 | 0.517465 | 0.517724 | +0.000260 | 0.172369 | 0.172464 | +0.000095 | 아니오 |
| 4 | 0.531008 | 0.530971 | -0.000037 | 0.178321 | 0.178303 | -0.000018 | 예 |
| 평균 | 0.525798 | 0.525713 | -0.000085 | 0.175063 | 0.175062 | -0.000002 | 3/4 |

두 primary 평균이 모두 비악화이고 두 지표 동시 비악화가 3/4 fold이므로 KEEP이다.
별도 practical-equivalence margin은 도입하지 않았다.

## Secondary 결과

| 지표 | 139 baseline 평균 | Challenger 평균 | Δ |
|---|---:|---:|---:|
| Micro Log Loss | 0.523686 | 0.523578 | -0.000108 |
| Micro Brier | 0.174123 | 0.174122 | -0.0000003 |
| Calibration intercept | -0.063284 | -0.059842 | +0.003442 |
| Calibration slope | 0.929677 | 0.931720 | +0.002043 |
| Top-1 PLC hit | 0.614476 | 0.613565 | -0.000911 |
| Recall@3 | 0.514059 | 0.513843 | -0.000217 |
| NDCG@3 | 0.536369 | 0.536050 | -0.000319 |

순위 지표는 소폭 악화했지만 secondary이므로 primary 판정을 뒤집지 않는다.

## 재현성과 보호

- 직전 139개 baseline의 4개 fold probability/calibration 지표는 기존 결과와 절대오차 0으로
  재현됐다(허용오차 `1e-12`).
- 모든 fold에서 training date < evaluation date였고 race overlap은 없었다.
- Validation 접근 0, 2024-07-01 이후 로드 0, post-2025-07 접근 0이었다.
- 공통 source DB와 branch-local experiment DB의 SHA256은 실행 전후 동일했다.
- branch-local DB에는 테이블이나 행을 추가하지 않았다. 결과 CSV/JSON만 git-ignored
  `data/exports/modeling/plc_saturated_recent10_count_sequential_ablation_v1/`에 저장했다.
- 직전 139개 계약·결과와 LR1 registry도 변경되지 않았고 다른 worktree를 수정하지 않았다.
- 실행 경고는 sklearn `penalty` deprecation뿐이며 수렴 실패는 없었다.

## 산출물

- `src/kra_analytics/saturated_recent10_count_ablation.py`
- `tests/test_saturated_recent10_count_ablation.py`
- `docs/plc-saturated-recent10-count-sequential-ablation-contract.json`
- `docs/plc-saturated-recent10-count-sequential-ablation-result.md`
- git-ignored: `fold_metrics.csv`, `summary_metrics.csv`, `fold_deltas.csv`,
  `fold_context.csv`, `removed_feature_profile.csv`, `result.json`
