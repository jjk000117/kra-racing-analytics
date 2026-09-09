# Ranking R2 F3-ablation 설계 감사

작성일: 2026-09-09  
상태: `SEALED_DESIGN_ONLY` — R2 학습·예측·OOF·성능 계산 미실행

## 결론

R2는 `R1 LambdaRank + L133`에서 F3 current-field relative Feature 10개만 제거한
`LambdaRank + L123_NO_F3` 단일 후보로 제한한다. F1 6개, 모델, relevance, group,
전처리, 모집단, fold와 평가 규칙은 모두 유지한다. 이 설계는 hyperparameter tuning이 아니라
F3 representation의 LambdaRank 내부 추가가치를 격리하는 controlled ablation이다.

R2가 R1을 이겨도 raw L133 Logistic보다 낮다면 해석은 “F3 제거가 이 LambdaRank procedure에는
도움이 됐지만 ranking이 PLC 기준선을 대체하지는 못했다”로 제한한다.

## Ranking v1 결과 보호

- 결과 commit: `215c2b3b7c3f1cc1be5f0ea1c5e23e70863d7243`
- commit 직후 ranking worktree: clean
- R1 판정: `DROP_RANKING_V1`
- R1 OOF SHA256:
  `6eae0d8844f831c78ab418a6826bf76d135d932d928a1f57cb9993cc78f8439e`
- R1 result JSON SHA256:
  `e7f0a3ce34954deb5c41b273ff12a94b95ca1c1668b1f144cf563c4a6b2a17a1`
- main에는 기존 untracked 분석 산출물이 있었고, plc-dev에는 접근 불가 pytest 임시 경로
  경고가 있었으며, ensemble은 clean이었다. 이번 설계 감사에서는 세 worktree 모두 수정하지 않았다.
- 공통 DB, R1 artifact, Validation ledger 및 L133/T1/A1 보호 대상을 쓰지 않았다.

## 실제 F3 10개

다음 순서는 `src/kra_analytics/feature_bundles.py:F3_FEATURES`,
`docs/post-baseline-v2-feature-bundle-registry.csv`, 봉인된 L133 feature order에서 일치한다.

1. `rating_field_percentile`
2. `carried_weight_vs_field_median_kg`
3. `horse_prior_plc_hit_rate_field_percentile`
4. `horse_recent5_plc_hit_rate_field_percentile`
5. `horse_same_distance_plc_hit_rate_field_percentile`
6. `jockey_recent10_plc_hit_rate_field_percentile`
7. `trainer_recent10_plc_hit_rate_field_percentile`
8. `horse_recent5_s1f_field_percentile`
9. `horse_recent5_g3f_field_percentile`
10. `horse_recent5_g1f_field_percentile`

## R2 Feature 계약

- Derivation: 봉인된 L133 이름·순서를 유지하면서 위 F3 10개만 제거
- Count: 123개, unique 123개
- Hash 방식: ordered name을 newline으로 결합하고 마지막 newline을 붙인 UTF-8 SHA256
- R2 hash: `0b0c545fb5a2135cbd4b8362e3c7bd72231f05b43dbfdfaccec64198dc3469cc`
- F1 6개 유지, F3 0개, T1 추가 없음

F1은 과거 경주 안에서 산출한 상대 성과를 말의 historical history로 집약한다. 현재 경주의
상대 구성과 무관하게 과거 정보의 표현으로 남는다. F3는 오늘 경주의 출전마 집합을 분모로
각 말의 rating, 부담중량, 과거 PLC rate와 sectional을 다시 상대화한다. 질문이
“현재 field-relative context가 ranking objective에 필요한가”이므로 F1을 제거하면 다른
가설까지 동시에 바뀐다.

## LambdaRank와 F3의 이론적 관계

LambdaRank objective는 같은 race group 안의 positive/negative score ordering에 gradient를
만든다. 이것만으로 각 행의 absolute rating이 오늘 field의 어느 percentile인지 자동으로
계산하지 않는다. 모델은 group boundary를 손실 계산에 사용하지만 다른 runner의 Feature
distribution을 새 input으로 제공받지는 않는다.

따라서 F3는 추가 정보일 수 있다. 예를 들어 동일 rating 70이라도 강한 field와 약한 field에서
의미가 다르고, field percentile은 이 조건부 위치를 한 행에 명시한다. Tree split은 전역 threshold를
사용하므로 이러한 정규화가 race 간 scale 차이를 줄여 줄 가능성이 있다.

반대로 F3는 해당 absolute source와 강하게 관련된 파생값이다. 현재 L133에는 rating, 부담중량,
PLC rate와 sectional level/count도 남아 있어 tree가 유사한 구분을 반복하거나 제한된 200 trees를
상관된 split에 사용할 수 있다. 작은 field의 percentile 이산화, tied/missing source, field composition
변동이 노이즈를 추가할 수도 있다. Tree boosting의 상관 Feature는 선형모델의 exact collinearity와
같은 식별 불능을 만들지는 않지만 split 선택을 분산시키거나 불안정하게 만들 수 있다.

F3 제거 후 absolute value만으로 충분할 가능성도 있으나, absolute value만으로 상대 위치를 완전히
복원하려면 모델이 race condition과 경쟁자 distribution의 관계를 간접적으로 학습해야 한다.
R2 결과 전에는 추가 정보, 중복, 방해 중 어느 설명도 확인된 사실이 아니다.

## 단일 변경 계약

| 항목 | R1 | R2 |
|---|---|---|
| Model | LightGBM 4.6.0 LambdaRank | 동일 |
| Config hash | `3b30a1f7…c24f2` | 동일 |
| Relevance/gain | place_hit 0/1, `[0,1]` | 동일 |
| Query | race_id | 동일 |
| Population/folds | 28,392행·2,675경주, 4 folds | 동일 |
| Feature | L133 | L123_NO_F3 |
| Feature hash | `18297f13…da182` | `0b0c545f…3469cc` |
| Preprocessing | fold-Train OHE/median/count0/scaling | 동일 절차에서 F3 열만 없음 |
| Rounds/seed | 200 / 20260908 | 동일 |
| Early stopping/tuning | 없음 | 없음 |

F3 10개는 모두 numeric 파생 Feature다. 따라서 categorical 11개와 category learning scope는
변하지 않는다. numeric source는 122개에서 112개로 줄며, 기존 count-zero 목록도 그대로다.
각 fold의 OHE category 수는 Train으로 결정되므로 R1과 같아야 하고, transformed width는 R1보다
정확히 10 작아야 한다. 이는 R2 실행 전 구조 assert 대상이며 이번 설계 단계에서 새 전처리나
모델을 적합하지 않았다.

## Metric과 판정

Primary는 R1과 같은 race-macro binary PLC NDCG@3다. 비교 기준은 L133 Logistic이 아니라
동일 LambdaRank procedure의 R1이다. 각 fold에서 `R2 - R1`을 계산하고 네 fold를 동일 가중 평균한다.

Secondary는 Macro Recall@3, Top1 PLC hit, Top3 any PLC hit, mean PLC hits in Top3다.
L133 Logistic은 R2가 최종 PLC 기준선을 넘는지 보여주는 secondary context로만 유지한다.

`KEEP_F3_REMOVAL`은 다음 세 조건을 모두 만족해야 한다.

1. R2의 네 fold 평균 NDCG@3가 R1보다 `1e-12` 초과 개선
2. 최소 3/4 fold에서 R2 NDCG@3가 R1보다 `1e-12` 초과 개선
3. R2의 평균 Macro Recall@3 delta가 R1 대비 `-1e-12` 이상

유효한 실행에서 하나라도 실패하면 `DROP_F3_REMOVAL`이다. Feature/hash, PIT, population, fold,
group, OOF, environment 또는 보호 계약이 깨지면 성능 판정 대신 `INVALID`다. Secondary 및
disagreement는 primary 실패를 뒤집을 수 없고 실행 후 규칙을 바꾸지 않는다.

## OOF와 disagreement 준비

R2 OOF는 R1과 같은 `(race_id, horse_id, race_date, fold_id)` key 및
`ranking_raw_score`, `ranking_within_race_rank`, `ranking_normalized_score`를 사용한다.
R1/R2/PLC를 full outer one-to-one join하고 coverage 100%, 중복·결측 0, fold/date와 rank
연속성을 요구한다. R2 provenance에는 R2 Feature list/hash, 동일 model config hash, source DB,
snapshot, environment, code와 contract hash를 기록한다.

실행 후 descriptive 분석은 R1-R2 Top1/Top3 선택 일치, R2-PLC disagreement, ranking-only 성공
증감과 oracle descriptive upper bound를 포함할 수 있다. Oracle은 selector 성능이 아니며
NDCG 판정에 사용하지 않는다.

## Blocker와 다음 단계

데이터나 dependency blocker는 현재 없다. 구현 전 필요한 최소 작업은 R2 derived contract loader,
F3 정확 제거/hash assert, transformed width -10 assert, R1 OOF read-only comparator와 R2 artifact
경로 분리다. R1 artifact를 덮어쓰지 않고 새 run directory를 사용해야 한다.

이번 단계에서는 R2 코드, 모델 fit, prediction, OOF, 성능 metric, disagreement, tuning, calibration,
ensemble, Validation, payout/ROI를 실행하지 않았다.

## 사실·가설·검증 질문

### 확인된 사실

F3는 repository에서 확인된 위 10개이고, 이를 L133에서 순서 보존 제거하면 123개와 hash
`0b0c545f…3469cc`가 된다. F1은 모두 유지되고 F3는 모두 제거된다. R1은 commit `215c2b3`에서
`DROP_RANKING_V1`로 봉인되어 있다.

### F3 중복에 대한 미검증 가설

F3가 LambdaRank에서 유용한 field context일 수도 있고, absolute source와 중복되어 제한된 tree
capacity를 분산시키거나 noisy percentile로 학습을 방해할 수도 있다. Objective가 race-relative라는
사실만으로 F3 중복은 증명되지 않는다.

### R2 실험에서 검증할 질문

F3만 제거했을 때 R2가 R1 NDCG@3를 평균 및 3/4 fold에서 개선하는가? 평균 Recall@3 guardrail을
지키는가? 개선하더라도 raw L133 Logistic 기준선까지 회복하는가? R1/R2 selection과 R2-PLC
ranking-only 구조는 어떻게 변하는가?

Commit Summary (제안만): `docs: seal Ranking R2 F3 ablation contract`

Commit Description (제안만): Seal a controlled R2 ablation that removes only the ten current-field
relative F3 features from L133 while preserving F1, the binary PLC LambdaRank configuration,
Development population, folds, preprocessing, metrics, OOF schema, and strict R1-relative decision
rules without training R2 or accessing Validation.
