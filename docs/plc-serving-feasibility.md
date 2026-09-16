# PLC provisional 137 Feature serving feasibility audit

감사일: 2026-09-16

대상 branch: `plc-dev`

대상 후보: unweighted Logistic, 137 Features, temporal OOF sigmoid

Feature hash: `7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e`

## 1. 목적과 범위

이 감사의 질문은 하나다.

> 아직 열지 않은 미래기간을 사용하지 않고, 다음 경주의 베팅 직전 시점에 137개 입력을 실제로
> 구성해 동일한 추론 절차를 실행할 수 있는가?

저장소의 코드·문서·registry·기존 API 메타데이터 검증만 읽었다. API 호출, 웹 조회, 모델 학습,
prediction, 성능 계산, Validation 재접근, 2024-07 이후 데이터 로드, DB 변경은 수행하지 않았다.
이 문서는 모델 성능 판정이나 cutoff 최종 결정이 아니다.

137개 전체 행별 감사는
[`serving_feature_availability.csv`](serving_feature_availability.csv), 파이프라인 단계는
[`serving_pipeline_stage_map.csv`](serving_pipeline_stage_map.csv), blocker는
[`serving_blockers.json`](serving_blockers.json)에 재현 가능하게 저장했다.

## 2. 계약 재현과 분류 결과

코드의 provisional candidate builder를 읽기 전용으로 실행해 순서·개수·hash를 재현했다.

| 구분 | 정의 | 수 |
|---|---|---:|
| A | 현재 출전표 또는 공식 구조화 사전 원천에서 직접 확보 | 23 |
| B | 현재 경주 entity ID와 동결된 과거 DB로 PIT-safe 계산 | 109 |
| C | 별도 race-day 원천과 cutoff 이전 관측시각이 필요 | 5 |
| D | 현재 근거로 확보·의미·시점이 불확실 | 0 |
| 합계 | 고유 Feature | 137 |

D가 0이라는 것은 137개 의미가 모두 알려졌다는 뜻이지, 오늘 당장 운영 추론이 가능하다는 뜻은
아니다. C 수집과 A의 운영 lineage, 최종 출전 집합, 서빙 오케스트레이션이 아직 없다.

### Feature family별 수

| 범주 | Family | 수 |
|---|---|---:|
| A | current race context / prize / runner profile | 9 / 9 / 5 |
| B | field-relative | 17 |
| B | horse long-term / recent / aptitude / weight | 12 / 22 / 10 / 6 |
| B | jockey / trainer / owner | 5 / 5 / 2 |
| B | horse×jockey / horse×trainer | 4 / 2 |
| B | race-relative / speed-sectional / trend | 6 / 14 / 4 |
| C | race-day weather-track / horse weight | 3 / 2 |

## 3. 현재 경주 직접 입력

### 출전표·경주계획에서 확보 가능한 A

- 경마장, 등급, 거리, 출전두수, 마번
- 성별, 연령, 부담중량, rating
- 연령·부담·상금·성별 조건, 경주 유형, 경주 요일
- 1~5위 순위상금과 부가상금 1~3

미래 운영의 우선 원천은 `API26_2/entrySheet_2`이고, 경주 조건·계획·상금은
`API72_2`로 교차 확인할 수 있다. 현재 연구 Snapshot의 동일 필드는 API4 결과행에서
재구성되지만 API4는 **경주 후 원천**이므로 live serving 원천으로 사용할 수 없다.
`race_day_of_week`은 `race_date`에서 결정론적으로 계산한다.

### race-day 별도 원천이 필요한 C

| Feature | 후보 원천 | 현재 판단 |
|---|---|---|
| current_weather | KRA 경주로 현황/공식 race-day feed | 경기 전 의미는 검증됐지만 timestamped ingestion 없음 |
| current_track_condition | 동일 | 상태 변경을 cutoff별로 보존해야 함 |
| current_track_moisture_percent | 동일 | 수치와 갱신시각을 함께 저장해야 함 |
| current_horse_weight_kg | API25_1 또는 공식 출전마체중 화면 | API25_1 실제 응답은 과거 403으로 운영 접근 미확인 |
| current_horse_weight_change_kg | 동일 | 게시 완료시각과 late refresh 규칙 미확인 |

기존 cutoff 검증은 이 다섯 값이 사전정보라는 **의미**를 승인했다. 이번 감사의 C 판정은 의미
부정이 아니라, 실제 추론 시 별도 race-day 수집과 `observed_at` 증거가 필요하다는 운영 분류다.

### 최종 출전집합과 변경정보

현재 Feature 중 `registered_runner_count`와 F3/R1은 최초 등록 목록이 아니라 실제 베팅 가능한
active field가 필요하다. 출전취소·DNS·기수변경·부담중량 변경이 발생하면 다음 순서로 처리해야 한다.

1. 변경 공지를 immutable event로 저장한다.
2. active runner와 horse/jockey/trainer/owner ID를 다시 확정한다.
3. 변경된 기수·부담중량 관련 history를 다시 계산한다.
4. 모든 field-relative percentile/median-difference를 전체 active field에서 다시 계산한다.
5. 기존 snapshot/prediction을 덮어쓰지 않고 새 버전으로 supersede한다.

현재 저장소에는 이 변경 feed, invalidation trigger, 재계산 orchestration이 없다.

## 4. Entity key와 과거 DB 연결

| Entity | 사전 원천 key | Historical key | 판단 |
|---|---|---|---|
| race | race_date + meet + race_no | project `race_id` | 직접 재구성 가능 |
| horse | API26 horse ID | `horse_id` | 직접 연결 가능 |
| jockey | API26 `jkNo` | `jockey_id` | 직접 연결 가능; 기수변경 반영 필수 |
| trainer | API26 `trNo` | `trainer_id` | 직접 연결 가능 |
| owner | API26 `owNo` | `owner_id` | 직접 연결 가능하나 과거 결측 소량 존재 |

이름 기반 fallback은 동명이인·개명·표기변경 위험 때문에 기본 경로로 허용하면 안 된다. 공식 ID가
없으면 `unresolved_entity_key`로 분리하고, 묵시적으로 이름 join을 해서는 안 된다.

## 5. Historical Feature serving 구조

### 재사용 가능한 B family

- 말 장기/최근 3·5·10회 이력, 동일 경마장·거리 적성
- 기수·조교사·마주, 말×기수, 말×조교사 이력
- 과거 마체중, race time/S1F/G3F/G1F
- F1 historical race-relative 성능
- T1 recent-five 순서 기반 trend
- F3/R1 current-field-relative 파생

기존 구현은 모두 `historical.race_date < feature_as_of`를 사용한다. API26의 현재 누적 성적 필드는
과거 조회 시 PIT가 아니므로 재사용하지 않고, API4 개별 과거 event에서 직접 집계하는 정책을
유지한다.

다만 구현은 연구용 전체 Snapshot 생성기다. 다음 경주 한 건을 받아 읽기 전용으로 과거를 조회하고
137개 순서/hash를 fail-closed로 내보내는 parameterized serving builder는 아직 없다.

### F3/R1 비교집단

F3/R1은 현재 경주의 사전 Feature를 active field 안에서 상대화한다. 기존 계약은 average rank,
동률 average, 비교 가능한 말 3두 미만이면 NULL이다. 다음 경우 반드시 다시 계산한다.

- 출전취소/DNS로 active runner가 변함
- 기수·부담중량·rating 등 upstream 값이 정정됨
- current field에 새 말이 추가되거나 말이 제거됨

부분 갱신으로 한 말의 percentile만 바꾸면 비교집단 일관성이 깨진다.

## 6. Cold start와 missingness

새 말·새 기수·새 조교사·새 조합에 과거가 없어도 추론 자체가 실패하면 안 된다.

- count는 계약상 관측 없음이 실제 0일 때만 0
- rate/median/trend는 최소 관측 조건 미달 시 NULL
- F3/R1은 비교 가능한 말 3두 미만이면 NULL
- sealed preprocessing은 count 0 처리와 train-fitted median/category 처리를 재사용

현재 추가로 필요한 것은 결측 원인의 구분이다.

| 상태 | 의미 | 허용 처리 |
|---|---|---|
| MATCHED_NO_HISTORY | ID 연결 성공, 과거 event 0 | 정상 cold start |
| INSUFFICIENT_HISTORY | 연결 성공, 최소 관측 미달 | NULL + 실제 count |
| UNRESOLVED_ENTITY_KEY | 공식 ID 연결 실패 | 데이터 품질 경고; cold start로 위장 금지 |
| SOURCE_NOT_OBSERVED | cutoff 전 race-day 값 미수집 | 입력 누락/운영 장애 |

## 7. Prediction cutoff 후보

| 후보 | 137개 완성 가능성 | 장점 | 한계 |
|---|---|---|---|
| 출전표 공개 직후 | 낮음 | A와 대부분 B를 일찍 계산 | field 미확정, C 부재 |
| 경주일 아침 | 중간 | 날씨·주로 일부 확보 | 마체중·late changes 불완전 |
| T-30분 | 높음 추정 | 대부분 사전값 확보 가능 | 변경 감시가 여전히 필요 |
| T-10~T-5분 | 가장 높음 | 최종 field·마체중 반영 가능성이 큼 | 정확한 공개/정정시각 실측 근거 부족 |

따라서 **137개를 모두 쓸 수 있는 최소 시점은 현재 근거로 확정할 수 없다**. 실무 후보는
T-10~T-5분이지만, KRA 화면/API의 게시 완료시각과 late-change 빈도를 timestamped shadow
capture로 먼저 검증해야 한다. exact cutoff를 성능 또는 편의로 사후 선택해서는 안 된다.

## 8. 파이프라인 단계와 lineage

필요 단계는 current entry ingestion → race-day ingestion → active field/entity resolution →
historical as-of lookup → base/F1/T1 계산 → F3/R1 재계산 → 137 contract gate → preprocessing/
inference → prediction lineage 저장 → late-change supersession이다.

각 prediction은 최소 다음을 보존해야 한다.

- `race_id`, `horse_id`, `prediction_cutoff`, source별 `observed_at`
- current-entry/race-day snapshot ID와 hash
- historical DB high-water mark와 PIT condition
- ordered Feature hash, preprocessing/model/calibrator hash
- raw/sigmoid probability와 superseded 여부

단계별 구현 상태는 `serving_pipeline_stage_map.csv`에 있다.

## 9. 문서와 코드 사이의 운영상 차이

1. cutoff 검증 문서는 current weight/weather/track을 의미상 승인했지만, live timestamped collector는
   없다.
2. `feature_snapshot_v2.py`는 사후 API4 행을 사용해 역사적 연구 Snapshot을 재구성한다. 이는
   live pre-race serving 구현이 아니다.
3. README의 대표 Feature 서술은 LR1 144 단계가 중심이고, 후속 Development ablation이 만든
   provisional 137 상태가 완전히 반영되지 않았다. 이번 감사의 source of truth는 코드로 재현한
   137 count/order/hash다.
4. 과거 계산 코드는 PIT-safe하지만, live 요청별 `feature_as_of`·source `observed_at`·ID 매칭
   결과를 저장하는 serving contract가 없다.

## 10. 최종 판단

### 지금 137개 전체 추론이 가능한가?

**NOT YET.**

의미와 계산식은 모두 식별됐다(D=0). 그러나 다음 5개 운영 blocker가 남아 있다.

1. timestamped pre-race A/C snapshot과 `observed_at` lineage 부재
2. final active field, scratch/DNS, jockey-change feed와 재계산 trigger 부재
3. API25_1 마체중 operational access/게시시각 미확인
4. next-race parameterized Feature builder와 inference orchestration 부재
5. genuine cold start와 entity join 실패를 구분하는 provenance 부재

### 다음 권고 작업

DB나 모델을 바꾸기 전에 **read-only shadow-serving pilot**을 구현한다. 2~4개 실제 경주일에
출전표 공개, 경주일 아침, T-30, T-10/T-5 시점의 공식 화면/API snapshot과 변경 event를
timestamped Raw로 보존하고, active field와 137개 완성률을 측정한다. 이 결과로 exact cutoff와
재계산 SLA를 결정한 뒤 serving builder를 구현하는 순서가 가장 안전하다.

## 11. 근거

- [Prediction cutoff 및 미확정 원천 검증](official-place-baseline-cutoff-validation-v2.md)
- [Feature와 KRA API 메타데이터 대조](feature-api-metadata-review.md)
- [API26 historical PIT 검증](api26-pit-validation.md)
- [Snapshot v2 구현·PIT 감사](place-feature-snapshot-v2-build.md)
- [F1/F3 구현 코드](../src/kra_analytics/feature_bundles.py)
- [T1 구현 코드](../src/kra_analytics/trend_features.py)
- [R1 구현 코드](../src/kra_analytics/relative_features.py)
- [137 후보 계약 생성 코드](../src/kra_analytics/saturated_recent10_count_ablation.py)

## 12. 보호 확인

- API/웹 호출: 없음
- 모델 학습·prediction·성능 계산: 없음
- Validation/2024-07 이후 데이터 접근: 없음
- DB 쓰기: 없음
- Feature registry/기존 sealed artifact 변경: 없음
- 다른 worktree 수정: 없음
