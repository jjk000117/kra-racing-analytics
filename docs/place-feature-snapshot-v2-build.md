# Place Feature Snapshot v2 candidate 구현·감사

기준일: 2026-08-12  
상태: Snapshot 생성 및 데이터 계약 감사 완료, 모델 미학습

## 결과

- Snapshot: `mart.place_feature_snapshot_v2_candidate`
- Grain: 경주 × 유효 출전마
- 업무키: `race_id + horse_id`
- Feature: 125개
- 행: 48,524개
- 경주: 4,582개
- PLC 양성: 13,740개
- 첫 전체 빌드 시간: 약 192초

기존 `place_feature_snapshot_v1`, `place_logistic_baseline_v1`, Validation 및 Final Test
산출물은 변경하거나 재평가하지 않았다.

## Registry 정정

기존 “즉시 후보 126개”는 고유 Feature 수가 아니라 중복 행을 포함한 수였다.

- 중복 5개: `horse_recent5_start_count`, `horse_recent5_finish_rate`,
  `horse_recent5_avg_finish_rank`, `horse_same_distance_start_count`,
  `horse_same_distance_plc_hit_rate`
- 원인: v1 승계 목록과 generic recent/condition 생성 루프가 같은 Feature를 각각 추가함
- 중복 제거 후 즉시 후보: 121개
- 추가한 companion count: `horse_recent3_g3f_count`, `horse_recent3_g1f_count`,
  `horse_recent5_g3f_count`, `horse_recent5_g1f_count`
- 최종 registry: 140개, 이름 중복 0개
- 상태: `APPROVED` 39, `APPROVED_WITH_FLAG` 86, `DEFERRED` 5,
  `PROHIBITED` 10
- 최종 즉시 구현 대상: 고유 Feature 125개

`horse_recent5_start_count`는 값 자체가 관측 깊이를 나타내는 count이므로
`APPROVED_WITH_FLAG`가 아닌 `APPROVED`로 정의를 바로잡았다.

## Sectional 공통화

공식 필드 의미와 저장값의 내부 관계를 기준으로 다음만 공통화했다.

| 공통값 | 서울 | 부산경남 |
|---|---|---|
| S1F | `seS1fAccTime` | `buS1fTime` |
| 최종 G3F | `rcTime - seG3fAccTime` | `bu_3fGTime` |
| 최종 G1F | `rcTime - seG1fAccTime` | `bu_1fGTime` |

부산경남 20,473개 유효 원천에서 `rcTime - buG3fAccTime = bu_3fGTime`과
`rcTime - buG1fAccTime = bu_1fGTime`의 최대 절대 오차는 모두 0.0초였다.
서울 변환은 정상 완주 대부분에서 물리적으로 타당한 범위였으며, 소수의 긴 기록은
원천에 그대로 존재하므로 자동 삭제하지 않았다.

`bu_10_8fTime`, `bu_8_6fTime`, `bu_6_4fTime`, `bu_4_2fTime`, 코너 누적기록과
통과순위는 서울과 동일 정의의 공통 원천이 없거나 거리별 구조가 다르므로 이번
공통 Feature에 합치지 않았다. 이들은 경마장 전용 또는 후속 전개 Feature 대상이다.

## 원천 가용성

정상 완주 기준 가용성은 다음과 같다.

| 경마장 | 정상 완주 | race time | S1F | G3F | G1F |
|---|---:|---:|---:|---:|---:|
| 서울 | 27,995 | 27,995 | 27,915 | 27,915 | 27,915 |
| 부산경남 | 20,473 | 20,473 | 20,473 | 20,473 | 20,473 |

서울 S1F/G3F/G1F의 정상 완주 가용률은 99.71%, 부산경남은 100%다.
관측된 모든 `meet × distance_m` 조합에 공통 원천이 존재했다. 특정 거리 전체가
구조적으로 비어 있는 사례는 없었다. 경마장 전용 raw 필드가 반대 경마장에서 NULL인
것은 구조적 미존재이며, 공통화한 컬럼의 개별 NULL은 결과 미기록으로 구분한다.

상세 거리별 수치는
`data/exports/validation/place_feature_snapshot_v2_candidate/source_sectional_by_meet_distance.csv`에
보존했다.

## Snapshot 가용성

| Feature | non-null | null | 가용률 |
|---|---:|---:|---:|
| 현재 마체중 | 48,524 | 0 | 100.00% |
| 현재 마체중 증감 | 45,129 | 3,395 | 93.00% |
| 날씨·주로·함수율 | 48,524 | 0 | 100.00% |
| 최근 5회 race time 중앙값 | 43,541 | 4,983 | 89.73% |
| 최근 5회 S1F 중앙값 | 43,543 | 4,981 | 89.73% |
| 최근 5회 G3F 중앙값 | 43,541 | 4,983 | 89.73% |
| 최근 5회 G1F 중앙값 | 43,541 | 4,983 | 89.73% |

속도 Feature의 NULL은 주로 과거 이력 부족이다. companion count가 0이면 값은 NULL이며,
과거 출전은 있지만 해당 기록만 없는 경우에는 start count와 sectional count의 차이로
식별할 수 있다. Feature별 전체 결과와 Snapshot의 `meet × distance_m` 가용성은 validation
CSV에 보존했다.

## PIT·leakage 감사

- 업무키 중복: 0
- 원천 모집단과 Snapshot 행 차이: 0
- `source_max_event_date >= feature_as_of`: 0
- Historical join은 모두 `historical.race_date < current.race_date`
- 동일 날짜의 다른 경주 결과 사용 금지 유지
- 현재 경기 착순·경주기록·sectional·착차·배당·매출 입력: 0개
- API26/API37 누적값 입력: 0개
- 현재 결과 상태는 모집단·타깃·감사 컬럼으로만 보존

현재 날씨·주로·함수율·마체중은 기존 사전 이용 가능성 검증에 따라 입력에 포함했다.
다만 과거 API 응답에 정확한 공개 timestamp가 없으므로 당시 경주 전 공개정보의
historical representation으로 간주한다는 제한이 남는다.

## 구조·값 감사

- recent3 ≤ recent5 ≤ recent10 count 위반: 0
- 동일거리 count > 전체 prior count: 0
- history availability와 실제 count/value 모순: 0
- rate 정의 및 0~1 범위 위반: 0
- sectional count=0인데 값 존재: 0
- 부산경남 누적/직접 G3F·G1F 관계 위반: 0

현재 표본에서 다음 companion count들은 값이 완전히 같았다.

- recent3/recent5의 race time, G3F, G1F count
- `horse_recent5_start_count`와 `horse_recent5_weight_count`

이는 현재 유효 이력에서 해당 원천 가용성이 거의 완전하기 때문이며 정의상 같은
Feature는 아니다. 향후 결측이 생기면 달라지고 각각의 missingness를 설명하므로 이번
단계에서는 제거하지 않는다. 성능이나 상관관계를 근거로 한 Feature 선택도 하지 않았다.

정상 완주 원천에서 S1F 범위 밖 1개, G3F 범위 밖 8개, G1F 범위 밖 14개를 진단용
휴리스틱으로 탐지했다. 일부는 매우 긴 경주기록과 함께 나타난 실제 원천값이다.
Snapshot의 최근 5회 중앙값 범위는 race time 59.2~158.0초, S1F 13.0~25.5초,
G3F 35.3~54.2초, G1F 11.7~22.9초였다. 이상값을 자동 삭제하지 않았다.

## 남은 제한과 다음 결정

- 과거 현재경주 정보의 정확한 공개 timestamp 부재
- 속도 절대값은 경마장·거리 차이를 포함하므로 모델 단계에서 조건 companion을 함께 사용
- 거리·주로·등급 보정 speed figure와 pace index는 후속 고도화
- 표본상 동일한 companion count를 모델 입력에서 유지할지는 모델링 전 구조 검토에서 결정

Snapshot 생성과 데이터 계약 감사 관점의 blocker는 없다. 다음 단계는 별도 official
baseline의 날짜 분할·전처리·모델 입력 계약을 설계하는 것이며, 아직 모델 학습은 하지 않았다.

## 재현 산출물

- `feature_availability.csv`
- `source_sectional_by_meet_distance.csv`
- `snapshot_sectional_by_meet_distance.csv`
- `feature_ranges.csv`
- `exact_duplicate_features.csv`
- `audit_summary.json`

모두 `data/exports/validation/place_feature_snapshot_v2_candidate/` 아래에 생성된다.
