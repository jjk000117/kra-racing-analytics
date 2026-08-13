# Official place baseline v2 속도·sectional Feature 감사

기준일: 2026-08-13  
대상: 2022-01-07~2026-07-26, 85,566행·8,036경주  
범위: 원천 의미, 정규화, Historical aggregation, PIT, 조건 혼합 타당성  
제외 범위: 모델 학습, 타깃·성능·Feature importance, 새로운 속도지수 설계

## 결론

- `horse_recent3_race_time_median`, `horse_recent5_race_time_median`은 `EXCLUDE_LOGICAL`로 확정했다.
  Snapshot에는 유지하지만 서로 다른 거리·경마장의 절대 경주시간을 섞으므로 모델 입력에는 쓰지 않는다.
- race-time count 2개는 속도 크기가 아니라 유효 과거 관측 깊이이므로 유지한다.
- S1F·G3F·G1F recent3/recent5 median·count 12개는 `KEEP_AS_IS`로 판정했다. 모두 경마장별
  원천을 동일한 고정 길이 구간과 초 단위로 정규화한 Historical 값이다.
- 최종 official baseline v2 입력은 기존과 동일한 117개다. 구성은 `MODEL_INPUT` 117,
  `EXCLUDE_STRUCTURAL` 6, `EXCLUDE_LOGICAL` 2이며 `REVIEW_REQUIRED`는 0개다.

## 전수 Feature와 lineage

Snapshot의 속도·sectional 계열은 16개이고, 이 중 모델 입력은 14개다.

| 계열 | Snapshot Feature | 원천 → Semantic | 집계 | 조건 혼합 | 판정 |
|---|---|---|---|---|---|
| race time | recent3/5 median | 양 경마장 `rcTime` → `valid_race_time_seconds` | 최근 유효 3/5건 median | 경마장·거리 | `EXCLUDE` |
| race time | recent3/5 count | 동일 | 최근 유효 3/5건 count | 경마장·거리 | `KEEP_AS_IS` |
| S1F | recent3/5 median/count | 서울 `seS1fAccTime`, 부경 `buS1fTime` → `s1f_seconds` | 최근 유효 3/5건 median/count | 경마장·거리 | `KEEP_AS_IS` |
| G3F | recent3/5 median/count | 서울 `rcTime-seG3fAccTime`, 부경 `bu_3fGTime` → `historical_g3f_seconds` | 최근 유효 3/5건 median/count | 경마장·거리 | `KEEP_AS_IS` |
| G1F | recent3/5 median/count | 서울 `rcTime-seG1fAccTime`, 부경 `bu_1fGTime` → `historical_g1f_seconds` | 최근 유효 3/5건 median/count | 경마장·거리 | `KEEP_AS_IS` |

모든 원천 컬럼은 `staging.race_result`에 VARCHAR 원문으로 보존된다. Semantic v2가 0 sentinel을
NULL로 바꾸고 초 단위 구간값을 만든다. Snapshot builder는 현재 경주와 같은 말의
`hist.race_date < cur.race_date` 행만 연결한 뒤 metric별로 별도 recency rank를 부여한다.
따라서 결측 기록은 recent window의 자리를 소모하지 않고, 최근 3/5개의 **유효 관측값**을 집계한다.

현재 경주의 `rcTime`, S1F, G3F, G1F는 결과 후 정보다. Builder의 `base`에는 Historical 계산을
위해 일시적으로 존재하지만 최종 Snapshot current 입력에서는 제거되며, `speed_long`에는 과거 행만
들어간다. Snapshot의 `source_max_event_date >= feature_as_of` 위반은 0건이었다.

## 경마장별 정규화 감사

| 지표 | 서울 | 부산경남 | 공통 의미 |
|---|---|---|---|
| S1F | `seS1fAccTime` | `buS1fTime` | 출발 후 첫 200m |
| G3F | `rcTime - seG3fAccTime` | `bu_3fGTime` | 결승선 전 마지막 600m |
| G1F | `rcTime - seG1fAccTime` | `bu_1fGTime` | 결승선 전 마지막 200m |

부산경남에서 누적값과 직접 구간값을 함께 확인할 수 있는 35,695건을 전체기간 대조했다.
`rcTime-buG3fAccTime = bu_3fGTime`, `rcTime-buG1fAccTime = bu_1fGTime`은 각각 불일치 0건,
최대 절대 오차 0.0초였다. 서울 Semantic 계산식과 재계산값의 불일치도 G3F/G1F 모두 0건이다.

경마장별 유효 출전행의 결측률은 0.08~0.31%로 낮았다. 중앙값은 다음과 같다.

| 경마장 | S1F | G3F | G1F |
|---|---:|---:|---:|
| 서울 | 14.0초 | 39.4초 | 13.8초 |
| 부산경남 | 14.2초 | 39.5초 | 13.9초 |

두 경마장 차이는 원천 정의 불일치의 흔적이 아니라 코스·경주 구성에서 생길 수 있는 수준의
분포 차이다. 동일한 물리 구간과 단위가 검증됐으므로 경마장 분리는 필수 논리 조건이 아니다.

## 거리별·경마장×거리별 프로파일

거리별 중앙값 범위는 S1F 13.9~14.6초, G3F 37.9~40.9초, G1F 13.4~14.2초였다.
짧은 1000~1200m와 1600~1800m 이상에서 특히 G3F 분포가 달라지는 것은 경주 전체의 pace와
출발 위치·코스 구성이 마지막 구간 기록에도 영향을 준다는 점을 보여준다. 다만 G3F와 G1F가
각각 마지막 600m·200m라는 물리적 정의는 거리와 함께 바뀌지 않는다.

공통 거리의 경마장×거리 중앙값 차이도 확인했다. S1F는 주로 0.0~0.4초, G3F는 0.0~0.7초,
G1F는 0.0~0.2초 수준이었다. 이는 조건 효과를 후속 모델이 더 세밀하게 표현할 여지는 있지만,
현행 값이 서로 다른 단위나 구간을 섞었다는 증거는 아니다. 현재 경주의 `meet_code`와
`distance_m`도 별도 입력으로 유지된다.

## Feature별 최종 판정

| Feature 묶음 | 판정 | 근거 |
|---|---|---|
| recent3/5 race-time median | `EXCLUDE` | 거리별 총 경주 길이가 달라 절대시간의 물리적 비교가 성립하지 않음 |
| recent3/5 race-time count | `KEEP_AS_IS` | 성능값이 아닌 유효 관측 깊이; 거리·경마장 혼합이 의미를 훼손하지 않음 |
| recent3/5 S1F median/count | `KEEP_AS_IS` | 양 경마장 모두 첫 200m, 초 단위; 거리별 pace 영향은 있으나 구간 정의는 동일 |
| recent3/5 G3F median/count | `KEEP_AS_IS` | 양 경마장 모두 마지막 600m로 정규화되고 누적↔직접값 관계 전수 일치 |
| recent3/5 G1F median/count | `KEEP_AS_IS` | 양 경마장 모두 마지막 200m로 정규화되고 누적↔직접값 관계 전수 일치 |

`SPLIT_BY_MEET`와 `CONDITION_ON_DISTANCE`는 현행 Feature의 논리적 오류를 고치기 위한 필수 판정으로
선택하지 않았다. 분포 차이만으로 Feature를 분리하면 이번 감사 범위를 넘어선 Feature engineering이 된다.

## 후속 speed Feature engineering 후보

- 동일 거리 또는 경마장×거리 조건의 race-time 요약
- 경마장×거리 기준 상대 race time 또는 speed figure
- 거리·주로·함수율을 고려한 sectional 상대값
- S1F와 G3F/G1F의 조합을 이용한 pace profile

이 후보는 새 Feature 버전에서 설계하고 ablation으로 평가한다. official baseline v2에는 추가하지 않는다.

## 재현 산출물

- `data/exports/validation/official_place_baseline_v2_speed_sectional_audit/feature_lineage_and_verdict.csv`
- `data/exports/validation/official_place_baseline_v2_speed_sectional_audit/profile_by_meet.csv`
- `data/exports/validation/official_place_baseline_v2_speed_sectional_audit/profile_by_distance.csv`
- `data/exports/validation/official_place_baseline_v2_speed_sectional_audit/profile_by_meet_distance.csv`
- `data/exports/validation/official_place_baseline_v2_speed_sectional_audit/summary.json`
- 생성기: `scripts/audit_speed_sectional_features_v2.py`

모델 학습, target 조회, Log Loss·Brier, Feature importance와 성능 기반 판단은 수행하지 않았다.
