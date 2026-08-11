# 새 공식 연승 Baseline을 위한 API4 Feature Universe

## 기술 요약

`place_logistic_baseline_v1`은 최소 Feature 파이프라인과 시간순 평가 절차를 검증한 historical experiment로 보존한다. 성능 실패로 폐기하는 것이 아니라 API4 원천 89개 중 속도·구간·마체중·경주조건이 충분히 활용되지 않았기 때문에 향후 공식 기준모델 자격만 해제한다.

새 Feature universe는 141개 후보로 구성했다. 상태는 `APPROVED` 27개, `APPROVED_WITH_FLAG` 87개, `NEEDS_VALIDATION` 12개, `DEFERRED` 5개, `PROHIBITED` 10개다. 즉시 Snapshot 후보군은 114개지만 이는 모델 입력을 확정하거나 모두 유용하다고 주장하는 숫자가 아니다. 사전 상관관계 추측으로 제거하지 않고 후속 시간순 ablation이 평가할 수 있도록 후보를 보존한 결과다.

이번 단계에서는 `semantic.api4_runner_event_v2` View만 추가했다. Raw·Staging과 기존 Canonical 의미는 변경하지 않았고 새 Snapshot과 모델은 생성하지 않았다.

## 1. Raw 89개 필드는 모두 대조됐지만 Canonical에는 정보 손실이 있다

공식 API4 명세의 응답 필드와 `staging.race_result`를 89/89 일치시켰다. Staging은 49,386행에서 모든 원문 필드를 `VARCHAR`와 `source_item_json`으로 보존한다.

전수 결과는 `docs/api4-field-audit-v2.csv`에 있으며 각 행에는 공식 의미, 실제 예시, dtype, 계층별 보존, 현재 변환, 정보 손실, 직접 가용성, Historical 원천 여부, 사후정보와 검증 상태가 들어 있다.

### `rcTime` 정밀도 손실은 새 semantic column으로 해결했다

- Raw 예시: `75.9`, 단위는 초이며 소수 첫째 자리까지 존재
- 기존 Canonical: `race_time INTEGER`
- 기존 변환 결과: 49,386행 중 43,521행이 원문 소수값과 달라짐
- 새 표현: `race_time_seconds DECIMAL(8,1)`로 원문 정밀도 보존
- 속도 계산용 표현: `valid_race_time_seconds`; `0`은 결과 상태용 센티널로 제외
- 비0 기록: 48,568행, 최소 59.2초, 중앙값 87.9초, 최대 175.4초

현재 경주의 기록은 사후정보이므로 Feature로 금지하고, 과거 경주만 사용한다.

### `wgHr`는 중량과 증감을 분리할 수 있지만 두 종류의 구조적 결측이 있다

- 완전 패턴 예시: `478(+1)`, `502(-2)`
- 증감 없는 패턴: `475()`
- 중량도 없는 패턴: `()`
- `horse_weight_kg` 파싱 성공: 48,991/49,386행(99.20%)
- `horse_weight_change_kg` 파싱 성공: 45,566/49,386행(92.27%)
- `()` 중량 파싱 불가: 395행
- 중량 범위: 377~584kg, 중앙값 476kg
- 증감 범위: -35~45kg, 중앙값 +1kg

완전한 `중량(±증감)` 패턴의 파싱 실패는 0건이다. `중량()`은 중량을 보존하고 증감만 NULL로 둔다. `()`는 임의 보완하지 않는다. 현재 경주 마체중의 예측시점 공개 여부는 아직 검증되지 않았으므로 현재값 Feature는 `NEEDS_VALIDATION`, 과거 마체중 이력은 `APPROVED_WITH_FLAG`다.

### 주로는 상태와 함수율로 분리되며 12행은 상태가 없다

- 날씨: 맑음 38,123, 흐림 8,295, 비 2,737, 눈 146, 강풍 73, `-` 12행
- 주로: `건조 (2%)` 형식을 `track_condition='건조'`, `track_moisture_percent=2`로 분리
- 정상 상태: 건조·양호·다습·포화·불량
- `(0%)` 12행: 함수율은 0이지만 상태는 NULL

과거 조건 적응 이력은 PIT-safe하게 계산할 수 있다. 다만 현재 경주 날씨·주로가 발매 마감 전에 실제 제공되는지는 검증 전이므로 현재값은 승인하지 않는다.

## 2. 구간기록은 S1F만 통합하고 G3F/G1F는 경마장별로 분리했다

API4는 반대 경마장 필드와 미통과 구간을 NULL이 아닌 `0`으로 채운다. 따라서 `0`은 숫자 기록이 아니라 구조적 미존재 또는 결과 미확정으로 다룬다.

### 통합 승인

- 서울 `seS1fAccTime`: 서울 S1F 통과누적기록
- 부산경남 `buS1fTime`: 부산경남 S1F 통과기록
- 두 값은 출발 후 첫 1F라는 동일한 물리 구간이므로 `s1f_seconds`로 경마장별 매핑
- 서울 비0 27,917/28,644행, 부산경남 비0 20,508/20,742행

### 통합 보류

- 서울 `seG3fAccTime`, `seG1fAccTime`: 공식 명칭이 G3F/G1F 통과누적기록
- 부산경남 `bu_3fGTime`, `bu_1fGTime`: 공식 명칭이 해당 지점부터 결승까지 통과기록
- 명칭과 계산 방향이 같다고 확정할 근거가 부족하므로 경마장 공통 G3F/G1F로 합치지 않음
- `se_g3f_acc_time_seconds`, `se_g1f_acc_time_seconds`, `bu_g3f_to_finish_seconds`, `bu_g1f_to_finish_seconds`로 분리
- 공통 Feature는 `NEEDS_VALIDATION`

1C/2C와 부산 G6F/G8F는 거리별 구조적 결측이 크다. 거리×경마장별 가용률은 `sectional_availability.csv`에 보존했다. 이 필드들은 공통 baseline이 아니라 후속 거리 조건부 페이스 Feature로 둔다.

## 3. Feature registry는 사후 선택 전에 141개 후보를 보존한다

전체 정의는 `docs/place-feature-registry-v2.csv`에 있다. 각 후보는 source, 계산 정의, window/조건, PIT, 공개시점, 결측 의미, 최소 이력·count, 누수 위험, 예상 중복, status와 권장 그룹을 가진다.

| 상태 | 후보 수 | 의미 |
|---|---:|---|
| `APPROVED` | 27 | 명확한 현재 사전정보 또는 독립 count |
| `APPROVED_WITH_FLAG` | 87 | 과거 이력·조건부 표본이며 count/가용성 플래그와 함께 사용 |
| `NEEDS_VALIDATION` | 12 | 구간 의미 또는 현재 예측시점 공개 여부 미확정 |
| `DEFERRED` | 5 | 희소 환경 적응 또는 명백한 수학적 중복 |
| `PROHIBITED` | 10 | 현재 결과·사후시장·PIT 실패 누적값 |

### 새 공식 baseline Snapshot에 즉시 포함 가능한 후보군 114개

- 현재 사전정보 9개: 경마장, 등급, 거리, 등록두수, 마번, 성별, 연령, 부담중량, 레이팅
- 현재 경주조건 11개: 연령·부담·상금·성별 조건, 경주 유형, 요일, 1~5착 상금
- 기존 Historical 19개와 독립 count 3개
- 장기 경기력 10개: 승·Top3, 최고/표준편차 착순, 레이팅 수준·변화, 부담중량
- recent 3/5/10 form 24개
- 동일 경마장·거리·경마장×거리 적성 12개
- `rcTime`·S1F 안전 후보 및 관측 count 8개
- 과거 마체중 5개
- 기수·조교사·말-기수·말-조교사·마주 이력 20개

`APPROVED_WITH_FLAG`는 값만 단독 사용하지 않고 관측 count, history availability, left-censoring 표시와 함께 Snapshot에 저장하는 조건이다.

### 추가 검증 후 포함 가능한 12개

- `buga1~3`: 공식 의미와 모델링 단위를 추가 확인
- 현재 날씨, 주로상태, 함수율, 마체중, 마체중 증감: 발매 마감 시점 공개 여부 확인
- 서울·부산경남 공통 G3F/G1F 요약 4개: 의미적 동등성 검증

### 후속 고도화 5개

- 같은 날씨/주로 조건의 과거 출전수·PLC 적중률 4개
- `horse_prior_plc_hit_count`: 시작수와 적중률로 정확히 재구성되는 수학적 중복

### 사용 금지 10개

- 현재 착순, `rcTime`, sectional, 착차
- 현재 단승·연승 배당과 매출
- API26 현재성 누적 통계
- API37 누적 sectional
- `ilsu`를 말의 직전 출전 간격으로 해석한 Feature

과거 경주의 착순·기록·구간·배당은 목적이 명확할 때 Historical 계산 원천 또는 별도 시장 분석에는 사용할 수 있지만 현재 경주의 Feature로는 금지한다.

## 4. Point-in-Time 계약

모든 Historical 후보는 다음 조건을 공유한다.

```text
historical.race_date < feature_as_of
```

- 같은 날짜의 앞 경주도 사용하지 않음
- DNS는 출전 이력에서 제외
- 주행정지·실격은 실제 출전수에는 포함하되 완주·착순 통계에서는 기존 상태 계약 적용
- `rcTime`, sectional, 착차는 유효한 과거 출전에서만 사용
- 관측 count를 별도 companion feature로 보존
- API26/API37 누적 통계는 재사용하지 않음

## 5. 실제 수정한 데이터 계층

새 `semantic.api4_runner_event_v2` View를 추가했다.

- 기존 Raw: 변경 없음
- 기존 Staging: 변경 없음
- 기존 Canonical: 변경 없음
- 기존 `mart.feature_snapshot_place`: 변경 없음
- 기존 baseline 산출물: 변경 없음
- 새 semantic 표현: 시간 정밀도, 유효 시간, 마체중·증감, 주로상태·함수율, S1F, 경마장별 G3F/G1F

이 View는 `staging_row_id`, batch/request/raw file/SHA256과 `source_item_json`을 유지해 원문까지 역추적할 수 있다.

## 6. 품질 프로파일 결과와 한계

- semantic 행 수 49,386 = Staging 행 수 49,386
- `staging_row_id` 중복 0건
- Raw→semantic `rcTime DECIMAL(8,1)` 불일치 0건
- 완전 마체중 패턴 파싱 실패 0건
- semantic audit issue 0건
- 속도·sectional은 경마장·거리·연도별 가용률을 별도 CSV로 기록

아직 판단할 수 없는 사항:

- G3F/G1F 서울·부산 필드의 완전한 의미 동등성
- 현재 마체중·날씨·주로의 발매 마감 직전 공개 여부
- 2022·2023 추가 이력이 반영됐을 때 left-censoring 완화 정도
- 각 후보의 예측 성능과 중복 영향
- 거리·경마장·주로 보정 속도지수의 적절한 산식

## 7. 다음 단계

1. 사용자 검토로 114개 즉시 후보와 12개 보류 후보의 registry 정의를 확정한다.
2. API가 정상화되면 2022·2023 Raw 수집·audit을 완료한다.
3. 별도 버전의 공식 baseline Snapshot 설계를 확정하고 구현한다.
4. Snapshot 데이터 품질과 PIT를 먼저 audit한다.
5. 이후에만 독립된 시간 분할과 ablation을 설계하며 기존 Final Test를 재사용하지 않는다.
