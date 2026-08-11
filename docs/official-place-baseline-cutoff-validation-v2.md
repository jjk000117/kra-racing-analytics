# Official place baseline prediction cutoff and feature validation

검증일: 2026-08-12

## 결론

새 official place baseline의 prediction cutoff는 **각 경주의 결과가 발생하기 전이며, 실제 베팅
의사결정을 내리는 시점**으로 정의한다. 현재 단계에서는 `T-N분`을 고정하지 않는다. 해당 시점에
관측할 수 있는 현재 경주 정보와 `race_date < feature_as_of`인 과거 이력만 입력할 수 있다.

실시간 배당은 baseline 입력에서 제외한다. 향후 모델 확률과 시장확률 비교 및 베팅전략 단계에서만
별도 시점 스냅샷으로 사용한다. API4의 확정 배당은 결과 데이터이므로 계속 금지한다.

## 판정 요약

| 대상 | 판정 | registry 처리 | 근거와 적용 규칙 |
|---|---|---|---|
| 현재 마체중 | A baseline 사용 가능 | `APPROVED` | KRA `금주의경마 > 출전마체중`이 경주별 출발시각과 입력완료 상태로 공개하고, API25_1도 마체중을 실시간 갱신하는 전용 출전마 API로 정의한다. API4 `wgHr`는 역사적 재현 원천으로 파싱한다. |
| 현재 마체중 증감 | A | `APPROVED` | 같은 사전 화면과 API25_1이 증감을 별도 제공한다. 첫 출전마는 주행심사 합격 시 체중과 비교한다는 KRA 설명을 따른다. |
| 현재 날씨 | A | `APPROVED` | 경주일 당시 관측 가능한 환경값이며 KRA 경주 자료가 날씨를 경주일 단위로 표시한다. API4 `weather`는 역사적 재현값으로 사용한다. |
| 현재 주로상태 | A | `APPROVED` | KRA 경주로 현황이 경주 전 시각과 갱신시각을 붙여 상태를 공개한다. |
| 현재 함수율 | A | `APPROVED` | 같은 화면이 함수율과 상태 매핑을 공개한다. API4 `track`의 `상태 (N%)`를 분리한다. |
| `buga1~3` | A | `APPROVED` | 공식 명칭은 부가상금 1~3이며 출전표가 순위상금과 부가상금을 경주 전에 공개한다. 각각 1~3위 부가상금 금액으로 해석한다. |
| 과거 G3F | A, 변환 규칙 필수 | `APPROVED_WITH_FLAG` | 서울 `seG3fAccTime`은 출발~G3F 누적이므로 `rcTime - seG3fAccTime`; 부경 `bu_3fGTime`은 3F-G 자체다. 모두 최종 600m 초로 통일한다. |
| 과거 G1F | A, 변환 규칙 필수 | `APPROVED_WITH_FLAG` | 서울 `seG1fAccTime`은 출발~G1F 누적이므로 `rcTime - seG1fAccTime`; 부경 `bu_1fGTime`은 1F-G 자체다. 모두 최종 200m 초로 통일한다. |
| 현재 경주의 S1F/G3F/G1F | D baseline 사용 불가 | 기존 `PROHIBITED` 유지 | 현재 경주 주행 뒤 생성되는 결과정보다. |
| 실시간 배당 | E betting-stage only | baseline 밖에서 관리 | 예측확률과 시장확률을 비교할 후속 단계에서 cutoff가 있는 별도 원천으로 수집한다. |
| API4 확정 배당 | D | 기존 `PROHIBITED` 유지 | 경주 후 확정값이므로 live odds의 대체재가 아니다. |

이번 검증으로 B(추가 실측 필요) 또는 C(의미 검증 필요)로 남은 12개 대상은 없다. 다만 운영
수집에서는 모든 현재 경주 값에 `observed_at < prediction_cutoff`를 저장·검사해야 한다. 이는
Feature 의미의 blocker가 아니라 운영 lineage 요건이다.

## 공식 근거와 값 대조

- KRA 출전상세정보는 출전정보와 PDF 공개시각을 매주 수요일 17:00으로 명시한다.
- KRA 출전표 화면은 레이팅·부담중량·증감과 순위상금·부가상금을 경주 전에 제공한다.
- KRA 출전마체중 화면은 경주별 출발시각과 체중 입력완료 여부를 제공한다.
- KRA 경주로 현황은 예를 들어 2026-08-09 09:00의 함수율 `2%(건조)`와 다음 갱신시각을 함께
  게시했다. 이 때문에 상태와 함수율은 prediction cutoff 이전 관측값으로 사용할 수 있다.
- 공공데이터포털 API25_1은 마체중·증감·최종출전일을 제공하는 실시간 API로 정의한다.
- API4 공식 명세는 `weather`, `track`, `wgHr`, `buga1~3` 및 경마장별 sectional을 명시한다.
- 저장된 API4 49,386행에서 `buga1~3`는 0 또는 금액이며, 비영(非零) 값은 일관되게 1·2·3위
  배분 구조를 보였다.
- 부경 20,473개 유효행에서 `rcTime - buG3fAccTime = bu_3fGTime`과
  `rcTime - buG1fAccTime = bu_1fGTime`이 부동소수 오차 범위에서 전부 일치했다. 같은 공식
  누적기록 정의를 쓰는 서울에는 이 차분을 적용한다. 거리별 분포도 서울 변환값과 부경 직접값이
  같은 물리 범위였다(G3F 대체로 36~44초, G1F 대체로 13~16초).

API25_1 실제 단일 요청은 서버가 HTTP 403을 반환해 응답값 직접 대조에는 실패했다. 따라서 API와
홈페이지의 같은 경주·말 값 일치 여부는 이번 실행에서 새로 입증하지 못했다. 다만 전용 API의 공식
필드 정의, KRA의 실제 사전 공개 화면, API4 저장값의 의미가 서로 일치하므로 Feature 사용 가능성
판정은 유지한다. 운영 수집 구현 시 첫 성공 batch에서 행 단위 일치 검사를 추가한다.

## Sectional 계약

```text
historical_g3f_seconds =
  Seoul: rcTime - seG3fAccTime
  Busan: bu_3fGTime

historical_g1f_seconds =
  Seoul: rcTime - seG1fAccTime
  Busan: bu_1fGTime
```

- 원천 경주가 현재 feature row보다 과거여야 한다.
- 정상적인 양수 `rcTime`과 양수 sectional만 포함한다.
- 0 sentinel, DNS, 주행중지, 실격 및 기록 미존재 행은 해당 sectional 집계에서 제외한다.
- 거리·경마장 영향 때문에 raw 초 자체를 절대 속도지수로 해석하지 않는다. 첫 구현은 registry의
  최근 3/5회 중앙값과 관측 count 계약만 따른다.

## Registry 변경

기존 141개 항목 수는 유지했다.

- `NEEDS_VALIDATION -> APPROVED`: `race_bonus_1~3`, `current_weather`,
  `current_track_condition`, `current_track_moisture_percent`,
  `current_horse_weight_kg`, `current_horse_weight_change_kg` — 8개
- `NEEDS_VALIDATION -> APPROVED_WITH_FLAG`: 최근 3/5회 G3F·G1F 중앙값 — 4개
- 변경 후: `APPROVED` 35, `APPROVED_WITH_FLAG` 91, `NEEDS_VALIDATION` 0,
  `DEFERRED` 5, `PROHIBITED` 10
- Snapshot v2 즉시 구현 후보: 126개

## Snapshot v2 전 blocker

명세상 blocker는 없다. 구현할 때 필요한 최소 안전장치는 다음 세 가지다.

1. 현재 경주 값의 소스별 `observed_at`과 모델의 `prediction_cutoff` 저장
2. 서울 sectional 차분값의 양수·범위 검사와 원천 count 보존
3. API25_1을 실제 운영에 사용할 경우 첫 성공 수집에서 홈페이지/API4와 행 단위 대조

## 공식 자료

- [KRA 출전상세정보](https://race.kra.co.kr/chulmainfo/ChulmaDetailInfoList.do?Act=02&Sub=1&meet=1)
- [KRA 출전마체중](https://race.kra.co.kr/thisweekrace/ThisWeekWeight.do?Act=04&Sub=4&meet=3)
- [KRA 경주로 현황](https://race.kra.co.kr/chulmainfo/trackView.do?Act=02&Sub=10&meet=1)
- [KRA 경주성적표 용어해설](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)
- [공공데이터포털 출전마 체중 정보 API25_1](https://www.data.go.kr/data/15057498/openapi.do)
- [공공데이터포털 KRA API 목록 및 경주기록 정보](https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=&org=%ED%95%9C%EA%B5%AD%EB%A7%88%EC%82%AC%ED%9A%8C)

