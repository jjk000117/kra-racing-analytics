# Post-baseline v2 Aptitude Feature 설계 감사

## 결론

첫 Aptitude 실험은 7개 Feature로 구성한 `A1` bundle 하나만 사용한다. A1은 현재 137개가
직접 표현하지 않는 **동일등급 성과, 동일 주로상태 성과, 동일거리에서의 상대 경주력, 직전
출전 대비 거리 변화**를 추가한다. 함수율·날씨·과거 거리전환별 성과와 조건별 sectional은
첫 bundle에서 제외하거나 보류한다.

이번 단계에서는 Feature를 구현하거나 target과의 관계를 분석하지 않았다. Development current
rows인 `2023-01-01 <= race_date < 2024-07-01` 28,392행·2,675경주만 이용해 과거 관측의
계산 가능성을 확인했다.

## Worktree와 데이터 접근 감사

- Worktree: `C:\Users\jjk00\Documents\GitHub\kra-racing-analytics-plc`
- Branch: `plc-dev`
- 시작 HEAD: `ef6a38a8337cdbb4d91ce7e56514deeab3464b67`
- 공통 DB: `C:\Users\jjk00\Documents\GitHub\kra-racing-analytics\data\warehouse\kra.duckdb`
- `KRA_DATABASE_PATH`에 위 절대경로를 지정하고 `connect_database(..., read_only=True)`로
  28,392행·2,675경주를 정상 조회했다.

`KRA_DATABASE_PATH`는 데이터베이스 하나만 교체하고 `exports`는 현재 worktree root 아래를
사용하므로 파일 결과는 branch-local로 분리할 수 있다. 그러나 source DB와 writable experiment
DB를 별도 설정으로 표현하지는 못한다. `initialize_database`, Snapshot/Feature build 함수처럼
기본 write connection을 여는 코드를 공통 DB 경로와 함께 실행하면 공통 DB를 수정할 수 있다.

따라서 다음 구현은 공통 DB를 read-only connection으로만 조회하고 branch-local CSV/Parquet에
candidate를 저장해야 한다. 테이블이 꼭 필요하면 branch-local DuckDB를 만들고 공통 DB를
read-only로 attach하는 최소 분리가 선행돼야 한다.

## 현재 137개가 이미 표현하는 Aptitude 정보

| 영역 | 현재 수준/조건 | 말별 Historical aptitude | 상대/최근/변화 |
|---|---|---|---|
| 거리 | `distance_m` | 동일거리 count, finish/PLC rate, 평균착순 | 동일거리 PLC rate의 field percentile |
| 경마장 | `meet_code` | 동일 경마장 및 동일 경마장×거리 count/rate/평균착순 | 기수·조교사·말×기수의 동일 경마장 성적 |
| 주로 | 현재 주로상태·함수율 | 없음 | 없음 |
| 날씨 | 현재 날씨 | 없음 | 없음 |
| 등급 | 현재 등급과 상금·조건 | 없음 | rating 수준/변화는 있으나 동일등급 적성은 아님 |
| 속도 | 현재 거리와 최근 S1F/G3F/G1F | 동일거리 조건의 상대 경주력 없음 | F1 상대 경주력 recent3/5, field-relative sectional, T1 trend |
| 거리 변화 | 현재 거리 | 없음 | 직전 대비 연장·단축 크기 없음 |

T1 4개는 시간순 방향을 추가하지만 조건별 aptitude를 추가하지 않는다. 현재 Feature는 경마장과
거리 aptitude는 상당 부분 보유하지만 등급·주로상태·거리 변화 및 조건부 상대 경주력은 비어 있다.

## 후보 검토

| 후보 | 판단 | 근거 |
|---|---|---|
| 동일등급 count/PLC rate | 채택 | 현재 grade와 전체 성적의 단순 합으로는 같은 등급에서의 반복 성과를 직접 표현하지 못함 |
| 동일 주로상태 count/PLC rate | 채택 | 현재 상태는 있으나 말별 해당 상태 성적이 없음; 공식 5개 범주로 해석 가능 |
| 함수율 근접 이력 | 보류 | ±5%p 관측 3회 이상은 63.07%지만 주로상태와 중복되고 근접 폭 선택이 임의적임 |
| 동일 날씨 성적 | 제외 | 관측 3회 이상은 64.46%지만 맑음이 76.84%로 대부분이며 주로상태보다 직접성이 낮음 |
| 동일거리 F1 percentile | 채택 | 기존 동일거리 PLC 결과와 달리 같은 거리에서의 상대 기록 수준을 표현함 |
| 유사거리(±200m) F1 | 제외 | 가용성은 높지만 거리 경계가 임의적이며 정확한 동일거리 정의보다 해석이 약함 |
| 직전 대비 거리 변화 | 채택 | 현재 거리와 동일거리 history로 표현되지 않는 당일 연장·단축 부담을 직접 표현함 |
| 과거 연장/단축 후 PLC rate | 보류 | transition 방향×크기×결과로 표본이 분할되고 grade/meet 변화가 함께 섞임 |
| 동일등급 전환/승급·강급 | 보류 | 국산/혼합/OPEN을 포함한 grade의 전역 순서 계약이 먼저 필요함 |
| 조건별 sectional | 보류 | Aptitude보다 별도 speed/pace 연구에 가까우며 조건별 표본 희소성이 큼 |
| 동일 경마장/경마장×거리 | 중복 제외 | 기존 137개에 이미 count/rate/평균착순이 존재함 |

## 봉인할 A1 Feature 계약

모든 집계의 current grain은 `(race_id, horse_id)`이고 과거 후보는 동일 `horse_id`에서
`historical.race_date < feature_as_of`를 만족하는 기존 유효 출전 모집단이다.

| Feature | 정확한 계산 | 최소 관측 및 NULL | 단위/방향 |
|---|---|---|---|
| `horse_same_grade_start_count` | `historical.race_grade = current.race_grade`인 과거 출전 수 | 0 허용 | 회 |
| `horse_same_grade_plc_hit_rate` | 동일등급 과거 `place_hit` 합 / count | count 3 미만이면 NULL | 0~1, 높을수록 우수 |
| `horse_same_track_condition_start_count` | 과거 `track_condition = current.track_condition`인 출전 수 | 현재 상태 NULL이면 0, 그 외 0 허용 | 회 |
| `horse_same_track_condition_plc_hit_rate` | 동일 주로상태 과거 `place_hit` 합 / count | 현재 상태 NULL 또는 count 3 미만이면 NULL | 0~1, 높을수록 우수 |
| `horse_same_distance_race_time_percentile_count` | 동일거리 과거 F1 `time_percentile` 유효 관측 수 | 0 허용 | 회 |
| `horse_same_distance_race_time_percentile_median` | 위 관측의 전체 historical median | count 3 미만이면 NULL | 0~1, 높을수록 우수 |
| `horse_distance_change_from_last_start_m` | 현재 거리 − 가장 최근 과거 유효 출전 거리 | 과거 출전이 없으면 NULL | m, 양수=연장·음수=단축 |

Rate/median의 최소 3회 규칙은 1~2회 우연을 aptitude로 직접 해석하지 않기 위한 계약이다.
실제 count는 0으로 숨기지 않고 companion으로 함께 제공한다. 연속형 결측은 후속 모델의 fold
Train median으로만 대체하며, count는 관측 수 자체이므로 0을 유지한다. 신규 missing indicator나
shrinkage는 첫 실험에 추가하지 않는다.

F1 `time_percentile`은 기존 계약을 그대로 재사용한다. 정상 실제 출전·완주, 유효 race time,
경주 내 비교 가능 완주마 3두 이상, average-rank tie 처리, `0=열위 / 1=우위`다.

## Development-only 가용성

| 값 Feature의 source count | 1회 이상 | 3회 이상 | count 중앙값 | P75 | 최대 |
|---|---:|---:|---:|---:|---:|
| 동일등급 | 80.49% | 50.95% | 3 | 6 | 47 |
| 동일 주로상태 | 73.71% | 39.13% | 2 | 4 | 31 |
| 동일거리 F1 percentile | 74.24% | 42.26% | 2 | 4 | 40 |

| Source count | 2023 3회 이상 | 2024-H1 3회 이상 |
|---|---:|---:|
| 동일등급 | 49.34% | 54.17% |
| 동일 주로상태 | 37.61% | 42.16% |
| 동일거리 F1 percentile | 41.81% | 43.16% |

직전 거리 관측은 94.40%에서 가능했다. 거리 변화 분포는 P5 -200m, 중앙값 0m, P95 +300m이며
동일거리 46.78%, 연장 31.99%, 단축 21.23%였다.

보조 검토에서 함수율 ±5%p 관측 3회 이상은 63.07%, 동일 날씨는 64.46%, 유사거리 F1은
73.95%였다. 가용성이 높더라도 중복·정의 임의성 때문에 A1에는 넣지 않았다.

## PIT와 Leakage 계약

- 모든 과거 event는 `historical.race_date < feature_as_of`여야 한다.
- 현재 경주의 결과·착순·race time·sectional·`place_hit`·배당·매출을 사용하지 않는다.
- 과거 `place_hit`와 F1 percentile은 확정된 historical 결과로만 사용한다.
- 같은 날짜 event는 현재 event보다 과거라고 가정하지 않고 제외한다.
- most-recent distance tie-break는 `race_date DESC, race_id DESC`로 결정한다.
- DNS·취소·실격·주행중지는 기존 Snapshot 모집단 및 historical metric 정책을 그대로 따른다.
- API26/API37의 현재 누적값은 사용하지 않는다.

## 후속 실험 계약

다음 구현·감사를 통과한 뒤 단 하나의 비교만 수행한다.

- Control: `LT1 = Logistic + 기존 137`
- Candidate: `LA1 = Logistic + 기존 137 + A1 7 = 144`
- 동일 target, 모집단, Logistic 설정, 4개 development temporal fold, Train-only preprocessing
- raw probability의 Macro Log Loss와 Macro Brier를 주 지표로 사용
- 두 평균 지표의 방향, fold 반복성, calibration의 현저한 악화 여부를 기존 bundle 정책으로 판단
- A1 결과를 본 뒤 정의·최소 count·조건을 소급 변경하지 않음

## Blocker와 다음 단계

Feature 정의·PIT·개발기간 가용성 측면의 blocker는 없다. 구현 전 기술 blocker는 공통 DB write
방지다. 다음 단계에서 source read-only와 branch-local artifact write를 코드 수준에서 분리하고
이를 테스트한 뒤 A1을 구현해야 한다.

이번 설계는 L133+sigmoid의 official 지위, LT1의 development KEEP, Validation ledger 및 기존
sealed artifact를 변경하지 않는다.

## 확인된 사실, 가설, 후속 질문

### 현재 코드와 데이터에서 확인된 사실

- 현재 137개에는 동일거리·동일경마장·동일경마장×거리 history가 있지만 동일등급·동일
  주로상태 aptitude와 거리 변화는 없다.
- A1 핵심 rate/median은 최소 3회 규칙에서 39.13~50.95%가 계산 가능하다.
- 공통 DB는 PLC worktree에서 read-only 조회 가능하지만 source/write DB 설정은 분리돼 있지 않다.

### Aptitude에 대한 아직 검증되지 않은 가설

- 같은 등급 및 같은 주로상태에서의 반복 성과가 전체 성적과 현재 조건을 넘어 추가 정보를 준다.
- 동일거리 F1 percentile은 동일거리 PLC rate와 다른 수행 품질을 표현한다.
- 직전 대비 거리 변화가 연장·단축 적응 부담을 일부 표현한다.

### 후속 모델 실험에서 검증해야 할 질문

- A1 7개가 LT1보다 두 primary probability loss를 여러 temporal fold에서 반복해 낮추는가?
- 낮은 가용성, 특히 동일 주로상태 3회 이상 39.13%에서도 추가 정보가 유지되는가?
- 개선이 특정 Feature 하나나 특정 fold에만 의존하지 않는가?
