# Post-baseline v2 Race-relative R1 구현·데이터 감사

기준일: 2026-09-09  
상태: R1 7개 구현 및 development 데이터 감사 완료, 성능 실험 미수행

## 결론

봉인된 R1 7개를 공통 DB의 `mart.place_feature_snapshot_v2_trend_candidate`에서 읽어 PLC branch-local
`mart.place_feature_snapshot_v2_relative_candidate`에 구현했다. Candidate는 development
28,392행·2,675경주이며 `LT1 137 + R1 7 = LR1 144` 입력 계약을 만족한다.

- R1 hash: `f058c627fb68960803ed88adf450e67796fc2df25e8ad8854c372374d8875539`
- LR1 hash: `7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a`
- LT1 hash: `1dcf5f5a630d67f216fa6dc27932d2c6532ec0a50af6360b7521917682f802e8`
- 업무키·PIT·NULL·범위·round-trip·수기 재계산 감사 이슈: 0건
- 모델 학습·prediction·target 성능·Validation 접근: 없음

## 구현 lineage

모든 source는 기존 LT1의 `DOUBLE` Historical Feature이며 원본 정의를 바꾸지 않았다. Source가 NULL이면
R1도 NULL이고, 같은 현재 경주의 non-null source가 3두 미만이면 R1도 NULL이다.

| R1 | Existing absolute source | 기존 companion / NULL 의미 | 방향·PIT |
|---|---|---|---|
| `horse_same_meet_plc_hit_rate_field_percentile` | `horse_same_meet_plc_hit_rate` | `horse_same_meet_start_count`; 해당 경마장 과거 이력 없음 | 높을수록 우위; 과거 event만 사용 |
| `horse_same_meet_distance_plc_hit_rate_field_percentile` | `horse_same_meet_distance_plc_hit_rate` | `horse_same_meet_distance_start_count`; 결합조건 이력 없음 | 동일 |
| `jockey_same_meet_plc_hit_rate_field_percentile` | `jockey_same_meet_plc_hit_rate` | `jockey_same_meet_start_count`; 기수 해당 경마장 이력 없음 | 동일 |
| `trainer_same_meet_plc_hit_rate_field_percentile` | `trainer_same_meet_plc_hit_rate` | `trainer_same_meet_start_count`; 조교사 해당 경마장 이력 없음 | 동일 |
| `owner_prior_plc_hit_rate_field_percentile` | `owner_prior_plc_hit_rate` | `owner_prior_start_count`; 마주 이력/ID 없음 | 동일 |
| `horse_trainer_prior_plc_hit_rate_field_percentile` | `horse_trainer_prior_plc_hit_rate` | `horse_trainer_prior_start_count`; pair 이력/ID 없음 | 동일 |
| `horse_recent5_race_time_percentile_median_field_percentile` | `horse_recent5_race_time_percentile_median` | `horse_recent5_race_relative_time_count`; 유효 F1 과거시간 없음 | 높을수록 우위; 기존 F1 PIT 승계 |

구현은 기존 F3 `_higher_percentile` helper를 재사용한다. 유효 비교마 `n`, 오름차순 최소 rank `r`,
동률 수 `t`에 대해 `(r + (t-1)/2 - 1)/(n-1)`이며 0=열위, 1=우위다.

## Schema·key·보호 감사

| 항목 | 결과 |
|---|---:|
| Development 행 | 28,392 |
| Development 경주 | 2,675 |
| `(race_id, horse_id)` 중복 | 0 |
| LT1 입력 | 137 |
| R1 신규 | 정확히 7, registry 순서 일치 |
| LR1 입력 | 144, 이름 중복 0 |
| Existing F3 이름 중복 | 0 |
| Branch-local table round-trip 차이 | 0 |
| 기존 LT1 값 변경 | 0 |
| `source_max_event_date >= feature_as_of` | 0 |

공통 DB는 read-only 연결로만 사용했으며 작업 전후 SHA256은
`0F760634F63E8C4F606688202E41B2513735EB8A1122B4D586F64FC075E89E01`로 동일하다.
A1 audit/result, T1 registry/result, Validation contract/ledger/result, H133, RA1 보호 해시도 모두 동일했다.

## NULL·비교 가능 runner·tie 감사

| Feature source | source non-null | R1 non-null | 가용률 | tie 행 비율 | 계약 위반 |
|---|---:|---:|---:|---:|---:|
| horse same-meet PLC | 26,675 | 26,644 | 93.84% | 37.89% | 0 |
| horse same-meet-distance PLC | 20,955 | 20,821 | 73.33% | 60.02% | 0 |
| jockey same-meet PLC | 28,313 | 28,313 | 99.72% | 0.25% | 0 |
| trainer same-meet PLC | 28,368 | 28,368 | 99.92% | 14.00% | 0 |
| owner prior PLC | 28,311 | 28,311 | 99.71% | 6.25% | 0 |
| horse×trainer prior PLC | 26,129 | 26,098 | 91.92% | 39.98% | 0 |
| F1 recent5 percentile median | 26,801 | 26,770 | 94.29% | 20.98% | 0 |

각 Feature에서 source NULL인데 R1 존재, 비교마 3두 미만인데 값 존재, 비교마 3두 이상인데 이유 없는
NULL, NaN, ±Inf는 모두 0건이다. Same-meet-distance의 tie 60.02%는 작은 count의 이산 rate에서
예상되는 구조이며 average rank를 적용했다. 구현 후 Feature를 제거하거나 jitter를 추가하지 않았다.

## Percentile·분포 감사

모든 Feature의 min/max는 0/1이고 범위 위반은 0건이다. Percentile 특성상 경주별 평균은 0.5였다.

| Feature source | mean | std | P05 | P25 | median | P75 | P95 | exact 0 | exact 1 | unique values |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| horse same-meet | 0.500 | 0.303 | 0.000 | 0.250 | 0.450 | 0.778 | 1.000 | 5.94% | 8.27% | 118 |
| horse same-meet-distance | 0.500 | 0.298 | 0.063 | 0.250 | 0.444 | 0.778 | 1.000 | 2.92% | 7.65% | 104 |
| jockey same-meet | 0.500 | 0.317 | 0.000 | 0.222 | 0.500 | 0.778 | 1.000 | 9.37% | 9.44% | 87 |
| trainer same-meet | 0.500 | 0.317 | 0.000 | 0.222 | 0.500 | 0.778 | 1.000 | 8.53% | 8.80% | 138 |
| owner prior | 0.500 | 0.317 | 0.000 | 0.222 | 0.500 | 0.778 | 1.000 | 8.97% | 9.24% | 118 |
| horse×trainer prior | 0.500 | 0.303 | 0.000 | 0.250 | 0.450 | 0.778 | 1.000 | 5.36% | 8.35% | 128 |
| F1 recent5 percentile median | 0.500 | 0.317 | 0.000 | 0.222 | 0.500 | 0.778 | 1.000 | 8.92% | 8.77% | 130 |

Clipping과 winsorization은 수행하지 않았다.

## 독립 재계산

실제 development 경주에서 575개 runner-feature 행을 pandas average-rank 공식으로 독립 재계산했다.

- 실제 최소 field 8두, 중간 11두, 최대 16두 포함
- 비교 가능 runner 2두와 3두 포함
- tie와 source NULL 포함
- 최저 0, 최고 1 포함
- stored 대비 최대 절대오차: `0.0`

Development에는 등록두수 7두 경주가 없으므로 실제 표본은 만들 수 없었다. 대신 7두 synthetic 단위
테스트에서 `[1..7] -> [0, 1/6, ..., 1]`과 중간값 0.5를 확인했다. 이 부재는 구현 blocker가 아니다.

## Development 가용성 재현

설계 감사의 전체 가용률 73.33%~99.92%가 구현 결과에서 그대로 재현됐다.

- 4 evaluation fold 범위: same-meet 90.87~95.71%, same-meet-distance 70.58~79.37%,
  jockey 99.47~99.90%, trainer 99.75~99.98%, owner 99.51~99.83%, horse×trainer 88.07~93.95%,
  F1 recent5 91.21~96.31%
- 서울/부산경남: 각 Feature 차이는 0.96%p 이하이며 구조적 단절 없음
- field-size 13~16두는 경주 수가 매우 적어 개별 가용률을 일반화하지 않는다. 16두의
  same-meet-distance 가용률 44.24%는 별도 오류가 아니라 희소 표본과 source NULL의 결합이다.

세부 전체·기간·경마장·fold·field-size 표는 branch-local 감사 CSV에 저장했다.

## 상대의 상대화 Feature

`horse_recent5_race_time_percentile_median_field_percentile`은 두 단계의 비교집단을 구분한다.

1. 기존 F1: 각 **과거 race_id**의 정상 완주·유효 시간 말들 사이 time percentile을 계산하고 해당 말의
   최근 5회 median을 만든다.
2. R1: 그 cutoff-known median을 **현재 race_id**의 출전마끼리 다시 percentile로 바꾼다.

R1 SQL은 과거 event나 현재 결과를 재조인하지 않고 기존 F1 source column만 읽는다. Source NULL은
정상 전파됐고 비교마 규칙 위반 0건, 독립 재계산 최대 오차 0이었다. 따라서 과거 경주 상대수준과
오늘 경쟁자 내 위치가 혼동되지 않았다.

## 재현 산출물

Branch-local ignored 경로 `data/exports/validation/post_baseline_v2_relative_r1/`에 다음을 저장했다.

- `audit_result.json`
- `r1_source_null_tie_audit.csv`
- `r1_manual_recalculation.csv`
- `r1_profile_overall.csv`
- `r1_profile_by_period.csv`
- `r1_profile_by_meet.csv`
- `r1_profile_by_fold.csv`
- `r1_profile_by_field_size.csv`

## 다음 단계

데이터 수준 blocker는 없다. 다음 작업은 기존 계약을 고정한 `LT1(137)` 대 `LR1(144)` 단일 Logistic
development 실험이다. 이번 결과는 R1의 예측 가치를 의미하지 않으며 성능을 확인하기 전 7개 구성과
계산식을 변경하지 않는다.

### 확인된 사실

- R1 7개가 registry와 1:1로 구현됐고 candidate 28,392행·2,675경주·144입력 계약이 성립한다.
- 업무키, PIT, NULL, tie, 범위, round-trip, 수기 재계산 위반은 0건이다.
- 공통 DB와 봉인 산출물은 변경되지 않았고 Validation 접근은 없다.

### R1에 대한 아직 검증되지 않은 가설

- 동일 경마장·거리 및 관계자의 현재 field-relative 위치가 LT1의 absolute 값보다 추가 정보를 준다.
- 과거 경주 상대력의 최근 median을 오늘 field에서 다시 상대화하면 F1 수준을 넘어 추가 정보를 준다.

### 후속 모델 실험에서 검증할 질문

동일 Logistic·동일 네 development fold에서 R1 7개만 추가한 LR1이 LT1보다 Macro Log Loss와 Macro
Brier를 여러 fold에서 반복 개선하는가?
