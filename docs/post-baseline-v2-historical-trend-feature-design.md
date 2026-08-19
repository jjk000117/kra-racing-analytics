# Post-baseline v2 Historical Trend Feature 설계 감사

기준일: 2026-08-20  
상태: `T1` 논리 계약 봉인, Feature·Snapshot·모델 미구현

## 결론

현재 L133은 최근 경기력의 **수준**과 일부 rating·마체중의 **변화·변동성**은 이미 풍부하게 표현하지만,
F1 상대 경주기록과 S1F/G3F/G1F의 관측 순서를 이용한 명시적 방향은 표현하지 않는다. 첫 Trend 실험은
이 빈칸만 검증하도록 최근 5개 유효 관측의 경기 순서 OLS slope 4개로 제한한다.

- F1 time percentile slope 1개
- S1F/G3F/G1F improvement slope 3개
- 최소 유효 관측 3개, 부족하면 NULL
- 기존 count companion을 재사용하며 새 count나 availability flag를 만들지 않음
- rating, 착순·PLC, 마체중 Trend는 첫 bundle에서 제외

이 설계는 target이나 모델 성능을 사용하지 않았다. 허용된 development 현재행
`2023-01-01 <= race_date < 2024-07-01`만 대상으로 계산 가능률을 조사했고, 각 현재행의 원천은
`historical.race_date < feature_as_of`로 제한했다.

## 현재 133개가 표현하는 Trend 관련 정보

| 변수군 | 현재 수준 | short/long을 통한 간접 Trend | 명시적 변화 | 명시적 순서·방향 | 변동성 |
|---|---|---|---|---|---|
| Rating | current, prior mean, last, recent3/5/10 mean | recent3/5/10 level 비교 가능 | last 대비 current, recent3/5/10 endpoint change | window의 최초·최종만 사용하며 중간 순서는 미반영 | 없음 |
| 착순·PLC/Top3 | prior 및 recent3/5/10 rate·평균·best | 여러 window level 차이로 간접 추론 | 없음 | 없음 | prior finish-rank std |
| Race time/F1 | F1 recent3/5 median advantage·percentile | recent3 대 recent5 비교 가능 | 없음 | 없음 | 없음 |
| S1F/G3F/G1F | recent3/5 median과 count, F3 current-field percentile | recent3 대 recent5 비교 가능 | 없음 | 없음 | 없음 |
| 마체중 | current, last, recent5 mean | current/last/mean 비교 가능 | current change, last historical change | 연속 관측 방향은 없음 | recent5 std |
| 관계 이력 | 말·기수·조교사·마주·pair의 prior/recent rate와 count | prior/recent 비교 가능 | 없음 | 없음 | 없음 |

확인된 명시적 rating change는 단순 slope가 아니다. 구현은 window 안의 `arg_max(rating, race_date) -
arg_min(rating, race_date)`로 최신값과 최초값의 차이를 계산한다. 따라서 방향은 있지만 중간 관측을
사용하지 않는다. 이것만으로도 첫 실험에서 rating slope를 또 추가할 필요성은 낮다.

## Trend 정의 비교

| 방식 | 측정 대상과 경마적 의미 | 최소 관측 | 불규칙 출전 간격·이상치 | 기존 입력과 중복 | 첫 실험 판단 |
|---|---|---:|---|---|---|
| 최근 N경기 linear slope | 관측 순서를 모두 사용한 경기당 개선·악화 방향 | 3 | sequence 축은 휴양기간을 무시; endpoint 차이보다 단일 이상치 영향이 분산됨 | rating에는 높고 F1/sectional에는 낮음 | 채택 |
| 최신값-이전 평균 | 최근 한 경기가 종전 수준에서 얼마나 벗어났는지 | 2~3 | 최신 한 건 이상치에 매우 민감 | recent level·current/last와 중복 큼 | 제외 |
| short-long level gap | 최근 수준이 장기 수준보다 좋아졌는지 | 각 window의 유효 관측 | 시간 순서를 직접 쓰지 않고 겹치는 window 상관이 큼 | recent3/5/10이 이미 제공됨 | 제외 |
| 최초값-최신값 | endpoint 방향 | 2 | 중간 경로를 버리고 두 endpoint 이상치에 민감 | rating change와 동일 계열 | 제외 |
| 연속 개선/악화 횟수 | streak와 단조 방향 | 2 이상 | 작은 기록 오차에도 streak가 끊기며 N이 작을 때 불안정 | binary outcome rate와 중복 가능 | 후순위 |
| 최근 N variability | 안정성·기복 | 2 | 이상치에 민감하고 방향은 없음 | finish-rank std, weight std가 일부 보유 | 첫 Trend 질문과 달라 제외 |

모든 방식은 과거 event만 사용하면 PIT-safe하다. 첫 slope의 시간축은 실제 경과일이 아니라
`x=0,1,...,n-1`의 출전 순서를 사용한다. 성과가 발생하는 기회가 경주 단위이고, 일수 축은 휴양·출전
빈도를 slope에 섞으며 `horse_days_since_last_start`와 중복되기 때문이다. 따라서 결과는
`per start`로만 해석한다. 실제 일수 slope는 후속 민감도 후보이지 첫 bundle의 병렬 후보가 아니다.

## 변수군별 적합성

### Rating

Rating의 상승·하락은 의미가 있지만 현재 133개에 current/last/mean과 세 window의 endpoint change가
이미 있다. OLS rating slope는 중간 경로를 더 쓰지만 같은 개념을 반복하므로 첫 bundle에서 제외한다.

### Finish / PLC / Top3

Raw 착순 slope는 출전두수와 상대 수준에 좌우된다. PLC/Top3는 짧은 window에서 이산적인 0/1열이라
streak와 slope가 불안정하며 recent3/5/10 rate와도 겹친다. field-size 보정 finish percentile은 더
타당할 수 있으나, 이는 새 상대 outcome 표현과 Trend를 동시에 바꾸므로 Trend 자체 효과를 분리하려는
첫 실험에서는 제외한다.

### F1 race-relative performance

`time_percentile`은 과거 같은 경주의 유효 완주마 사이 위치를 0~1로 표준화하므로 서로 다른 거리와
두수의 절대 race time보다 Trend에 적합하다. 현재 recent3/5 median은 수준만 표현하므로 recent5
slope는 순서라는 새 정보를 추가한다. `time_advantage` slope도 가능하지만 percentile과 같은 원천의
유사 방향을 중복하므로 제외한다.

### Sectional

S1F/G3F/G1F는 고정 물리구간의 초 단위라 절대 race time보다 순서 Trend에 적합하다. 다만 거리,
경마장, 주로, 전개 영향은 남으므로 이를 순수 능력 향상으로 단정하지 않는다. 현재 median과 field
percentile은 수준·오늘 상대 위치만 제공하므로 각 구간의 slope는 명시적 방향을 추가한다. 세 구간은
초반, 종반 600m, 마지막 200m라는 서로 다른 역할이어서 첫 bundle에서 유지한다.

### 마체중과 기타 반복 측정값

마체중 방향은 경기력 개선 방향과 같지 않으며 current/last change, recent5 mean/std가 이미 존재한다.
관계 주체의 rate Trend는 선수·조교사 구성 변화와 작은 표본 문제를 함께 섞는다. 첫 Trend 질문을
명확히 유지하기 위해 모두 제외한다.

## 봉인 제안: T1 4개

유효 관측을 오래된 순서로 `i=0,...,n-1`, 값은 `y_i`라 한다. 최근 최대 5개를 사용하며
`n>=3`일 때만 다음 OLS slope를 계산한다.

`beta = sum((i-mean(i))*(y_i-mean(y))) / sum((i-mean(i))^2)`

| Feature | 계산 | 방향·단위 | 기존 Feature와 차이 |
|---|---|---|---|
| `horse_recent5_race_time_percentile_trend_per_start` | F1 time percentile의 `beta` | 양수=상대 경기력 개선, percentile/start | recent3/5 median에 없는 순서 |
| `horse_recent5_s1f_improvement_trend_seconds_per_start` | S1F seconds의 `-beta` | 양수=초반 200m 빨라짐, sec/start | S1F median·field 위치에 없는 방향 |
| `horse_recent5_g3f_improvement_trend_seconds_per_start` | G3F seconds의 `-beta` | 양수=종반 600m 빨라짐, sec/start | G3F median·field 위치에 없는 방향 |
| `horse_recent5_g1f_improvement_trend_seconds_per_start` | G1F seconds의 `-beta` | 양수=마지막 200m 빨라짐, sec/start | G1F median·field 위치에 없는 방향 |

각 metric은 자신의 최신 5개 **유효 metric 관측**을 사용한다. DNS·취소·실격·주행중지와 기존
비정상 결과는 성과 관측에서 제외한다. 그 사건을 0으로 넣지 않는다. `n<3`은 실제 변화 0이 아니라
계산 불가이므로 NULL이다. 기존 recent5 count가 표본 깊이를 이미 제공하므로 신규 count와 missing
indicator는 만들지 않는다.

## Development 가용성

가용률은 target을 읽지 않고 28,392행·2,675경주의 development 현재행에서 계산했다. 2022 이력은
각 2023~2024-H1 행보다 과거인 경우 warm-up 원천으로만 사용했다.

| Metric | 2023 가용 | 2024-H1 가용 | recent5 count P25/median/P75 |
|---|---:|---:|---:|
| F1 time percentile | 15,327/18,911 (81.05%) | 8,178/9,481 (86.26%) | 2023: 3/5/5; 2024-H1: 4/5/5 |
| S1F | 15,327/18,911 (81.05%) | 8,178/9,481 (86.26%) | 동일 |
| G3F | 15,327/18,911 (81.05%) | 8,178/9,481 (86.26%) | 동일 |
| G1F | 15,327/18,911 (81.05%) | 8,178/9,481 (86.26%) | 동일 |

여기서 가용은 최근 5개 window 안에 유효 관측이 최소 3개라는 뜻이다. 네 metric의 가용성이 현재
원천에서는 일치했지만 구현 계약은 metric별 독립 count를 유지한다. 데이터가 바뀌어 하나의 구간만
결측일 수 있기 때문이다. 2023에서 2024-H1로 가용률이 높아지는 것은 warm-up 이후 이력 성숙과
일치한다. 이 차이를 0으로 대체하지 않는다.

## PIT·leakage 계약

1. 모든 원천은 `historical.race_date < feature_as_of`를 만족한다.
2. 현재 경주의 착순, `place_hit`, race time, sectional, 착차, 배당은 참조하지 않는다.
3. F1은 기존 정상 완주·유효 시간·비교 가능 말 3두 이상 계약과 percentile 방향을 그대로 재사용한다.
4. Sectional은 기존 서울·부산경남 공통 semantic 정의와 정상 완주·유효값 계약을 재사용한다.
5. 정렬은 `race_date ASC, race_id ASC`로 결정론적으로 수행한다. 2024-07 이전 이력에서 동일 말의
   복수 경주가 같은 날짜에 존재한 사례는 0건이었다. 향후 발생하면 인위적인 순서를 학습하지 않도록
   해당 날짜의 관측을 제외하고 audit issue로 기록한다.
6. DNS·취소·실격·주행중지는 0이나 악화값으로 바꾸지 않고 해당 performance sequence에서 제외한다.

## 후속 실험 계약

- L133: 봉인된 Logistic + 현재 133
- LT1: 동일 Logistic + 현재 133 + T1 4개
- 동일 development 기간, 동일 4개 quarterly expanding fold, 동일 모집단·target·전처리·평가 함수
- T1 연속형은 fold Train median으로만 대체하고 scaling하며 NULL을 0으로 바꾸지 않음
- 판정은 기존 bundle 정책대로 Macro Log Loss와 Macro Brier의 평균 방향, 개선 fold 수, 변동성,
  calibration의 현저한 악화 여부를 함께 본다.
- 결과를 본 뒤 window, 최소 count, slope 축이나 bundle 구성을 바꾸지 않는다.
- Validation은 접근하지 않는다.

설계 blocker는 없다. 구현 단계에서 slope 수기 재계산, count/NULL 관계, recent window, 동일 날짜,
PIT source max date를 감사해야 한다.

## 사실·가설·후속 질문

### 현재 코드와 데이터에서 확인된 사실

- 133개는 rating endpoint 변화와 마체중 변화·변동성은 이미 포함한다.
- F1과 sectionals에는 recent3/5 level 및 count가 있지만 event order 기반 slope는 없다.
- T1 네 후보의 development 계산 가능률은 2023 81.05%, 2024-H1 86.26%다.
- 허용 범위의 과거 원천에서 동일 말·동일 날짜 복수 event는 0건이다.

### 아직 검증되지 않은 가설

- 최근 5회 F1 percentile 방향이 median 수준을 넘어 추가 정보를 준다.
- 초반·종반 sectional 방향이 현재 level과 field percentile을 넘어 추가 정보를 준다.
- sequence slope가 irregular elapsed-time을 무시해도 첫 Trend 검정에 충분히 안정적이다.

### 후속 모델 실험에서 검증할 질문

동일 Logistic·동일 temporal CV에서 T1 4개만 더했을 때 L133보다 Macro Log Loss와 Macro Brier가
여러 fold에서 반복 개선되는가? 개선되지 않으면 첫 Trend 경로는 DROP하고 정의를 사후 수정하지 않는다.
