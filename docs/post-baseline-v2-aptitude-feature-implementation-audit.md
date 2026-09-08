# Post-baseline v2 Aptitude A1 구현·데이터 감사

## 결론

봉인된 A1 7개를 기존 LT1 137개 뒤에 추가한 development-only 후보를 구현했다. 후보는
`2023-01-01 <= race_date < 2024-07-01`의 28,392행·2,675경주이며 업무키 중복, PIT 위반,
count/value 모순, 범위 오류 및 수동 재계산 불일치는 모두 0건이다. 모델 학습, prediction,
target 기반 성능 분석 및 Validation 접근은 수행하지 않았다.

## Source / output 분리

- 공용 source: `C:\Users\jjk00\Documents\GitHub\kra-racing-analytics\data\warehouse\kra.duckdb`
- source connection: DuckDB `read_only=True`로만 개방
- branch-local output: `data/warehouse/plc_experiments.duckdb`
- candidate table: `mart.place_feature_snapshot_v2_aptitude_candidate`
- lineage audit table: `quality.post_baseline_v2_aptitude_source_audit`
- 재현 산출물: `data/exports/validation/post_baseline_v2_aptitude_a1/`

`KRA_SOURCE_DATABASE_PATH`와 `KRA_EXPERIMENT_DATABASE_PATH`를 별도로 요구한다. source와 output이
같거나 output이 활성 worktree 밖이면 즉시 실패한다. 공용 DB 및 T1/L133 Validation/H133/RA1
보호 산출물 8개의 실행 전후 SHA256은 모두 동일했다. 공용 DB SHA256은
`0f760634f63e8c4f606688202e41b2513735eb8a1122b4d586f64fc075e89e01`이다.

## 구현 Feature와 lineage

| Feature | Historical source | 집계 | 가용률 |
|---|---|---|---:|
| `horse_same_grade_start_count` | 기존 유효 출전의 `race_grade` | 현재 등급 일치 count | 100% |
| `horse_same_grade_plc_hit_rate` | 위 출전의 과거 공식 `place_hit` | count 3 이상 평균 | 50.95% |
| `horse_same_track_condition_start_count` | 기존 유효 출전의 `current_track_condition` | 현재 주로상태 일치 count | 100% |
| `horse_same_track_condition_plc_hit_rate` | 위 출전의 과거 공식 `place_hit` | count 3 이상 평균 | 39.13% |
| `horse_same_distance_race_time_percentile_count` | 과거 F1 event percentile | 현재 거리 일치 count | 100% |
| `horse_same_distance_race_time_percentile_median` | 과거 F1 event percentile | count 3 이상 median | 42.26% |
| `horse_distance_change_from_last_start_m` | 가장 최근 과거 유효 출전 거리 | 현재 거리 - 직전 거리 | 94.40% |

F1 event percentile은 정상 실제 출전·완주, 유효 race time, 경주 내 비교 가능 3두 이상,
average-rank 동률 처리 및 `0=열위, 1=우위`인 기존 계약을 재사용했다. 모든 history join은
`historical.race_date < feature_as_of`를 명시한다.

## 분포와 가용성

- 동일등급 count: 중앙값 3, P25 1, P75 6, 최대 47
- 동일 주로상태 count: 중앙값 2, P25 0, P75 4, 최대 31
- 동일거리 F1 count: 중앙값 2, P25 0, P75 4, 최대 40
- 동일등급 rate 가용률: 2023 49.34% → 2024-H1 54.17%
- 동일 주로상태 rate 가용률: 2023 37.61% → 2024-H1 42.16%
- 동일거리 F1 median 가용률: 2023 41.81% → 2024-H1 43.16%
- 거리 변화: 26,801행 가용, 1,591행 이력 없음; 연장 8,574, 동일 12,538, 단축 5,689
- 경마장별 거리변화 가용률: 서울 94.59%, 부산경남 94.12%

네 development evaluation fold에서도 각 Feature의 availability와 분포를 저장했다. 동일
주로상태 rate는 fold 1의 27.48%에서 fold 4의 48.41%로 증가해 초기 left-censoring의 영향을
보이지만, 이는 모델 성능 판단에 사용하지 않았다.

## 데이터 감사

- candidate schema: LT1 137개 + A1 7개 = 144개 순서 일치
- 업무키 `(race_id, horse_id)` 중복: 0
- strict PIT 및 last-start PIT 위반: 0
- 최소 3회 count/value NULL 계약 위반: 0
- rate/percentile `[0,1]` 범위 위반: 0
- 무한대 값: 0
- branch-local DuckDB round-trip 불일치: 0
- 수동 독립 재계산: 경계 count, 장기 history, 동일거리 F1, 연장/동일/단축/무이력 10건 모두 일치
- A1 registry와 구현 이름·순서: 1:1 일치
- A1 Feature hash: `9f15c6caa05da889780ac29de73ec11441e470fba759925c00af936c3c5773d2`

## 다음 단계

데이터 계약상 blocker는 없다. 다음 별도 실험은 동일 Logistic, 동일 네 temporal fold,
Train-only preprocessing을 유지한 `LT1(137)` 대 `LA1(144)` 단일 비교다. 이번 구현 결과로
A1 정의나 최소 count를 변경하지 않는다.
