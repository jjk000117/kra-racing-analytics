# Prize/Bonus Structural Redundancy Ablation 결과

## 결론

사전 봉인 규칙에 따라 `DROP_PRIZE_BONUS_SIMPLIFICATION`으로 판정한다. 1~5위 상금과
bonus 1~3의 완전 선형 중복을 대표 변수 한 개씩으로 축약했을 때 Development 평균 Macro
Log Loss는 `+0.00000994`, Macro Brier는 `+0.00000204` 악화했다. 차이는 매우 작지만 두
primary 지표가 함께 비악화한 fold도 2/4로, 요구한 3/4를 충족하지 못했다.

이는 상금 정보 자체의 유용·무용을 뜻하지 않는다. 완전 선형 구조임에도 현재의 L2 Logistic과
Train-only scaling에서는 중복 열 제거가 봉인된 temporal loss 유지 조건을 충족하지 못했다는
Development 결과다. LR1 144개 계약은 그대로 유지한다.

## 계약과 범위

- Upstream: [`plc-final-feature-diagnostic-result.md`](plc-final-feature-diagnostic-result.md)
- 계약: `plc_prize_bonus_structural_redundancy_ablation_v1`
- 계약 commit: `d9fcee7`
- 모집단: 2023-01-06~2024-06-30, 28,392행·2,675경주
- Baseline: LR1 144, hash
  `7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a`
- Challenger: 138, hash
  `e767676c30493b51f9f5548cf417fd2503a79bf08120ac41be01027fb410f260`
- 유지: `race_first_prize`, `race_bonus_1`
- 제거: `race_second_prize`, `race_third_prize`, `race_fourth_prize`,
  `race_fifth_prize`, `race_bonus_2`, `race_bonus_3`
- 비교 중 다른 Feature, target, population, preprocessing, Logistic, seed와 temporal fold는
  변경하지 않았다.

## Primary 결과

Delta는 challenger minus LR1이며 음수가 개선이다.

| Fold | LR1 Macro LL | Challenger | Δ LL | LR1 Macro Brier | Challenger | Δ Brier | 동시 비악화 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.531234 | 0.531122 | -0.000112 | 0.176398 | 0.176368 | -0.000030 | 예 |
| 2 | 0.524450 | 0.524426 | -0.000024 | 0.173443 | 0.173423 | -0.000020 | 예 |
| 3 | 0.517616 | 0.517622 | +0.000006 | 0.172387 | 0.172385 | -0.000002 | 아니오 |
| 4 | 0.530945 | 0.531115 | +0.000170 | 0.178302 | 0.178361 | +0.000060 | 아니오 |
| 평균 | 0.526061 | 0.526071 | +0.000010 | 0.175132 | 0.175134 | +0.000002 | 2/4 |

봉인 규칙은 두 primary 평균이 모두 비악화이고, 두 지표가 함께 비악화한 fold가 최소 3/4일
때만 KEEP이다. 평균 두 지표가 모두 아주 작게 악화했고 fold 반복성도 2/4이므로 DROP이다.

## Secondary 결과

| 지표 | LR1 평균 | Challenger 평균 | Δ |
|---|---:|---:|---:|
| Micro Log Loss | 0.523939 | 0.523956 | +0.000017 |
| Micro Brier | 0.174186 | 0.174192 | +0.000006 |
| Calibration intercept | -0.064502 | -0.064803 | -0.000301 |
| Calibration slope | 0.926758 | 0.926836 | +0.000078 |
| Top-1 PLC hit | 0.613443 | 0.614555 | +0.001113 |
| Recall@3 | 0.513817 | 0.513793 | -0.000024 |
| NDCG@3 | 0.536004 | 0.536320 | +0.000316 |

Top-1과 NDCG@3의 소폭 상승은 primary 판정을 뒤집지 않는다. Micro probability loss도
primary와 같은 악화 방향이었다.

## 재현성과 보호

- LR1의 4개 fold probability/calibration 지표는 기존 Development 결과와 절대오차 0으로
  재현됐다(허용오차 `1e-12`).
- 모든 fold에서 training date < evaluation date였고 race overlap은 없었다.
- Validation 접근 횟수 0, 2024-07-01 이후 로드 0, post-2025-07 접근 0이었다.
- 공통 source DB와 branch-local experiment DB는 read-only였고 SHA256이 실행 전후 동일했다.
- branch-local DB에는 테이블이나 행을 추가하지 않았다. 결과 CSV/JSON만 git-ignored
  `data/exports/modeling/plc_prize_bonus_structural_redundancy_ablation_v1/`에 생성했다.
- 다른 worktree에는 쓰지 않았고 Push도 수행하지 않았다.

## 해석 한계

이 실험은 Development 네 fold의 현재 L2 Logistic에만 해당한다. 중복 열이 L2 penalty에서
가중치 분산 방식에 영향을 줄 수 있으므로 완전 선형이라는 사실만으로 예측값이 같아지지는
않는다. fresh generalization, 상금의 인과효과 또는 다른 모델 family에서의 결과를 주장하지
않는다. 결과를 본 뒤 제거 목록·판정선·모델 설정을 변경하지 않았다.
