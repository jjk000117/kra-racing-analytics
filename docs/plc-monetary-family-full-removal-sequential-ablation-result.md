# Monetary Feature Family 전체 제거 순차 Ablation 결과

## 결론

사전 봉인 규칙에 따라 `DROP_MONETARY_FAMILY_REMOVAL`로 판정한다. 직전 KEEP 누적 상태의
137개 후보에서 prize/bonus 금액 Feature 8개를 모두 제거하자 Development 평균 Macro Log
Loss는 `+0.00002242` 악화했고 Macro Brier는 `-0.00002077` 개선했다. 두 primary가 함께
비악화한 fold는 1/4뿐이므로 요구한 3/4를 충족하지 못했다.

이 결과는 상금 정보의 독립적 중요도나 인과효과를 뜻하지 않는다. `race_grade`,
`race_prize_condition`, rating 계열과 다른 race context를 유지했더라도, 현재 137개 L2
Logistic에서 금액 family 전체 제거는 봉인된 temporal probability-loss 기준을 통과하지 못했다.

## 계약과 범위

- Upstream 진단: [`plc-final-feature-diagnostic-result.md`](plc-final-feature-diagnostic-result.md)
- 이전 구조 축약 결과:
  [`plc-prize-bonus-structural-redundancy-ablation-result.md`](plc-prize-bonus-structural-redundancy-ablation-result.md)
- 모집단: 2023-01-06~2024-06-30, 28,392행·2,675경주
- Baseline: 137개, hash
  `7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e`
- Challenger: 129개, hash
  `253891f6a97c65df4a5e9f1046efb9f7824fd4fd5d7e3d0cc4135e3b5e3db028`
- Feature 감소: 8개, `5.8394%`
- 제거: `race_first_prize`, `race_second_prize`, `race_third_prize`,
  `race_fourth_prize`, `race_fifth_prize`, `race_bonus_1`, `race_bonus_2`,
  `race_bonus_3`
- 유지: `race_grade`, `race_prize_condition`, rating/history와 그 밖의 race context
- Logistic, preprocessing, seed, population, target, four expanding temporal folds는 동일하다.

## Primary 결과

Delta는 challenger minus 137개 baseline이며 음수가 개선이다.

| Fold | Baseline Macro LL | Challenger | Δ LL | Baseline Macro Brier | Challenger | Δ Brier | 동시 비악화 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.530536 | 0.530685 | +0.000148 | 0.176280 | 0.176212 | -0.000067 | 아니오 |
| 2 | 0.523621 | 0.523586 | -0.000035 | 0.173200 | 0.173203 | +0.000003 | 아니오 |
| 3 | 0.517724 | 0.517711 | -0.000013 | 0.172464 | 0.172465 | +0.000001 | 아니오 |
| 4 | 0.530971 | 0.530960 | -0.000011 | 0.178303 | 0.178283 | -0.000020 | 예 |
| 평균 | 0.525713 | 0.525735 | +0.000022 | 0.175062 | 0.175041 | -0.000021 | 1/4 |

- Macro Log Loss 상대 변화: `+0.004265%`
- Macro Brier 상대 변화: `-0.011864%`

봉인 규칙은 두 primary 평균이 모두 비악화이고, 두 지표가 함께 비악화한 fold가 최소 3/4일
때만 KEEP이다. 이번 결과는 두 조건을 모두 만족하지 못했다. 변화는 매우 작지만 사전 기준은
그대로 적용했다.

## Secondary 결과

| 지표 | Baseline 평균 | Challenger 평균 | Δ |
|---|---:|---:|---:|
| Micro Log Loss | 0.523578 | 0.523599 | +0.000021 |
| Micro Brier | 0.174122 | 0.174088 | -0.000034 |
| Calibration intercept | -0.059842 | -0.060519 | -0.000677 |
| Calibration slope | 0.931720 | 0.931170 | -0.000550 |
| Top-1 PLC hit | 0.613565 | 0.611866 | -0.001698 |
| Recall@3 | 0.513843 | 0.513479 | -0.000364 |
| NDCG@3 | 0.536050 | 0.535527 | -0.000522 |

Secondary는 primary 판정을 뒤집지 않는다. Micro Brier는 개선됐지만 Micro Log Loss와 세
ranking 지표는 작게 악화했다.

## 재현성과 보호

- 137개 baseline의 4개 fold Macro/Micro probability loss와 calibration 지표는 직전 결과와
  절대오차 0으로 재현됐다(허용오차 `1e-12`).
- 모든 fold에서 training date < evaluation date였고 race overlap은 없었다.
- Validation 접근 0, 2024-07-01 이후 로드 0, post-2025-07 접근 0이었다.
- 공통 source DB와 branch-local experiment DB는 read-only였고 SHA256이 실행 전후 동일했다.
- branch-local DB에는 테이블이나 행을 추가하지 않았다. 재현 가능한 CSV/JSON만 git-ignored
  `data/exports/modeling/plc_monetary_family_full_removal_sequential_ablation_v1/`에 생성했다.
- 다른 worktree에는 쓰지 않았고 Push도 수행하지 않았다.

## 해석 한계

이 결과는 Development 네 fold와 현재 L2 Logistic에만 해당한다. 이전 8→2 구조 축약과 이번
8→0 제거는 질문이 다르며, 이번 DROP이 개별 상금 Feature의 독립적 중요도를 증명하지 않는다.
fresh generalization이나 다른 모델 family의 결과도 주장하지 않는다. 결과 확인 뒤 Feature,
판정선, 모델 설정을 변경하지 않았다.
