# 6C 첫 역사적 Feature Snapshot 명세

결정일: 2026-08-08  
상태: A안 승인, Feature 명세 확정, Snapshot 미구현

## 1. 목적과 범위

첫 Snapshot은 `API4_3`만 사용해 연승 적중확률 기준모델에 필요한 최소 Feature를 만든다. 목표는
Feature 파이프라인, 날짜순 검증, 확률평가와 Calibration 구조를 완성하는 것이다. 현재 만들 수
있다는 이유만으로 구간기록, 배당, 날씨, 주로, 마주·조합 이력까지 확대하지 않는다.

- 행 Grain: `race_id + horse_id`
- 모집단: 승인된 4,582경주의 `is_valid_start = true`인 말
- `feature_as_of`: 해당 `race_date`의 시작 시점으로 간주
- 역사 이력 조건: 모든 원천 경주의 `source_race_date < feature_as_of`
- 같은 날짜의 앞 경주도 이력에서 제외
- Feature 원천: `canonical.race`, `canonical.runner_result`, 과거 경주의
  `canonical.winning_payout(pool_code='PLC')`
- 현재 경주의 결과·상태·기록·배당·매출은 모델 입력에서 제외

## 2. 과거 이력 원천 모집단

과거 이력은 현재 행보다 날짜가 이른 경주 중 다음을 모두 만족하는 경주만 사용한다.

1. `canonical.race.race_status = 'COMPLETED'`
2. 공식 PLC 적중 조합이 존재하고 정상 파싱됨
3. 적중마가 해당 경주의 승인된 말 모집단과 일치함
4. DNS 외 미해결 비출전 상태나 Grain·업무키 오류가 없음

말 이력은 `horse_id`, 기수 이력은 `jockey_id`, 조교사 이력은 `trainer_id`로 각각 결합한다. 이름은
조인 키로 사용하지 않는다. 기수·조교사 ID가 현재 행에서 NULL이면 해당 엔터티 이력 Feature는
모두 NULL이고 가용 플래그는 `false`다.

## 3. 결과 상태별 집계 규칙

| 과거 상태 | 출전수 | 유효 완주수 | 착순 집계 | PLC 적중수 | 최근 N회 출전 | 마지막 출전일 |
|---|---:|---:|---|---:|---|---|
| `FINISHED` | 포함 | 포함 | `official_finish_rank` 사용 | 공식 PLC 포함 여부 | 포함 | 포함 |
| `RACE_STOPPED` | 포함 | 제외 | NULL, 평균·최근착순에서 제외 | 0 | 포함 | 포함 |
| `DISQUALIFIED` | 포함 | 제외 | NULL, 평균·최근착순에서 제외 | 0 | 포함 | 포함 |
| `DNS` | 제외 | 제외 | 제외 | 제외 | 제외 | 제외 |
| 그 밖의 미해결 상태 | 원천 경주 자체를 제외 | 제외 | 제외 | 제외 | 제외 | 제외 |

여기서 두 비율을 구분한다.

- `finish_rate = 유효 완주수 / 실제 출전수`
- `plc_hit_rate_per_start = 공식 PLC 적중수 / 실제 출전수`

따라서 주행중지·실격은 실제 출전 후 연승에 적중하지 못한 결과로 `plc_hit_rate_per_start`의
분모에는 들어가고 분자에는 들어가지 않는다. 완주마만 분모로 쓰는 착순 기반 연승률은 기준모델
Feature로 만들지 않는다. DNS는 실제 출전이 아니므로 분모와 분자 모두에 들어가지 않는다.

## 4. NULL과 이력 부족의 공통 원칙

- 관측 이력 건수는 이력이 없을 때 `0`이다. 이는 전체 생애 0회가 아니라 **현재 데이터 관측창에서
  과거 이력 0회**라는 뜻이다.
- 분모가 0인 비율·평균·경과일은 `0`으로 대체하지 않고 NULL로 둔다.
- 각 엔터티의 `history_available`을 함께 제공한다. 모델이 NULL을 직접 처리하지 못하면 전처리
  단계에서만 대체값과 결측 플래그를 사용하며 원본 Snapshot 값은 유지한다.
- 데이터가 2024년부터 시작하므로 모든 이력은 좌측 절단될 수 있다. `history_complete=true`를
  추정하지 않고, 전 행에 관리 컬럼 `history_window_start_date`를 기록한다.
- 최근 N회는 달력 기간이 아니라 `race_date DESC, race_id DESC`로 정렬한 실제 출전 이벤트다.
  같은 날짜 결과는 전부 제외되므로 `race_id` 정렬은 재현성만 위한 tie-breaker다.

## 5. 모델 입력 Feature

### 5.1 현재 경주·출전마 기본 Feature

| Feature | 의미 | 원천 컬럼 | 계산식/기준 | NULL 처리 | PIT | 용도 |
|---|---|---|---|---|---|---|
| `meet_code` | 경마장 | `race.meet_code` | 원천 코드 그대로 범주형 | NULL이면 행 생성 실패 | 현재 경주의 사전 고정 의미를 개발용 프록시로 사용 | 모델 |
| `race_grade` | 경주 등급 | `race.race_grade` | trim한 원천값 그대로 범주형 | NULL은 `UNKNOWN` 범주 | 동일 | 모델 |
| `distance_m` | 경주 거리 | `race.distance_m` | 정수 미터 | NULL이면 행 생성 실패 | 동일 | 모델 |
| `registered_runner_count` | 결과 원장의 등록 말 행 수 | `race.runner_count` | 경주별 API4_3 행 수. DNS 포함 | NULL/0이면 행 생성 실패 | 최종 베팅 가능 두수가 아닌 개발용 프록시 | 모델 |
| `gate_no` | 출주번호·마번 | `runner_result.gate_no` | 정수 원천값 | NULL이면 행 생성 실패 | 현재 경주 결과와 무관한 기본정보로 간주 | 모델 |
| `horse_sex` | 말 성별 | `runner_result.horse_sex` | trim한 원천값 그대로 범주형 | NULL은 `UNKNOWN` 범주 | 동일 | 모델 |
| `horse_age` | 경주일 기준 원천 연령 | `runner_result.horse_age` | 정수 원천값 | NULL은 NULL + 결측 처리 | 동일 | 모델 |
| `carried_weight` | 현재 경기 부담중량 | `runner_result.carried_weight` | 원천 수치 그대로 | NULL은 NULL + 결측 처리 | 동일; 향후 사전 출전표로 교체 필요 | 모델 |

이 기본 Feature는 API4_3에서 사후 수집됐지만 의미상 경기 전에 정해지는 값이라는 개발 가정으로
사용한다. 실제 발매마감 시점 운영 성능의 증거로 표현하지 않는다.

### 5.2 말 전체 이력 Feature

아래에서 `H`는 같은 `horse_id`이고 `source_race_date < current_race_date`인 승인된 과거 행이다.

| Feature | 의미 | 원천 컬럼 | 정확한 계산식 | 부족/NULL | 용도 |
|---|---|---|---|---|---|
| `horse_prior_start_count` | 관측 과거 실제 출전수 | `horse_id`, `is_valid_start` | `count(H where is_valid_start=true)` | 없으면 0 | 모델 |
| `horse_prior_finish_count` | 공식 수치 착순이 있는 완주수 | `is_valid_finish` | `count(H where is_valid_finish=true)` | 없으면 0 | 모델 |
| `horse_prior_finish_rate` | 출전 대비 완주 비율 | 위 두 count | `finish_count / start_count` | start=0이면 NULL | 모델 |
| `horse_prior_plc_hit_count` | 과거 공식 PLC 적중수 | `winning_payout`, `gate_no` | `sum(place_hit)` over valid starts | 이력 없으면 0 | 관리/감사 |
| `horse_prior_plc_hit_rate` | 출전 대비 과거 PLC 적중 비율 | 위 count | `plc_hit_count / start_count` | start=0이면 NULL | 모델 |
| `horse_prior_avg_finish_rank` | 완주한 경주의 평균 공식 착순 | `official_finish_rank` | `avg(rank)` over valid finishes | finish=0이면 NULL | 모델 |
| `horse_days_since_last_start` | 마지막 실제 출전 후 경과일 | `race_date`, `is_valid_start` | `current_race_date - max(prior valid-start race_date)` | start=0이면 NULL | 모델 |
| `horse_history_available` | 말 과거 이력 존재 여부 | start count | `start_count > 0` | 항상 boolean | 모델 |

### 5.3 말 최근 5회 Feature

`H` 중 실제 출전만 날짜 내림차순으로 정렬해 최대 5건을 `H5`로 둔다. DNS는 `H5` 순번을
차지하지 않는다.

| Feature | 의미 | 원천 컬럼 | 정확한 계산식 | 부족/NULL | 용도 |
|---|---|---|---|---|---|
| `horse_recent5_start_count` | 최근 창에 실제 존재하는 출전수 | `horse_id`, `race_date`, `is_valid_start` | `count(H5)` | 0~5 | 모델 |
| `horse_recent5_finish_rate` | 최근 출전의 완주 비율 | `is_valid_finish` | `count(valid_finish in H5) / count(H5)` | H5=0이면 NULL | 모델 |
| `horse_recent5_plc_hit_rate` | 최근 출전의 공식 PLC 적중 비율 | 과거 `place_hit` | `sum(place_hit in H5) / count(H5)` | H5=0이면 NULL | 모델 |
| `horse_recent5_avg_finish_rank` | 최근 5회 중 완주 경기의 평균 착순 | `official_finish_rank` | `avg(official_finish_rank)` over valid finishes in H5 | 완주 0이면 NULL | 모델 |

주행중지·실격은 `H5`에 포함되어 finish rate와 PLC hit rate를 낮추지만 평균 착순에서는 제외된다.
이를 임의의 최하위 착순으로 치환하지 않는다.

### 5.4 말 동일거리 이력 Feature

`HD`는 `H` 중 `historical.distance_m = current.distance_m`인 실제 출전이다.

| Feature | 의미 | 원천 컬럼 | 정확한 계산식 | 부족/NULL | 용도 |
|---|---|---|---|---|---|
| `horse_same_distance_start_count` | 동일거리 과거 출전수 | `race.distance_m`, `is_valid_start` | `count(HD)` | 없으면 0 | 모델 |
| `horse_same_distance_plc_hit_rate` | 동일거리 출전 대비 PLC 적중률 | 과거 `place_hit` | `sum(place_hit in HD) / count(HD)` | count=0이면 NULL | 모델 |

경마장별·등급별 말 성적은 표본 희소성과 Feature 수 증가를 피하기 위해 첫 Snapshot에서 제외한다.

### 5.5 기수·조교사 이력 Feature

각 엔터티의 모든 승인된 과거 실제 출전을 사용한다. 상태 처리는 말 이력과 동일하다.

| Feature | 의미 | 원천/키 | 정확한 계산식 | 부족/NULL | 용도 |
|---|---|---|---|---|---|
| `jockey_prior_start_count` | 기수의 관측 과거 출전수 | `jockey_id` | valid-start 행 수 | ID NULL이면 NULL, 이력 없으면 0 | 모델 |
| `jockey_prior_plc_hit_rate` | 기수의 출전 대비 PLC 적중률 | `jockey_id`, PLC 타깃 | PLC 적중수 / 출전수 | 분모 0이면 NULL | 모델 |
| `jockey_history_available` | 기수 과거 이력 존재 | 위 count | `start_count > 0`; ID NULL이면 false | boolean | 모델 |
| `trainer_prior_start_count` | 조교사의 관측 과거 출전수 | `trainer_id` | valid-start 행 수 | ID NULL이면 NULL, 이력 없으면 0 | 모델 |
| `trainer_prior_plc_hit_rate` | 조교사의 출전 대비 PLC 적중률 | `trainer_id`, PLC 타깃 | PLC 적중수 / 출전수 | 분모 0이면 NULL | 모델 |
| `trainer_history_available` | 조교사 과거 이력 존재 | 위 count | `start_count > 0`; ID NULL이면 false | boolean | 모델 |

최근 기수·조교사 폼, 완주율, 말–기수 조합 이력은 첫 기준모델에서는 제외한다. 말 이력보다 표본이
크고 변화 가능성이 있지만, 최소 기준선 완성 후 시간창과 추가가치를 별도로 검증한다.

## 6. 관리·감사 컬럼

다음은 모델 입력이 아니다.

| 컬럼 | 의미/계산 |
|---|---|
| `snapshot_id` | Snapshot 버전과 실행을 식별하는 키 |
| `snapshot_version` | Feature 정의 버전. 최초 구현은 별도 버전명으로 고정 |
| `race_id`, `horse_id` | 행 업무키 |
| `race_date`, `feature_as_of` | 분할키와 Point-in-Time 기준일 |
| `jockey_id`, `trainer_id` | 이력 결합 감사키 |
| `source_batch_id` | API4_3 Raw lineage |
| `policy_version` | 적용한 결과 상태 정책 버전 |
| `history_window_start_date` | 현재 API4_3 관측 시작일 |
| `source_max_event_date` | 해당 행의 모든 이력 Feature가 참조한 가장 늦은 과거 경주일 |
| `history_complete` | 항상 `false` 또는 `unknown`; 완전한 생애 이력을 주장하지 않음 |
| `population_proxy` | `POST_RACE_VALID_START_PROXY` 고정 |
| `place_hit` | 공식 PLC 적중 타깃. 모델 입력에서 물리적·논리적으로 분리 |
| `result_status`, `is_valid_start`, `is_valid_finish` | 모집단·타깃 생성 감사용 현재 결과 상태. 모델 입력 금지 |
| `population_exclusion_reason` | 제외 행·경주 사유. 포함 행은 NULL |

## 7. Point-in-Time 불변조건

각 Snapshot 행은 다음을 모두 만족해야 한다.

```text
source_max_event_date < feature_as_of = race_date
```

1. SQL window frame의 단순 이전 행이 아니라 `race_date < current_race_date` 조건을 먼저 적용한다.
2. 같은 날짜의 모든 다른 경주를 제외한다.
3. 말·기수·조교사·동일거리·최근 5회 모두 같은 날짜 경계를 사용한다.
4. 현재 경주의 `place_hit`, 착순, 기록, 결과상태, 배당과 매출을 Feature 계산에 참조하지 않는다.
5. 과거 PLC 적중은 해당 과거 경주의 타깃으로만 사용한다.
6. `source_max_event_date >= race_date`이거나 계산 근거를 역추적할 수 없으면 행 생성을 실패한다.

## 8. 첫 Snapshot에서 제외하는 후보

- 현재 경주 단승·연승배당, 확정배당, 매출
- 현재 경주 착순·경주기록·결과상태
- 마체중, 날씨, 주로상태
- 과거 구간기록과 세부 페이스 Feature
- 마주 성적, 말–기수·말–조교사·기수–조교사 조합 Feature
- 경마장별·등급별 말 성적
- 기수·조교사의 최근 N회 성적
- 임의 평활, 가중평균, 종합점수

제외는 영구 폐기가 아니다. 첫 기준모델 이후 동일한 날짜 분할에서 ablation 근거가 생길 때
Snapshot 차기 버전 후보로 검토한다.

## 9. 구현 전 승인 요약

첫 모델 입력은 현재 기본정보 8개, 말 이력 14개, 기수 이력 3개, 조교사 이력 3개로 총 28개다.
이 중 count·rate·가용 플래그는 서로 다른 의미를 가지므로 함께 유지한다. 관리·감사 컬럼과
`place_hit`은 28개에 포함하지 않는다.

다음 단계에서는 이 명세를 그대로 SQL/Python Snapshot으로 구현하고, 구현 과정에서 Feature를
추가하지 않는다. 명세 변경이 필요하면 구현 전에 문서 버전을 먼저 갱신한다.
