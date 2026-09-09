# Ranking R2 F3-ablation Development 결과

작성일: 2026-09-09  
판정: `KEEP_F3_REMOVAL`

## 결론

봉인된 R2는 R1의 L133에서 current-field relative F3 10개만 제거한 L123으로 동일한
binary PLC LambdaRank를 네 Development fold에 실행했다. R2 평균 NDCG@3는
`0.527814`로 R1 `0.527690`보다 `+0.000124` 높았고 3/4 fold에서 개선했다. 평균
Macro Recall@3도 `0.503981`에서 `0.504769`로 `+0.000788` 개선해 세 KEEP 조건을
모두 만족했다.

이 결과는 F3 전체 제거를 R1보다 선호한다는 뜻이다. 개선 폭은 작고 fold 4에서
NDCG@3가 `-0.009015` 악화됐으며 R2도 L133 Logistic context `0.534570`보다
`-0.006756` 낮다. 따라서 LambdaRank standalone challenger가 L133을 대체한다는 근거는 아니다.

## 계약과 환경

- 설계 commit: `f77939bdfe97d9f51aad99ef4b371203cccbf701`
- R1: 133 Features, hash `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`
- R2: 123 Features, hash `0b0c545fb5a2135cbd4b8362e3c7bd72231f05b43dbfdfaccec64198dc3469cc`
- 제거: repository `F3_FEATURES`와 동일한 10개; F1 6개 전부 유지; 다른 제거 0
- 모집단: 28,392행, 2,675경주
- OOF: 19,168행, 1,821경주
- Model: LightGBM 4.6.0 `LGBMRanker`, `lambdarank`, label gain `[0,1]`
- Query/rounds/seed: `race_id` / 200 / 20260908
- Early stopping, tuning, calibration: 없음
- 네 fold 모두 R1과 train/eval 행·경주 수가 일치하고 train max date < eval min date,
  race overlap 0을 확인했다.
- R2 transformed width는 fold별 191/208/238/250으로 R1보다 정확히 10씩 작았다.

## Primary NDCG@3

| Fold | R1 | R2 | Delta | Relative delta |
|---|---:|---:|---:|---:|
| fold_1 | 0.519906 | 0.528528 | +0.008622 | +1.6584% |
| fold_2 | 0.536462 | 0.536678 | +0.000216 | +0.0402% |
| fold_3 | 0.522838 | 0.523511 | +0.000673 | +0.1287% |
| fold_4 | 0.531554 | 0.522539 | -0.009015 | -1.6959% |
| Mean | 0.527690 | 0.527814 | +0.000124 | +0.0235% |

개선 fold는 3/4다.

## Recall과 secondary metrics

| Metric | R1 mean | R2 mean | Delta |
|---|---:|---:|---:|
| Macro Recall@3 | 0.503981 | 0.504769 | +0.000788 |
| Top1 PLC hit | 0.608049 | 0.605032 | -0.003017 |
| Top3 any PLC hit | 0.925283 | 0.926234 | +0.000951 |
| Mean PLC hits in Top3 | 1.511326 | 1.513530 | +0.002204 |

Top1 PLC hit 악화는 사전 KEEP 조건이 아니며 primary와 Recall 조건을 뒤집지 않는다.

## 판정

1. 평균 NDCG@3 개선: 통과 (`+0.000124`)
2. 최소 3/4 fold 개선: 통과 (`3/4`)
3. 평균 Macro Recall@3 비악화: 통과 (`+0.000788`)

최종 판정은 `KEEP_F3_REMOVAL`이다.

## OOF와 selection 변화

- R2 OOF coverage: 100%
- Duplicate key: 0
- Missing prediction: 0
- Rank continuity: 통과
- R1/R2/PLC one-to-one join: 19,168행, 1,821경주, 100%
- R1/R2 Top1 동일 horse: 76.94%
- R1/R2 Top3 set Jaccard: 0.8068
- R1/R2 within-race rank correlation: 0.9366

## R2와 PLC disagreement

| 기준 | Both correct | PLC only | R2 only | Both wrong | Oracle descriptive upper bound |
|---|---:|---:|---:|---:|---:|
| Top1 | 936 | 179 | 166 | 540 | 70.35% |
| Top3 any | 1,637 | 56 | 50 | 78 | 95.72% |

R1 대비 Top1 ranking-only 성공은 148→166, PLC-only는 154→179, both-wrong은
558→540으로 변했다. Top1 oracle descriptive upper bound는 69.36%→70.35%다.
Top3 ranking-only 성공은 52→50, PLC-only는 59→56, both-wrong은 76→78이며
oracle descriptive upper bound는 95.83%→95.72%다. 모두 descriptive이고 실제 ensemble
성능이 아니며 KEEP 판정에 사용하지 않았다.

## Feature importance

네 fold 평균 gain 상위 Feature는 다음과 같다. 이는 인과적 Feature 효과가 아니다.

1. `horse_recent3_race_relative_time_advantage_median` — gain 8207.79
2. `horse_same_meet_avg_finish_rank` — gain 3071.41
3. `jockey_same_meet_plc_hit_rate` — gain 2245.97
4. `jockey_prior_plc_hit_rate` — gain 2111.01
5. `carried_weight` — gain 1254.51
6. `horse_recent10_avg_finish_rank` — gain 1220.42
7. `horse_age` — gain 1035.79
8. `horse_recent3_race_time_percentile_median` — gain 990.95
9. `horse_recent3_avg_finish_rank` — gain 943.07
10. `horse_days_since_last_start` — gain 921.60

전체 gain/split importance는 branch-local `feature_importance.csv`에 저장했다.

## 확인된 사실

F3 10개를 한 묶음으로 제거한 R2는 봉인된 R1-relative KEEP 조건을 모두 만족했다.
F3 제거 후 평균 NDCG@3와 Recall@3는 개선됐지만 NDCG 개선 폭은 작고 fold 4에서는
큰 반대 방향 변화가 있었다. R2는 L133 Logistic ranking context보다 여전히 낮다.

## F3 중복 가설에 대한 판정

결과는 현재 200-tree LambdaRank procedure에서 F3 전체 제거가 R1보다 낫다는 가설을
지지한다. 그러나 개선이 작고 fold별 이질성이 있으므로 F3가 일반적으로 중복이거나 항상
해롭다고 결론내릴 수 없다. 개별 F3의 효과도 이 bundle ablation으로 식별되지 않는다.

## 아직 알 수 없는 것

개별 F3 중 무엇이 이득 또는 손실을 만들었는지, 다른 기간과 Validation에서도 작은 개선이
재현되는지, R2가 실제 ensemble에서 보완 가치를 만드는지는 알 수 없다. 이번 결과로 추가
Feature ablation, tuning, Validation 또는 ensemble 학습을 실행하지 않았다.

## 보호 및 artifact

- 공통 DB before/after SHA256:
  `0f760634f63e8c4f606688202e41b2513735eb8a1122b4d586f64fc075e89e01`
- R2 OOF SHA256:
  `d1c51b78ebf79ef3b4dc30457c7b36bab16a0a286dc9a20b0e54fc57b3d3a8c8`
- R2 result JSON SHA256:
  `7f8dce8dd336ec2ec39d69090bdb6f568f6abb87fdf04de9c434f4a45c04ce23`
- R1 contract/result/OOF 및 L133/T1/A1 보호 artifact 불변
- Validation 접근: 0
- 2024-07 이후 평가 접근: 0

모델, fold OOF, full OOF, metric, importance와 result는 branch-local
`data/exports/modeling/ranking_research_v1/ranking_r2_development_20260909`에 저장했다.
