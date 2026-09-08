# Ranking research v1 — 데이터 접근 감사 및 사전 봉인

작성일: 2026-09-08. 상태: SEALED_DESIGN_ONLY. 이 문서가 첫 ranking 실험의 규범 계약이다.
모델 구현·학습·예측·OOF·튜닝은 실행하지 않았다. 계약 변경은 실행 전에 새 버전으로 기록한다.

## 1. 환경/Git 감사

- 작업 root: `C:/Users/jjk00/Documents/GitHub/kra-racing-analytics-ranking`
- branch: `ranking-dev`
- 시작 HEAD: `ef6a38a8337cdbb4d91ce7e56514deeab3464b67`
- 시작 `git status --short`: 출력 없음(clean). 종료 변경은 이 문서 및 continuity 문서 3개뿐이다.
- 다른 KRA worktree 및 read-only reference `horse_racing`에는 파일을 쓰지 않는다.
- Commit/Push 금지. 공통 데이터, Snapshot, PIT, L133 hash, T1, Validation 계약/ledger,
  PROMOTE, HGB/H133/RA1 결과를 수정하지 않는다.

## 2. 공통 DB와 read-only 접근

공통 source: `C:/Users/jjk00/Documents/GitHub/kra-racing-analytics/data/warehouse/kra.duckdb`.
실제 Python 3.12.13, DuckDB 1.5.5에서 `duckdb.connect(path, read_only=True)` 성공.
사용한 실행기는 `C:/Users/jjk00/anaconda3/envs/kra-racing-analytics/python.exe`이며 `-B`로 실행했다.
시작 프로세스의 `KRA_DATABASE_PATH`, `KRA_PROJECT_ROOT`는 모두 unset이다.
현재 root의 기본 DB는 `data/warehouse/kra.duckdb`로 resolve되지만 파일은 없다.
이 worktree에는 `.env.example`만 있고 DB/Raw/export가 자동 복제되어 있지 않다.
main `.env`의 비밀값은 읽지 않았다. `.env` 자동 로드는 일부 collector에만 있어 분석 경로에서
환경설정이 자동 적용된다고 가정하면 안 된다.

근거: `src/kra_analytics/paths.py`, `database.py`, `development_evaluation.py`,
`feature_bundle_experiment.py`. `connect_database` 기본값은 read-write이므로 반드시
명시적으로 `read_only=True`를 지정한다. 환경변수를 main DB로 전역 설정한 상태로 build/init
명령을 실행하면 위험하다. 다음 구현에서는 source 절대경로를 별도 인자로 받아 read-only로 열고,
output은 ranking root로 고정한다. 기존 build/init/collector를 실행하지 않는다.

읽은 Snapshot은 `mart.place_feature_snapshot_v2_engineered_candidate`.
현재 전체 테이블 재빌드 없이 Development 범위 SELECT로 133개를 투영할 수 있다.
기본 development loader는 base Snapshot을 쓰므로 L133용 engineered loader의 패턴을 재사용해야 한다.
현재 Feature loader는 F2까지 읽으므로 다음 ranking loader에서는 봉인된 133개만 명시한다.

## 3. Branch-local output 구조

후속 실행 전용 경로(이번에는 생성 안 함):

- `data/exports/modeling/ranking_research_v1/<run_id>/`: OOF CSV, metrics, manifest, exclusions, model files
- 선택적 `data/warehouse/ranking_research_v1.duckdb`: ranking 전용 DB

`ProjectPaths.root`는 ranking root를 명시하고 source database만 분리한다. source/output의
resolve된 절대경로가 같으면 실패하며, output이 ranking root 밖이면 실패한다. junction/symlink도
해결해 검사한다. CSV/JSON/model은 위 export 아래에만 쓴다. 기존 `.gitignore`가 두 경로를 보호한다.
Source에 candidate table을 생성하지 않는다. main DB attach-write, init, migration도 금지한다.
DB lock이 발생하면 read-write 재시도나 공통 DB 복사로 우회하지 않고 중단한다.
문서 저장은 성공했지만 실제 artifact writer/branch DB 생성은 다음 단계의 검증 대상이다.

## 4. Legacy 코드·artifact로 확인된 사실

현재 KRA src/docs에는 legacy LambdaRank 구현이 없다. 별도 read-only `horse_racing`에서 확인했다:

- `scripts/build_task024_ranking_dataset.R`: finish 1~5를 relevance 5~1, 6착 이하 0으로 매핑;
  group=race_id, 최소 2두, race split 무결성 검사.
- `scripts/train_task025_lightgbm_ranker.R`: LightGBM R API, lambdarank, gbdt,
  label_gain=[0,1,3,7,15,31], 경주별 contiguous group sizes. 비선형 tree boosting.
- `reports/task025/test_metrics.csv`: NDCG@1=0.411798323596647,
  NDCG@3=0.515819655797381, winner_hit_rate=0.27755905511811.
- `reports/task029/model_comparison.csv`: original test top3_accuracy=0.586614173228346.
- `scripts/train_task029_lightgbm_ranker.R:extended_metrics`: Top3는 예측 상위 3두에
  공식 1착마가 하나라도 포함되는 비율이다. PLC hit/Recall@3/Top1의 3착 이내 비율이 아니다.

이는 저장된 코드·산출물의 확인이며 모델 재학습·재현 검증은 아니다. 현재 PLC와 데이터 기간,
population, features, relevance가 달라 수치를 직접 비교할 수 없다. legacy parameter를 복사하지 않는다.

## 5. Legacy reference만으로 알려진 내용과 감사 한계

`horse_racing/docs/modeling-methodology.md`의 122-feature 고정, 당시 실행 chronology,
선택 후 Test 평가 서술은 문서 근거이며 이번에 전체 실행 lineage/serialized booster를 검증하지 않았다.
사용자가 제공한 4개 성능값은 이제 위 CSV로 근거가 있으므로 미확인 수치로 분류하지 않는다.
대학 프로젝트라는 배경 자체는 사용자 설명이다.
초기 legacy 검색이 JSON Raw까지 확장되어 대량 결과가 반환된 검색 범위 오류가 있었다.
이후 scripts/docs/reports로 한정했다. 노출된 legacy Raw는 분석·선택에 사용하지 않았다.
KRA DB의 Validation/2024-07 이후 행, prediction artifact는 조회하지 않았다.
기존 KRA continuity/계약 문서에 이미 기록된 과거 결과는 설계 배경으로 읽었으며 새 평가가 아니다.

## 6. PLC와 ranking 질문

PLC: 한 행=출전마, 공식 `place_hit` 확률, Logistic, 대표 L133+sigmoid.
T1은 raw Logistic의 Development에서 KEEP이며 LT1의 official 승격을 의미하지 않는다.
Ranking: 동일 PIT-safe 정보에서 경주 안의 PLC positive를 negative보다 높게 배치하는
비선형 race-group 절차가 유용한 추가 순위 신호를 주는지 검증한다.
Raw score는 probability가 아니며 합이 1이 될 필요도 없다. raw score에 LL/Brier 적용 금지.
첫 실험은 target/feature를 맞추지만 model family와 objective가 함께 달라진다.
따라서 차이를 objective 하나의 인과효과로 주장하지 않는다. 별도 binary GBDT 비교는 후속 계약이다.

## 7. Relevance 후보 비교

| 후보 | 장점 | 제한 | 첫 실험 |
|---|---|---|---|
| A finish-order | 전체 유효 착순의 우열을 사용 가능; legacy 연결 | PLC와 target 차이, 동착/비완주 처리 추가; legacy 5단계도 6착 이하를 구분 못 함 | 보류 |
| B PLC-oriented 0/1 | 공식 target·모집단 일치, positive 내부 임의 우열 없음 | winner/positive 내부 순서를 직접 배우지 않음 | 선택 |
| C hybrid | PLC 우선 및 finish 세부 우열 결합 | 두 gain 스케일·비완주·동착 규칙 추가, 연구 질문 혼합 | 제외 |

A의 후속 예시는 유효 finish 1~16에 17-rank, 비완주 0이며 실제 채택 계약이 아니다.
Hybrid 예시는 PLC bonus가 모든 finish gain 차이보다 크게 설계되어야 하지만 이번에는 수치화하지 않는다.

## 8. 첫 relevance 봉인

`RANK_L133_PLC_LGBM_V1`: relevance=`int(place_hit)` (0 또는 1), label_gain=[0,1].
공식 PLC 양성끼리 같은 relevance, 음성끼리 같은 relevance. finish로 tie를 깨거나 positive를 재서열화하지 않는다.
결과는 supervised target 영역에서 허용되지만 Feature 영역에는 금지한다.

## 9. 첫 Feature 계약

L133 133개를 선택한다. `docs/post-baseline-v2-improvement-validation-contract.json`의
candidate.feature_order 이름·순서 그대로, hash
`18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`.
Hash 방식은 newline join 후 마지막 newline을 붙인 UTF-8 SHA256이다.
LT1 137개는 유망하지만 T1 효과까지 혼합하므로 후속으로 남긴다.
Absolute subset은 현재 상대 baseline의 정보를 제거하므로 첫 공정 비교가 아니다.
F3 10개만 제거해도 F1의 historical relative 정보는 남는다. absolute subset=123개라고 단정하지 않는다.

## 10. F3 중복과 RA1 해석

F3는 현재 field 구성에 대한 명시적 상대 Feature다. Ranking loss의 group은 gradient 비교 범위를
정할 뿐 inference 시 다른 말의 Feature를 자동으로 입력하지 않는다. 따라서 F3가 수학적으로
불필요하다고 결론낼 수 없다. redundancy/interaction은 미검증 가설이다.
F1은 과거 event의 상대시간 정보로 현재 field-relative F3와 구분한다.
RA1은 same-133 linear pairwise에서 NDCG@3 +0.000348, Recall@3 -0.000271,
확률 손실 전 fold 악화로 DROP_RACE_AWARE였다. 모든 ranking family 실패의 증거는 아니다.
첫 실험에서 F3 제거, T1 추가, relevance grid를 수행하지 않는다.

## 11. Query/population/status

query=race_id; 한 경주를 하나의 contiguous block으로 정렬한다.
입력 정렬은 race_date,race_id,horse_id 오름차순; group 벡터는 해당 순서의 실제 행 수이고
sum(group)=len(X)=len(y). race_id/horse_id/date/status/finish/target은 Feature가 아니다.
최소 runner=3; 미만이면 경주 전체 제외하고 양 모델 모두 동일 모집단으로 비교한다.
단일 relevance 경주는 train에서 제외하고 사유 기록, eval에는 유지한다. 양성 0인 경주의
NDCG/Recall은 NA로 보고하고 primary 비교는 사전 계약 불충족(INVALID), 유리하게 조용히 제외하지 않는다.

Snapshot의 완료·공식 PLC·valid-start proxy 모집단을 그대로 승계한다.
DNS는 행 제외, DNS 존재만으로 경주 제외하지 않는다. 취소/미확정 경주 및 미해결 상태가
포함된 경주는 기존 정책대로 제외한다. 실격/주행중지는 valid-start이면 유지하고 공식 PLC
target을 쓴다. 결측 finish를 0착으로 만들지 않는다. 비완주의 NULL finish는 허용;
FINISHED인데 유효 finish 결측/범위 위반이면 경주 계약 위반으로 실행을 중단한다.
동착 공식 PLC 양성은 모두 보존한다. rank 1 동착은 winner metric에서 모두 winner다.
`status-code-policy.md`의 초기 91/92 이름보다 현재 Snapshot/Canonical의 실제 세분 상태를 따른다.

공식 PLC source는 `canonical.winning_payout(pool_code='PLC')`이며 Snapshot의 감사된 place_hit을 재사용한다.
finish source는 `canonical.runner_result.official_finish_rank`; race_id+horse_id로 1:1 join한다.
PLC join은 원래 race_id+gate_no이며 두수로 양성 기준을 재계산하지 않는다. 배당 금액은 읽지 않는다.
현재경주 status는 target/population 감사에만 쓰며 사전 출전표 복원이라는 운영 한계는 남는다.

실제 Development 감사: 28,392행/2,675경주, 2023-01-06~2024-06-30,
중복키 0, canonical join 미결합 0, runner 7~16, PLC positive 2~4,
단일 relevance/3두 미만 0, target NULL 0, invalid-start 0.
FINISHED 28,318; RACE_STOPPED 73; DISQUALIFIED 1. 유효 finish 범위/결측 위반 0.
새 full population 재감사가 아니라 상속 계약 위의 ranking-specific 접근/결합 검사다.

재현 SQL의 모든 데이터 쿼리는 아래 범위에서만 수행했다(연결 read_only=True):

```sql
SELECT s.race_id, s.horse_id, s.race_date, s.place_hit,
       s.result_status, s.is_valid_start, r.official_finish_rank, r.is_valid_finish
FROM mart.place_feature_snapshot_v2_engineered_candidate s
LEFT JOIN canonical.runner_result r USING (race_id, horse_id)
WHERE s.race_date >= DATE '2023-01-01' AND s.race_date < DATE '2024-07-01';
```

실제 감사는 위 join/window의 count, distinct key, 상태별 count, group별 n/positive min/max
집계로 수행했다. Snapshot/canonical DESCRIBE는 schema 확인이며 평가 행 조회가 아니다.

## 12. Temporal fold

`src/kra_analytics/development_evaluation.py:DEVELOPMENT_FOLDS` 그대로 사용한다.

| Fold | Train [start,end) | Eval [start,end) | 기존 Train/Eval 행 | 기존 Eval 경주 |
|---|---|---|---:|---:|
| 1 | 2023-01-01,2023-07-01 | 2023-07-01,2023-10-01 | 9224/4458 | 427 |
| 2 | 2023-01-01,2023-10-01 | 2023-10-01,2024-01-01 | 13682/5229 | 494 |
| 3 | 2023-01-01,2024-01-01 | 2024-01-01,2024-04-01 | 18911/4707 | 432 |
| 4 | 2023-01-01,2024-04-01 | 2024-04-01,2024-07-01 | 23618/4774 | 468 |

기존 fold 건수는 T1/RA1 결과 문서 근거이며 이번에 fold 재학습하지 않았다.
Train은 과거, eval은 이후, race/date 일관성·교집합 0을 실행 전 assert한다.
2022는 inherited historical warm-up만; 모델 fit은 2023부터.
OOF coverage는 2023-07~2024-06의 19,168행/1,821경주이며 2023-H1은 OOF가 없다.
2024-07 이후 SQL/평가/selection 금지. SQL 전 window guard 및 반환 날짜 assert를 모두 둔다.

## 13. Metric 봉인

유일 primary: race-macro binary PLC NDCG@3. gain=y, discount=1/log2(position+1),
DCG@k를 동일 경주의 relevance 내림차순 IDCG@k로 나눈다. finish gain NDCG와 섞지 않는다.
각 fold에서 경주 동일 가중 평균, decision은 네 fold 평균 delta를 동일 가중으로 사용한다.
전체 pooled OOF race 평균은 별도 descriptive 값이다.

Secondary(각 경주 계산 후 macro, micro는 별도 이름):

- binary NDCG@1 (이 계약에서는 Top1 PLC hit와 같은 값)
- Recall@3 = Top3 PLC hits / 해당 경주 전체 PLC positives; micro는 전체 hits/전체 positives
- Top1 winner hit = 예측 첫 말의 유효 공식 finish=1
- Top1 PLC hit = 첫 말의 place_hit
- Top3 any PLC hit = Top3 중 양성 하나 이상
- Mean PLC hits in Top3 = 경주별 Top3 양성 수 평균

score 내림차순, 완전히 같은 score는 horse_id 문자열 오름차순(ordinal, 선행 0 보존)으로
결정론적으로 선택한다. target/finish/gate를 tie-break에 쓰지 않는다.
NDCG 구현도 같은 tie 순서를 쓰며 sklearn 기본 tie averaging과 혼합하지 않는다.
NaN/Inf score는 실패. 위 schema에서 n>=3이므로 Top3는 정확히 3두.
LL/Brier/calibration 성능은 이번 ranker의 metric이 아니다.

## 14. 첫 LightGBM candidate

현재 pyproject/environment.yml에 lightgbm이 없고 전용 Conda 및 bundled Python에서도 미설치다.
다음 구현 환경에서 `lightgbm==4.6.0`을 고정하고 버전/플랫폼/전체 resolved parameter를 manifest에 기록한다.
이번에 설치하지 않았다. 아래 수치는 검증 전 보수적 설계 선택이며 legacy 복사가 아니다.

LGBMRanker: objective=lambdarank, boosting_type=gbdt, n_estimators=200,
learning_rate=0.03, num_leaves=15, max_depth=4, min_child_samples=50,
min_child_weight=0.001, min_split_gain=0, reg_alpha=0, reg_lambda=1,
subsample=1, subsample_freq=0, colsample_bytree=1, max_bin=255,
random_state=20260908, data_random_seed=20260908, feature_fraction_seed=20260908,
bagging_seed=20260908, n_jobs=1, deterministic=true, force_col_wise=true,
device_type=cpu, label_gain=[0,1], lambdarank_truncation_level=6,
lambdarank_norm=true, sigmoid=1, metric=ndcg, eval_at=[3].
추가 sample/class weight 없음. Lambda normalization은 정확한 경주별 동일 weight 보장과 다르다.
고정 200 tree, early stopping 없음, outer eval을 fit callback/선택에 사용하지 않음.
truncation=6은 @3보다 여유를 둔 고정 설계이며 튜닝하지 않는다.

전처리는 공정한 첫 representation 비교를 위해 기존 L133 pipeline의 preprocessor를 그대로
각 fold Train에만 fit한다: 범주 최빈값+OneHotEncoder(handle_unknown=ignore), 일반 수치 median,
기존 count 계약 NULL→0, StandardScaler. target encoding/native categorical/새 missing indicator 없음.
133은 원본 Feature 수이고 OHE 후 차원은 별도 기록한다. LGBM의 categorical_feature=[]로
수치 OHE 행렬을 입력한다. 기존 변환 결과의 sparse/dense 형태를 기록하고 sparse implicit 0은
0으로 처리(zero_as_missing=false), use_missing=true. 새 library native missing 처리는 첫 비교에서
추가로 탐색하지 않는다. 전체 결측 열 처리는 기존 preprocessor 의미 그대로, 변환 열 목록 저장.
학습 group은 pipeline 자동 전달을 가정하지 않고 transform 후 ranker.fit(X,y,group=sizes)로 전달한다.

API 근거: [LGBMRanker 4.6.0](https://lightgbm.readthedocs.io/en/v4.6.0/pythonapi/lightgbm.LGBMRanker.html),
[Parameters 4.6.0](https://lightgbm.readthedocs.io/en/v4.6.0/Parameters.html).
향후 확률이 필요하면 outer Train 내부 temporal OOF로 calibration mapping을 별도 봉인한다.
현재 raw score에 단순 sigmoid/softmax를 적용해 calibrated probability라고 부르지 않는다.

## 15. OOF schema (미생성)

`oof_predictions.csv` UTF-8, 한 candidate/run 내 (race_id,horse_id,race_date) 유일:

| 컬럼 | 타입/규칙 |
|---|---|
| race_id, horse_id | string, source 원문 그대로, null 금지, 선행 0 보존 |
| race_date | ISO YYYY-MM-DD |
| fold_id, run_id, candidate_id, contract_version | string |
| ranking_raw_score | float64, finite, 높은 값 우선 |
| within_race_rank | int32, 1..n, 위 tie-break로 unique |
| within_race_normalized_score | float64, (score-race_mean)/population_std(ddof=0); std=0이면 0 |
| runner_count | int32 |

normalized score는 확률이 아니며 fold 간 raw scale 동일성도 보장하지 않는다.
`oof_targets.csv`에 같은 키+place_hit(bool)+official_finish_rank(nullable int)+result_status,
snapshot_id/source provenance를 분리한다. calibrated_probability 컬럼은 첫 버전에 없음.
`run_manifest.json`: source absolute path, scoped snapshot content/key hash, feature list/hash,
계약 파일 SHA256, code HEAD+dirty diff hash, library versions, parameter 전체, fold 경계,
preprocessor/model hash, SQL/window, exclusions/coverage, comparator artifact hash.
`models/fold_N.*`, `fold_metrics.csv`, `race_metrics.csv`, `population_exclusions.csv`도 branch-local.
OOF는 outer eval만. Train fitted score나 최초 H1 행을 OOF로 채우지 않는다.

PLC OOF도 string 키로 읽고 one-to-one full outer join해 누락/중복/date/fold/target 불일치가 0이어야 한다.
교집합만 조용히 쓰지 않는다. 현재 RA1 export 코드에는 horse-level OOF 저장이 없어 기존 정확한
PLC OOF artifact 가용성은 확인되지 않았다. 다음 구현 시 동일 outer fold L133 raw comparator를
branch-local로 생성하거나 provenance가 맞는 기존 artifact를 검증해야 한다. 전체 Development로
fit된 official model이나 Validation prediction은 comparator로 사용할 수 없다.
Primary comparator는 기존 raw L133 절차의 outer OOF 순위이다. 대표 L133+sigmoid는 별도 구분:
양의 기울기 sigmoid는 순위를 보존하지만 기존 calibration/rounding/ties를 감사하지 않고 같다고
가정하지 않는다. 확률 비교가 없으므로 첫 순위 benchmark에 sigmoid를 새로 선택하지 않는다.

## 16. Disagreement 재현 구조

동일 complete race에서 PLC와 ranker를 각각 score 정렬하여 Top1/Top3를 재현한다.
Top1 PLC hit 기준 2x2를 기본으로 두고 Top3 any PLC hit 기준 2x2를 별도로 저장한다:
both_hit, plc_only, ranking_only, neither. winner 기준은 별도 이름을 쓰며 합쳐 해석하지 않는다.
경주별 선택 horse_id, Top3 집합 overlap/Jaccard, rank correlation과 PLC hits 수를 함께 보존한다.
Horse raw score를 버리지 않아 후속 weighted ensemble/stacking이 가능하다. weight 학습/stacking은
meta-level temporal split을 별도 봉인해야 하며 같은 OOF 행으로 fit/평가해 성능을 주장하지 않는다.

## 17. KEEP/DROP 사전 기준

delta=ranker-primary minus raw-L133-primary, 비교 부동소수 tolerance=1e-12.

- INVALID/BLOCKED: 데이터/PIT/키/group/date/hash/OOF 계약 위반, library 설치 실패,
  재현 불가 또는 comparator 누락. 성능 DROP과 구분하고 tuning하지 않는다.
- KEEP_RANKING_RESEARCH: 네 fold 평균 primary delta > 1e-12이고 적어도 3/4 fold에서
  primary delta > 1e-12. 추가로 평균 macro Recall@3 delta >= -1e-12를 PLC coverage guardrail로 요구한다.
- DROP_FIRST_CANDIDATE: 유효 실행에서 위 KEEP conjunction을 충족하지 못함.

Secondary Top1 단독 개선이나 disagreement가 있다는 사실만으로 KEEP하지 않는다.
각 fold/월 delta, ranking_only 비율, 효과 크기를 병기하되 사후 문턱을 바꾸지 않는다.
이 기준은 연구 후보 보존 규칙이며 유의성/ensemble 이득/official PROMOTE를 뜻하지 않는다.
DROP도 모든 ranking 가능성을 부정하지 않는다. LL/Brier guardrail은 raw rank score에 적용하지 않는다.

## 18. Blocker 및 제한

설계 봉인은 가능하다. 실행 준비에는 branch 전용 LightGBM 환경, guarded loader,
133 hash 검증, fold OOF comparator/키 일치, 출력 경로 guard 및 manifest 구현이 필요하다.
현재 library 미설치/OOF 미생성은 실행 blocker이며 데이터 source 접근 blocker는 없다.
read-only 연결은 이번 세션 성공 사실일 뿐 future lock-free 보장이 아니다.
DB 전체 해시를 전후 검사하지 않았으므로 외부 프로세스에 의한 변경 부재까지 보증하지 않는다.
이 작업은 source read-only connection만 사용했고 DDL/DML/build를 수행하지 않았다.

## 19. 생성·수정 문서

신규: 이 문서 `docs/ranking-research-v1-contract.md`.
Append: `docs/progress.md`, `docs/decision_log.md`, `docs/experiment_log.md`.
구현 소스/설정/dependency/기존 보호 문서는 변경하지 않는다.

## 20. 다음 구현 단계와 사실/가설 분리

다음 요청에서 구현 단계로 넘어갈 수 있다. 먼저 위 실행 blocker와 계약 테스트를 해결한 뒤
한 candidate와 동일 fold comparator만 실행한다. 이번 단계는 여기서 멈춘다.

확인된 사실: clean ranking-dev/공통 HEAD, read-only DB 접근, Development grain/status,
L133 및 T1/RA1 기존 문서 계약, legacy R 코드/저장 metric, LightGBM 미설치.

미검증 가설: nonlinear LambdaRank의 추가 신호, F3와 group objective의 중복 정도,
raw-score normalization의 ensemble 활용성. 어느 것도 성능 사실로 주장하지 않는다.

첫 실제 실험의 질문: primary 개선이 3/4 fold에서 반복되는가? PLC Recall guardrail을 지키는가?
PLC-only/ranking-only 경주가 어떻게 분포하는가? key-complete OOF를 재현할 수 있는가?
family와 objective가 함께 바뀌는 이 제한된 절차 비교에서 KEEP 조건을 충족하는가?

Commit Summary (제안만): docs: seal first PIT-safe ranking research contract

Commit Description (제안만): Audit ranking worktree and read-only Development data access; distinguish
legacy finish-order LambdaRank from PLC probability modeling; seal one L133 binary-PLC LambdaRank
candidate, temporal folds, metrics, OOF interoperability and KEEP/DROP rules. No model execution,
shared database writes, Validation access, commit or push.
