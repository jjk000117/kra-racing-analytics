# Ranking v1 구현 및 구조 감사

작성일 2026-09-08. 상태: 구조 감사 완료, 실제 Development 모델 실험 미실행.
규범 설계는 `ranking-research-v1-contract.md`를 유지한다.

## 1. 계약 commit / Git

시작 branch `ranking-dev`, HEAD `b4cd6b04db901a0dd548b510379d180add6ebb92`.
시작 staged/unstaged/untracked 모두 없음. 공통 기준점 ef6a38a 이후 이미 예상 문서 4개만
커밋되어 있었다. Summary는 요청과 동일한 `docs: seal first PIT-safe ranking research contract`.
기존 Description은 한국어로 작성되어 요청된 영어 문장과 바이트 단위로 같지는 않지만 동일 범위다.
중복 commit이나 amend를 하지 않았다. 이번 구현은 미커밋이며 Push하지 않았다.
main/PLC/ensemble worktree는 시작 clean, 직접 변경하지 않았다.

## 2. Dependency / 환경

`pyproject.toml`에 optional `ranking = ["lightgbm==4.6.0"]` 한 항목을 추가했다.
전용 `.venv`에 LightGBM 4.6.0 및 현재 ranking editable package를 설치했다.
공용 Conda를 변경하지 않고 `--system-site-packages`로 기존 패키지를 읽기 전용 재사용했다.
실제 import 경로는 ranking worktree의 `src/kra_analytics/__init__.py`임을 확인했다.

Python 3.12.13 / DuckDB 1.5.5 / NumPy 2.5.1 / pandas 2.3.3 / sklearn 1.9.0 /
scipy 1.18.0 / LightGBM 4.6.0. 전이 dependency까지 정확한 41개 버전을
`ranking-requirements.lock.txt`에 기록했다. `validate_environment`가 Python 및 모든 pin을
검사하므로 공유 설치 패키지가 나중에 달라지면 조용히 실행하지 않고 실패한다.
이 lock은 버전 pin이며 wheel hash lock은 아니다. 과거 T1 문서의 sklearn 1.8과 현재 환경은
다르므로 과거 저장 metric의 비트 단위 재현을 이번에 입증했다고 주장하지 않는다.

새 독립 환경 재구성 예시(현재 공유 환경에 실행 금지):

```powershell
# Python 3.12.13으로 ranking worktree 내부에 새 venv 생성 후
.venv/Scripts/python.exe -m pip install -r ranking-requirements.lock.txt
.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e '.[ranking]'
```

## 3. Read-only source / branch-local output

`RankingPaths`가 명시적 source 절대경로를 받으며 연결은 항상 `read_only=True`다.
환경변수의 DB 주소를 write target으로 재사용하지 않는다. source missing/lock은 실패하며
read-write fallback이 없다. `output()`은 resolve 후 경계·source 충돌·동일 파일·상위 경로를
검사한다. JSON, OOF CSV, model.save는 해당 guard를 사용하며 기존 파일 덮어쓰기도 금지한다.
optional experiment DB는 이번 구현에서 만들지 않았다. source DB에는 DDL/DML을 실행하지 않았다.
DDL 차단 unit test는 임시 synthetic DB에서만 수행했다.

출력: ranking root의 `data/exports/modeling/ranking_research_v1/` 아래.
실제 산출물은 `structural/audit.json`과 synthetic pytest 임시 산출물뿐이다.
실제 candidate dataset/model/prediction/full OOF는 저장하지 않았다.

## 4. 공통 DB hash / 보호

Source: `C:/Users/jjk00/Documents/GitHub/kra-racing-analytics/data/warehouse/kra.duckdb`.
작업 시작과 구조 감사 전후 SHA256:

`0f760634f63e8c4f606688202e41b2513735eb8a1122b4d586f64fc075e89e01`

구조 감사 JSON에는 ranking 계약, L133 계약, T1/H133/RA1/HGB 관련 선택 문서 및
공통 Validation ledger의 파일 hash도 저장했다. 해당 감사 전후 동일했다.
ledger는 무결성 hash만 계산했으며 평가 데이터/prediction을 로드하지 않았다.
기존 보호 파일은 변경 목록에 없으며 기존 Snapshot/PIT/결과를 재작성하지 않았다.

## 5. Model config

`model_config()`가 봉인된 단일 설정을 반환한다. LambdaRank/GBDT, binary gain [0,1],
200 rounds, learning_rate .03, leaves 15, depth 4, min_child_samples 50, L2 1,
seed 20260908, CPU single-thread, deterministic/force_col_wise,
truncation 6, lambdarank_norm=true. 나머지 명시 parameter도 계약 14절대로 구현했다.
추가 `verbosity=-1`은 출력 제어만 한다. early stopping, eval-set fit, parameter search 없음.
training API eval_at=[3]은 고정이며 실제 평가 지표는 독립 `ranking_metrics` 구현이다.

`fit_ranker`는 명시적인 단일 fit; `run_ranker_fold`는 기존 fold 하나를 준비하는 후속 호출용
adapter다. 이번에는 두 함수 중 synthetic fit만 실행했다. full 실험 자동 실행 CLI는 없다.
`Ranker.save`는 전처리+모델을 guarded local joblib으로 저장하며 synthetic reload 일치를 테스트했다.

## 6. L133

정확히 133개 = 117+F1 6+F3 10. 기존 계약의 이름/순서와 코드 조합의 SHA256을 모두 검증한다.

`18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`

T1/F2 추가, F3 제거 없음. Loader SQL은 133개를 명시 투영한다.
식별자·lineage·공식 target/finish/status는 관리 영역이며 X에는 포함되지 않는다.

## 7. Population/status/PIT

Development WHERE는 SQL에서 `2023-01-01 <= race_date < 2024-07-01`로 고정되며 SQL 전과
반환 후 guard를 둔다. Snapshot 및 Canonical 1:1 join, base/F1 source 최대일 < feature_as_of,
feature_as_of=race_date, status/valid-start/valid-finish, 완료마 finish 유효성, 제외사유를 검사한다.
F3 및 완료·공식 PLC 모집단은 상속된 Snapshot 계약을 재사용하며 전체 source를 재빌드하지 않는다.

28,392행 / 2,675경주. FINISHED 28,318, RACE_STOPPED 73, DISQUALIFIED 1.
DNS·취소·미해결 상태의 새 음성 타깃 생성 없음. 주행중지/실격을 제거하지 않는다.
PIT/group/key 위반은 모두 검사 통과. 2024-07 이후 평가 행 조회 0.

## 8. Relevance 분포

| 경주당 PLC positive 수 | 경주 수 |
|---:|---:|
| 2 | 7 |
| 3 | 2,661 |
| 4 | 7 |

positive 없는 경주 0, 모두 positive인 경주 0. 공식 값을 임의로 3개로 맞추지 않는다.
단일 relevance가 추후 발견되면 ranking train에서 제외·기록하고 eval에는 보존한다.
PLC comparator는 원래 horse-level train을 유지한다. 이번 모집단에서는 그 차이가 발생하지 않는다.

## 9. Group

race_date/race_id/horse_id 정렬 후 contiguous race block별 int32 size를 전달한다.
sum=28,392, 경주당 7~16두. 크기 합, block 연속성, race 재등장, 키 중복을 검사한다.
최소 3두 미만 경주는 양쪽 모집단에서 제외·기록한다(현재 0).

## 10. Fold

| Fold | Train 행/경주 | Eval 행/경주 | Train 마지막 | Eval 첫날~마지막 | 변환 열 |
|---|---:|---:|---|---|---:|
| 1 | 9,224/854 | 4,458/427 | 2023-06-30 | 2023-07-01~09-24 | 201 |
| 2 | 13,682/1,281 | 5,229/494 | 2023-09-24 | 2023-10-06~12-31 | 218 |
| 3 | 18,911/1,775 | 4,707/432 | 2023-12-31 | 2024-01-05~03-31 | 248 |
| 4 | 23,618/2,207 | 4,774/468 | 2024-03-31 | 2024-04-05~06-30 | 260 |

Train 시작은 모두 2023-01-06. 기존 DEVELOPMENT_FOLDS 그대로, overlap 0, strict order 모두 true.
OOF 가능 구간은 2023-07~2024-06, 19,168행/1,821경주. 최초 H1은 in-sample로 채우지 않는다.

## 11. Preprocessing 판단

봉인 계약이 이미 표현을 고정했으므로 OHE/median/count0/StandardScaler를 의도적으로 유지했다.
Tree split 자체에 scaling이 필수여서가 아니라 representation 변경을 첫 절차 비교에서 분리하기 위해서다.
범주 11개, 수치 122개; categorical most-frequent imputation, unknown category all-zero OHE.
native categorical, target encoding, missing-indicator 추가 실험은 없다.
일반 numeric train median, 계약 count NULL→0. zero_as_missing=false, use_missing=true지만
실제 inherited imputation 뒤 dense ndarray는 네 fold 모두 finite였다.
object/category 값은 기존 preprocessor가 수치 OHE로 변환하며 ranker에는 categorical_feature=[]를 전달한다.
전체결측 column 동작도 기존 SimpleImputer 계약을 따른다. 실제 네 fold의 각 train median을
독립 계산해 대사했고 eval 통계를 fit하지 않았다. synthetic unseen category/missing test도 통과했다.

## 12. Synthetic smoke

50개 synthetic race/400행으로 봉인 config fit을 두 번 수행하고 16행 predict가 성공했다.
실제 tree가 생성됨을 확인했고 score 길이/finite/re-run exact equality/저장 후 reload equality를 검사했다.
실제 Development race를 이용한 model smoke도 하지 않았다.
joblib 로드 시 NumPy 2.5 array.shape 관련 upstream DeprecationWarning 4개가 있었다.
예측 불일치·실행 실패는 없었다.

## 13. Metrics

race-macro binary NDCG@3, macro Recall@3, NDCG@1, Top1 PLC, Top3 any PLC,
mean PLC hits in Top3를 구현했다. horse_id ordinal tie-break를 모든 ranking 선택에 공통 적용한다.
서로 다른 runner/positive 수의 손계산 fixture로 race 동일 가중 평균을 검증했다.
zero-positive의 NDCG/Recall은 NA를 보존해 macro를 INVALID로 만들며 평균에서 조용히 빼지 않는다.
NDCG는 PLC 양성 집중도를 측정하며 1/2/3착 순서 학습 지표가 아니다.
이번에 실제 Development score 기반 metric, KEEP/DROP를 계산하지 않았다.

## 14. OOF

`ranking_oof.py`: schema/builder/writer/loader/validator/full-coverage join 구현.
key=(race_id,horse_id,race_date,fold_id), 문자열 ID·선행 0 보존.
사용자의 최신 요청에 맞춰 출력 이름은 `ranking_raw_score`, `ranking_within_race_rank`,
`ranking_normalized_score`로 고정한다. 이전 문서의 within_race_rank/within_race_normalized_score와
같은 의미이며 이 이름 매핑만 구현에서 구체화했다.

raw 내림차순, 완전 tie는 horse_id 오름차순. normalized는 within-race z-score(ddof=0),
std=0이면 0이며 확률이 아니다. runner_count도 기록한다.
model contract/version, Feature/source DB/snapshot/code/config/contract hash, run/candidate를 포함한다.
`build_provenance`는 Feature+target+snapshot ID를 포함한 scope hash와 미커밋 source code hash를 만든다.
CSV sidecar manifest의 날짜 선언을 먼저 검사하고 file hash를 검증한다.
validator는 fold 날짜, duplicate/missing coverage, rank/normalization 재계산, metadata를 검사한다.
writer는 외부 경로/기존 산출물 overwrite를 차단한다. full OOF는 생성하지 않았다.

## 15. PLC OOF adapter

기존 RA1 및 F1+F3 combination Development export 파일명을 확인했다. fold 집계와
nested_oof_folds는 있지만 재사용 가능한 horse-level L133 outer OOF 파일은 해당 경로에 없다.
다른 평가기간 prediction을 열거나 가져오지 않았다.
`run_plc_fold`는 기존 build_v2_pipeline + L133으로 동일 fold raw PLC 확률을 생성할 수 있는
최소 adapter다. 이번에 실제로 실행하지 않았다. Calibration 선택/재학습은 없다.
PLC writer/loader도 동일 key/provenance 계약을 사용한다.

## 16. Disagreement 준비

`join_oof`는 양쪽 전체 key coverage와 Feature/source/snapshot 일치를 확인하는 one-to-one
outer join이다. PLC probability와 ranking horse score를 보존하므로 이후 Top1 PLC 및
Top3 any PLC의 2x2를 각각 만들 수 있다. 해당 값은 이번에 계산하지 않았다.
후속 실험에서는 snapshot/target provenance가 일치하는 같은 전체 eval 모집단을 expected로 전달해야 한다.

## 17. 파일

- 신규 `src/kra_analytics/ranking_research.py`: 접근·dataset·fold·runner·metric·환경 guard.
- 신규 `src/kra_analytics/ranking_oof.py`: OOF·provenance·join.
- 신규 `scripts/audit_ranking_v1.py`: 모델 없는 구조 감사 실행기.
- 신규 `tests/test_ranking_research.py`: 신규 계약 검증.
- 신규 `ranking-requirements.lock.txt`: 정확한 버전 pin.
- 변경 `pyproject.toml`: ranking optional dependency.
- 신규 이 보고서, continuity 문서 3개 append.
- ignored `data/exports/modeling/ranking_research_v1/structural/audit.json`, `.venv`, synthetic test 산출물.
- 기존 봉인 계약 문서 내용은 수정하지 않았다.

## 18. 검증 결과와 기존 제한

- 최신 ranking + development + race-aware 관련 Pytest: 27 passed.
- 전체 Pytest 실행 당시: 91 passed / 2 failed. 기존 `test_improvement_validation.py` 및
  `test_improvement_validation_contract.py`가 gitignored combination experiment_registry.json을
  요구하지만 새 worktree에 없어서 실패. Validation 접근은 발생하지 않았다.
  공통 export 복사/Validation 관련 동작으로 이를 우회하지 않았다.
- Ruff `src tests scripts/audit_ranking_v1.py`: 통과.
- Ruff `.`: 기존 notebooks/06b_feature_availability_analysis.ipynb와
  06c_dns_policy_validation.ipynb의 미사용 import/긴 줄 총 8개 오류. 범위 밖 notebook은 수정 안 함.
- mypy `src/kra_analytics`: 39개 source 통과.
- git diff --check: 통과. 모델 변경 자체는 미커밋.

실행 명령:

```powershell
.venv/Scripts/python.exe -B scripts/audit_ranking_v1.py --source C:/Users/jjk00/Documents/GitHub/kra-racing-analytics/data/warehouse/kra.duckdb --output data/exports/modeling/ranking_research_v1/new-audit/audit.json
.venv/Scripts/python.exe -B -m pytest tests/test_ranking_research.py tests/test_development_evaluation.py tests/test_race_aware_experiment.py -q --basetemp=data/exports/modeling/ranking_research_v1/new-pytest
.venv/Scripts/python.exe -B -m ruff check src tests scripts/audit_ranking_v1.py
.venv/Scripts/python.exe -B -m mypy src/kra_analytics --cache-dir=data/exports/modeling/ranking_research_v1/mypy-cache
```

## 19. 다음 단계 / 사실·가설·질문

현재 ranking 구조·dependency·data access blocker는 해소됐다. 전체 repository 검사에는 위 기존
환경 의존 테스트 2개/노트북 lint 제한이 남는다. 다음 명시적 요청에서 실험 orchestration으로
기존 4 fold와 raw PLC adapter를 호출하고 OOF/manifest를 저장하면 된다.
Full Development 실행 전 환경/source hash를 다시 확인하고 해당 실행의 provenance를 만들 것.
과거 저장 PLC metric과 현 sklearn 버전에서의 수치 재현 여부는 미확인이며 동일 실행의 comparator를 사용한다.

확인된 사실: 계약 commit 존재, source hash 동일, L133/PIT/population/group/fold 검사 통과,
synthetic 결정론적 fit/predict/save 통과, OOF schema 및 adapter 준비.
미검증 가설: LambdaRank가 추가 순위 신호를 주는가, ensemble/disagreement가 유용한가.
첫 full 실험 질문: primary 평균 및 3/4 fold 개선인가, Recall guardrail을 지키는가,
complete-key OOF와 재현성은 유지되는가. 실제 성능/KEEP/DROP는 아직 없다.

Commit Summary (제안만): feat: prepare PIT-safe ranking v1 infrastructure

Commit Description (제안만): Add guarded read-only Development loading, frozen L133 LambdaRank
configuration and environment pins, race-group/PIT audits, binary ranking metrics, and interoperable
ranking/PLC OOF adapters. Verify synthetic deterministic fitting and branch-local persistence without
running full Development experiments, accessing Validation, or modifying shared data.

종료 동시작업 관찰: main/ensemble은 clean이었다. plc-dev에는 시작 때 없던 cli.py 변경 및
aptitude_features.py/experiment_database.py와 해당 테스트가 나타났다. 이번 작업은 그 경로를
수정하지 않았으며 다른 작업의 변경으로 보고 그대로 두었다. 따라서 다른 worktree 전체가
시작·종료 동일하다고 주장하지 않는다. 공통 DB와 명시적으로 hash 검사한 보호 파일은 종료에도 동일했다.
최종 Ruff 재검사는 캐시 디렉터리 권한 문제를 피한 `--no-cache`로 수행했다.
