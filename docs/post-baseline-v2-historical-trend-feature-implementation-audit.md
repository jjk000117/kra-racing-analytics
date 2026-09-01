# Historical Trend T1 구현·데이터 감사

기준일: 2026-09-01  
상태: T1 4개 구현 및 development 데이터 감사 완료, 모델 미실행

## 기술 요약

봉인된 T1 4개를 기존 L133 engineered Snapshot을 변경하지 않는 별도 candidate로 구현했다.
`mart.place_feature_snapshot_v2_trend_candidate`는 development 기간 28,392행·2,675경주이며 기존
engineered Snapshot의 모든 열 뒤에 T1 4개만 계약 순서대로 추가한다. T1 가용률은 네 Feature 모두
82.79%였다.

PIT·시간순서·recent5·NULL·NaN/Inf 감사 위반은 모두 0건이었다. 실제 24개 표본을 독립 OLS로
재계산한 최대 절대오차는 `4.44e-15`였다. 기존 `horse_recent5_s1f_count`와 T1의 엄격한 정상 완주
S1F 관측 수가 6행에서 달랐지만, 이는 계산 오류가 아니라 기존 count가 S1F 값이 남은 주행중지
event를 포함하는 정의 차이다. T1은 봉인 계약대로 해당 event를 제외한다.

## 구현 계약

각 현재행에서 `historical.race_date < feature_as_of`인 metric별 유효 event를 최신순으로 최대 5개
고른 뒤, 다시 과거→최근으로 정렬하여 `x=0,...,n-1`을 부여한다. `n>=3`에서만 다음을 계산한다.

`beta = sum((x-x_mean)*(y-y_mean)) / sum((x-x_mean)^2)`

| Feature | 계산 | 방향·단위 |
|---|---|---|
| `horse_recent5_race_time_percentile_trend_per_start` | `beta(F1 time_percentile)` | 양수=상대 경기력 개선, percentile/start |
| `horse_recent5_s1f_improvement_trend_seconds_per_start` | `-beta(S1F seconds)` | 양수=초반 200m 빨라짐, sec/start |
| `horse_recent5_g3f_improvement_trend_seconds_per_start` | `-beta(G3F seconds)` | 양수=종반 600m 빨라짐, sec/start |
| `horse_recent5_g1f_improvement_trend_seconds_per_start` | `-beta(G1F seconds)` | 양수=마지막 200m 빨라짐, sec/start |

F1은 기존 정상 완주·유효 race time·비교 가능 완주마 3두 이상 percentile을 재사용한다. Sectional도
기존 서울/부산경남 공통 semantic seconds를 사용하되 정상 완주와 유효 metric을 요구한다. DNS,
취소, 실격, 주행중지는 sequence에 넣지 않는다. 관측이 3개 미만이면 0이 아니라 NULL이다.

## Candidate 구조와 접근 범위

- candidate: `mart.place_feature_snapshot_v2_trend_candidate`
- 원천 추적: `quality.post_baseline_v2_trend_source_audit`
- 현재행: 2023-01-06~2024-06-30
- 행/경주: 28,392 / 2,675
- 기존 L133: 133개, hash `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`
- T1: 4개, hash `b19df94b43b9f81b2b711fc9ed84c6e7af3c91b89eb2bcc761ac9fa0aa4fa63b`

현재행은 development 경계 이전만 적재했다. Historical warm-up을 포함한 과거 event를 조회했지만
각 현재행보다 과거인 원천만 저장했다. Target, prediction, 모델 평가 지표는 계산하지 않았다.

## 가용성

네 metric은 현재 원천에서 같은 유효 관측 가용성을 보였다. 정의는 metric별로 독립되어 있으므로
향후 결측 구조가 달라져도 하나의 count로 합치지 않는다.

| 구간 | 행 수 | non-null | 가용률 |
|---|---:|---:|---:|
| 전체 development | 28,392 | 23,505 | 82.79% |
| 2023 | 18,911 | 15,327 | 81.05% |
| 2024-H1 | 9,481 | 8,178 | 86.26% |

| Development evaluation fold | 행 수 | non-null | 가용률 |
|---|---:|---:|---:|
| fold 1: 2023-Q3 | 4,458 | 3,534 | 79.27% |
| fold 2: 2023-Q4 | 5,229 | 4,055 | 77.55% |
| fold 3: 2024-Q1 | 4,707 | 3,892 | 82.69% |
| fold 4: 2024-Q2 | 4,774 | 4,286 | 89.78% |

가용성은 이력 성숙과 함께 대체로 증가하지만 fold 2가 fold 1보다 낮다. 이는 오류로 보지 않으며,
LT1 실험에서 결측을 fold Train median으로만 처리한다. 계산 불가를 0으로 바꾸지 않는다.

## 분포

| Feature | Min | P01 | P05 | P25 | Median | P75 | P95 | P99 | Max | Mean | SD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F1 percentile trend | -0.500 | -0.250 | -0.176 | -0.071 | 0.000 | 0.068 | 0.175 | 0.273 | 0.500 | -0.001 | 0.109 |
| S1F improvement | -1.150 | -0.340 | -0.200 | -0.080 | -0.010 | 0.060 | 0.190 | 0.340 | 1.650 | -0.011 | 0.128 |
| G3F improvement | -7.630 | -1.550 | -0.940 | -0.390 | -0.080 | 0.220 | 0.730 | 1.270 | 7.300 | -0.088 | 0.546 |
| G1F improvement | -4.540 | -0.700 | -0.420 | -0.160 | -0.020 | 0.120 | 0.370 | 0.650 | 4.050 | -0.022 | 0.257 |

단위는 F1이 percentile/start, sectional이 seconds/start다. F1의 ±0.5는 3개 관측의 가능한 강한
방향 사례다. Sectional 극단값은 clipping하지 않았다.

## 극단값 원천 추적

가장 큰 G3F/G1F 악화는 말 `0046627`의 2024-06-29 현재행에서 발생했다. 최근 원천 중
2024-05-12 서울 1,800m 경주는 공식 `FINISHED`, 15위였고 Raw `rcTime=152.9`,
`seG3fAccTime=79`, `seG1fAccTime=118.1`이었다. 기존 semantic 정의로 G3F `73.9`, G1F `34.8`이
정확히 재현된다. 매우 느린 완주기록이지만 파싱·PIT·계산 오류는 아니다.

가장 큰 G3F 개선 사례의 원천인 2023-06-10 서울 1,000m 9위 기록도 Raw `rcTime=76.7`,
`seG3fAccTime=25.1`에서 G3F `51.6`으로 정확히 계산됐다. G1F 개선 극단의 2023-07-30 부산경남
1,200m 11위 기록은 API 직접 구간값 G3F `51.1`, G1F `22.1`이었다. 모두 정상 완주 원문이며,
성능을 보기 전에 winsorization이나 clipping을 도입하지 않는다.

이 값들은 거리·경마장·주로·전개를 보정하지 않은 sequence slope라는 T1의 한계를 보여준다.
극단값이 실제 관측이라는 사실은 T1이 순수 능력 Trend라는 뜻이 아니라 조건과 전개 영향을 포함할 수
있다는 뜻이다.

## 감사 결과

| 검사 | 결과 |
|---|---:|
| Registry/구현 이름·순서 불일치 | 0 |
| 신규 Feature 중복 | 0 |
| Candidate 업무키 중복 | 0 |
| `historical.race_date >= feature_as_of` | 0 |
| 동일 말·동일 날짜 복수 Historical event | 0 |
| recent5 초과·sequence ordering 위반 | 0 |
| 실제 count <3인데 값 존재 | 0 |
| 실제 count >=3인데 NULL | 0 |
| NaN/Inf | 0 |
| 독립 재계산 불일치 (`abs error > 1e-12`) | 0/24 |
| 최대 독립 재계산 절대오차 | `4.44e-15` |

수기 표본은 metric별 정확히 3·4·5개 관측, 양수·음수·평평한 사례를 포함한다. 저장된
`historical_race_date`, 원본 값, `sequence_index`, 독립 slope와 저장값은
`independent_slope_recalculation_samples.csv`에 남겼다. 실제 사례와 단위 테스트 모두 F1 상승은
양수, F1 하락은 음수, sectional seconds 감소는 양수, 증가는 음수임을 확인했다.

## 기존 companion count의 6행 차이

T1 실제 유효 count와 기존 companion의 불일치는 S1F 6행뿐이다. 원인은 기존 Snapshot의 sectional
count가 `is_valid_start` 이후 non-null S1F를 집계하지만 T1은 봉인 계약에 따라 정상 완주만 허용하기
때문이다. 예를 들어 말 `0044513`의 2022-01-22 주행중지 event에는 S1F `16.0`이 남아 있어 기존
count에는 들어가지만 T1 sequence에서는 빠진다.

- 영향 행: 6/28,392 = 0.021%
- F1/G3F/G1F companion 차이: 0
- 이 차이 때문에 잘못 생성된 T1 값: 0
- 기존 count 또는 기존 133개 수정: 수행하지 않음

한 행은 기존 S1F count가 3이지만 T1 실제 count는 2라 Trend가 NULL이다. 이는 이유 없는 NULL이
아니며 quality audit table과 mismatch CSV로 추적 가능하다. 기존 count 정의를 소급 변경하거나 T1에
신규 count를 추가하지 않는다는 봉인 계약을 유지한다. LT1에서 이 알려진 미세한 정의 차이를
limitation으로 기록하면 되며 개발 실험 blocker로 보지 않는다.

## 보호 및 다음 단계 준비 상태

기존 133개 Feature 목록·순서·hash, F1/F3 구현, 기존 Snapshot, baseline run contract/refit,
Validation 계약·ledger, PROMOTE, M1/H133/RA1 결과 파일의 작업 전후 SHA256은 모두 동일했다.
Validation ledger는 model-selection 1회와 descriptive reaccess 1회 상태 그대로다.

모델 학습, prediction, target 기반 분석, Validation 재접근, 2024-07 이후 평가를 수행하지 않았다.
T1 구현·감사 관점의 blocker는 없다. 다음 작업은 별도 승인 후 동일 Logistic·동일 4개 development
fold에서 `L133`과 `L133+T1`만 비교하는 것이다.

## 재현 산출물

`data/exports/validation/post_baseline_v2_historical_trend/`에 다음을 저장한다.

- `audit_summary.json`
- `feature_profile_overall.csv`
- `feature_profile_by_year.csv`
- `feature_profile_by_development_fold.csv`
- `observation_count_distribution.csv`
- `companion_count_mismatches.csv`
- `independent_slope_recalculation_samples.csv`
- `extreme_value_source_trace.csv`
