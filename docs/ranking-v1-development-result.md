# Ranking v1 Development 결과

실행일: 2026-09-09  
판정: `DROP_RANKING_V1`

## 결론

봉인된 binary PLC LambdaRank v1은 동일 L133 Logistic 순위보다 primary인 경주별 macro
NDCG@3가 네 fold 모두 낮았다. 네 fold 동일 가중 평균 delta는 `-0.006880`
(`-1.287%`)이고, macro Recall@3 평균 delta도 `-0.007821`이었다. 사전 계약의 평균 개선,
3/4 fold 반복 개선, Recall 비악화 조건을 모두 충족하지 못해 `DROP_RANKING_V1`로 판정한다.

일부 경주에서 두 모델의 성공 여부가 달랐지만 이는 selector나 ensemble 성능이 아니다.
LambdaRank score와 경주 내 z-score에는 Log Loss/Brier를 적용하지 않았고 calibration도 하지 않았다.

## 실행 계약

- 구현 commit: `43893e8d0e82eb450b5258ab28a66fefe63a6484`
- 계약: `ranking_research_v1`, candidate `RANK_L133_PLC_LGBM_V1`
- Development: 28,392행, 2,675경주, `2023-01-01 <= race_date < 2024-07-01`
- OOF: 19,168행, 1,821경주, 기존 네 expanding temporal fold의 evaluation 행
- Input: L133 133개, hash
  `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`
- Relevance: official `place_hit` 0/1, gain `[0,1]`, query=`race_id`
- LightGBM 4.6.0, 200 rounds, seed 20260908, early stopping/tuning 없음
- Comparator: 각 fold Train에 적합한 raw L133 Logistic probability의 경주 내 내림차순

## Fold별 primary

| Fold | L133 NDCG@3 | LambdaRank NDCG@3 | Delta | Relative delta |
|---|---:|---:|---:|---:|
| 1 | 0.532925 | 0.519906 | -0.013018 | -2.443% |
| 2 | 0.537626 | 0.536462 | -0.001164 | -0.217% |
| 3 | 0.532731 | 0.522838 | -0.009893 | -1.857% |
| 4 | 0.534997 | 0.531554 | -0.003444 | -0.644% |
| 4-fold mean | 0.534570 | 0.527690 | -0.006880 | -1.287% |

Primary 개선 fold는 `0/4`다.

## Secondary 지표

| 지표, 네 fold 평균 | L133 | LambdaRank | Delta |
|---|---:|---:|---:|
| Macro Recall@3 | 0.511802 | 0.503981 | -0.007821 |
| Top1 PLC hit | 0.612025 | 0.608049 | -0.003976 |
| Top3 any PLC hit | 0.929753 | 0.925283 | -0.004470 |
| Mean PLC hits in Top3 | 1.534641 | 1.511326 | -0.023315 |

Recall@3는 fold 4에서만 개선했다. Top1 PLC는 fold 2에서 개선, fold 3에서 동률이었고,
Top3 any PLC 및 Top3 hit 수는 fold 2·4에서 일부 개선했다. 어느 secondary 결과도 primary
실패를 뒤집지 않는다.

## L133 재현

기존 F1+F3 Development 결과의 raw Logistic Macro Log Loss/Brier와 같은 환경·fold에서
재계산한 값의 최대 절대차는 `2.78e-16`이었다. 8개 비교가 모두 `1e-12` 이내다.
이 검사는 comparator 재현성 확인이며 LambdaRank score에 probability loss를 적용한 것이 아니다.

## OOF 무결성

- Ranking OOF 19,168행, PLC OOF 19,168행, 1,821경주
- `(race_id, horse_id, race_date, fold_id)` full outer join coverage 100%
- 중복키 0, 결측 prediction 0, serialized OOF 재로딩·validator 통과
- 경주별 rank 1..N 연속, 높은 score/probability가 rank 1
- raw score, rank, within-race z-score, model/source/snapshot/code/config/contract provenance 보존
- 네 fold model 모두 정확히 200 trees

주 산출물은
`data/exports/modeling/ranking_research_v1/ranking_v1_development_20260909/`에 있다.
`ranking_oof.csv`, `plc_oof.csv`, `oof_targets.csv`, fold별 OOF, 모델, fold/race metric,
disagreement와 preflight/result JSON을 포함한다. 총 32개 파일이며 약 50.0 MB다.

## Disagreement와 선택 일치도

Top1 PLC 기준:

| 분류 | 경주 | 비율 |
|---|---:|---:|
| 둘 다 성공 | 961 | 52.77% |
| PLC만 성공 | 154 | 8.46% |
| Ranking만 성공 | 148 | 8.13% |
| 둘 다 실패 | 558 | 30.64% |

Top3 any PLC 기준:

| 분류 | 경주 | 비율 |
|---|---:|---:|
| 둘 다 성공 | 1,634 | 89.73% |
| PLC만 성공 | 59 | 3.24% |
| Ranking만 성공 | 52 | 2.86% |
| 둘 다 실패 | 76 | 4.17% |

- Top1 같은 말 선택률: 68.75%
- Top3 평균 교집합: 2.421두
- Top3 평균 Jaccard: 0.7227
- Top3 동일 집합률: 48.16%
- 경주 내 deterministic rank Spearman 평균: 0.8721
- Top1 oracle descriptive upper bound: 69.36%
- Top3 any PLC oracle descriptive upper bound: 95.83%

Oracle 값은 두 결과 중 맞은 쪽을 사후에 아는 상한 진단이며 달성 가능한 ensemble 성능이 아니다.
Ranking-only 경주가 존재한다는 사실만으로 학습 가능한 selector가 존재한다고 결론내릴 수 없다.

## Legacy 참고 제한

legacy finish-order LambdaRank의 NDCG@1 0.4118, NDCG@3 0.5158, winner hit 27.76%,
Top3 winner inclusion 58.66%는 저장 코드/산출물로 확인된 참고치다. 현재 실험은 기간, 모집단,
133개 Feature, binary PLC relevance, preprocessing과 평가 계약이 달라 직접 우열 비교가 불가능하다.

## 보호 및 검증

공통 DB SHA256은 전후 모두
`0f760634f63e8c4f606688202e41b2513735eb8a1122b4d586f64fc075e89e01`이다.
계약·L133/T1/RA1/H133/HGB·Validation ledger/model JSON/joblib의 보호 hash도 동일했다.
공통 DB write, Validation 접근, 2024-07 이후 평가, tuning, calibration, ensemble 학습은 0건이다.

관련 Pytest 31개 통과, Ruff 통과, mypy 40개 source 통과, `git diff --check` 통과.
전체 repository Pytest는 98 passed / 기존 export 누락 2 failed였고, 전체 Ruff에는 기존
notebook 오류 8건이 남았다. 이전 구현 감사에서 확인한 환경 제한이며 이번 결과 산출물로
보정하지 않았다.

## 해석 경계

확인된 사실은 고정 v1 후보가 동일 fold의 raw L133보다 primary와 평균 Recall에서 낮았고,
완전한 OOF에 보완 사례가 일부 존재했다는 것이다.

Ranking v1 가설은 사전 규칙에 따라 기각한다. 이는 binary PLC relevance, 고정 L133 입력,
고정 LambdaRank 설정으로 정의한 첫 후보에 대한 판정이며 모든 ranking family의 부정이 아니다.

Ensemble에 대해서는 ranking-only 사례가 시점 전에 식별 가능한지, 독립 meta split에서 실제로
일반화하는지, weighted/stacking 방식이 L133을 이기는지 아직 알 수 없다. 이번 OOF는 그 후속
연구의 join-ready 입력이지만 `DROP_RANKING_V1` 후보를 자동 승격할 근거는 아니다.

Commit Summary (제안만): `experiment: evaluate ranking v1 on Development folds`

Commit Description (제안만): Execute the sealed four-fold binary PLC LambdaRank candidate against
same-fold raw L133, persist validated branch-local OOF and model artifacts, apply the frozen
KEEP/DROP rule, and document disagreement diagnostics without tuning, calibration, Validation access,
shared-data writes, or ensemble training.
