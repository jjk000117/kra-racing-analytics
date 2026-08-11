# KRA API failure and ServiceKey exposure diagnostic

진단일: 2026-08-12

## 2026-08-12 활용신청 후 API4 재확인

사용자가 확인한 공공데이터포털 데이터셋 `15058305`는 현재 코드의 공식 원천과 일치한다.

- Base URL: `https://apis.data.go.kr/B551015/API4_3`
- operation: `GET /raceResult_3`
- 실제 코드 endpoint: `https://apis.data.go.kr/B551015/API4_3/raceResult_3`
- 공식 필수값: `ServiceKey`, `numOfRows`, `pageNo`
- 공식 선택조건: `meet`, `rc_date`, `rc_month`, `rc_year`
- 코드의 `_type=json`: 지원되는 JSON 응답 선택

2022 서울, 1페이지·1행을 retry 없이 한 번 호출한 결과:

- HTTP 200
- JSON
- 5.203초
- `resultCode=99`
- `가용한 세션이 존재하지 않습니다. (100/100)`
- `totalCount` 없음, item 0
- 실패 계층: API application

환경 키는 percent-encoded 문자열이 아닌 원문이며 `httpx` 준비 URL에서 double encoding 징후가
없었다. 인증 gateway 오류가 아니라 application 응답을 받았으므로 endpoint·operation·파라미터·
키 전달 방식이 원인이라는 증거는 없다. 전체 수집은 계속 보류한다.

## 2026-08-12 비교 API 활용신청 후 재확인

API156과 API155를 retry 없이 각각 한 번 재호출했다.

| API | HTTP | 시간 | resultCode | resultMsg | 데이터 |
|---|---:|---:|---|---|---|
| API156 `GET /raceRsutDtl` | 200 | 5.369초 | 99 | `가용한 세션이 존재하지 않습니다. (100/100)` | 없음 |
| API155 `GET /raceResult` | 200 | 5.195초 | 99 | `가용한 세션이 존재하지 않습니다. (100/100)` | 없음 |

두 API 모두 활용신청 전 HTTP 403에서 HTTP 200으로 바뀌었으므로 활용신청과 인증은 반영됐다.
그러나 API4와 동일한 application 오류를 반환했다. 현재 관측은 Case B, 즉 세 API가 공유하는 KRA
application 또는 연동 계층의 가용성 문제 가능성을 가장 강하게 지지한다. 내부 구현 원인은 여전히
단정하지 않는다.

## 요약

- 과거 수집 원천은 `https://apis.data.go.kr/B551015/API4_3/raceResult_3`, operation
  `GET /raceResult_3`이다.
- 이번 실행에서 API4는 정확히 한 번 호출했지만 오류 응답의 `body`가 객체가 아닌 문자열인 변형을
  초기 진단 파서가 처리하지 못해 HTTP status와 header 요약을 출력하기 전에 중단됐다. 호출 제한을
  지키기 위해 API4를 재호출하지 않았다.
- 직전 최소 진단에서 확인된 최신 API4 관측값은 HTTP 200, `resultCode=99`,
  `가용한 세션이 존재하지 않습니다. (100/100)`이며 이는 HTTP가 아닌 API application 계층 실패다.
- 비교 API156과 API155는 각각 한 번 호출했고 둘 다 HTTP 403이었다. API application header,
  `totalCount`, 데이터는 반환되지 않았다.
- 비교 API는 현재 키로 활용신청/권한이 없을 가능성이 있으므로 이 403만으로 KRA 공통 backend 장애나
  키 전체 무효를 판정할 수 없다.
- 2022·2023 전체 수집은 아직 재개하지 않는다.

## ServiceKey 노출 원인과 수정

### 원인

`httpx.HTTPError`를 `str(error)`로 직접 저장하면 예외가 전체 request URL을 포함하는 경우
`ServiceKey`가 함께 Manifest의 `error_message`, CLI traceback 또는 로그에 노출될 수 있었다.
기존 logging filter도 환경변수의 원문만 치환해 대소문자가 다른 query name과 URL-encoded key를
독립적으로 처리하지 못했다. 앞선 수동 진단의 `raise_for_status()` traceback도 같은 경로였다.

### 수정

`kra_analytics.logging`에 공통 함수를 추가했다.

- `redact_secrets`: `serviceKey`/`ServiceKey`를 대소문자 무관하게 탐지하고 query 값을
  `***REDACTED***`로 치환
- 환경변수 및 명시적으로 전달된 secret의 원문·percent encoding·plus encoding 치환
- `safe_exception_message`: 예외 타입과 메시지를 위 redaction 경로로만 문자열화
- API4/API179 collector의 `HTTPError` 저장 경로에서 `str(error)` 제거
- logging filter도 동일 함수 재사용
- 진단 스크립트는 예외를 catch하고 안전한 요약만 출력하며 request params는 출력·저장하지 않음

현재 키를 변경하거나 재발급하지 않았다.

## 저장소 노출 검사

프로젝트 `.env`와 Git 내부·도구 cache를 제외하고 파일 원문을 실제 키의 원문 및 URL-encoded
형태와 비교했다. DuckDB `raw.api_request`의 URL과 오류 메시지도 검사했다.

- filesystem secret hit: 0
- Manifest 검사 행: 100
- DB secret hit: 0
- `ServiceKey`가 있으나 redacted marker가 없는 URL: 0

기존 Codex 실행 로그는 저장소 밖이므로 이 검사 범위에 포함되지 않는다.

## 공식 endpoint와 최소 호출

| API | 공식 endpoint / operation | 이번 요청 | HTTP | format | result | total/data | 계층 |
|---|---|---|---:|---|---|---|---|
| 경주기록 정보 | `API4_3/raceResult_3`, `GET /raceResult_3` | 서울, `rc_year=2022`, 1행, 1회 | 이번 출력 유실 | JSON 오류 envelope | 이번 출력 유실; 직전 관측 `99 / 100/100` | 이번 출력 유실 | 직전 관측은 API application |
| AI기반연구용 경주결과상세 | `API156/raceRsutDtl`, `GET /raceRsutDtl` | 명세가 허용하는 무조건 최신, 1행, 1회 | 403 | JSON | application code 없음 | 없음 | HTTP |
| AI학습용 경주결과 | `API155/raceResult`, `GET /raceResult` | 서울 `20220108`, 1행, 1회 | 403 | JSON | application code 없음 | 없음 | HTTP |

API156 응답시간은 0.071초, API155는 0.026초였다. 자동 retry는 0회다.

## 장애 범위 판정

### 확인된 사실

1. API4는 과거 여러 차례 gateway HTTP 200 이후 application `99 / 100/100`을 반환했다.
2. 이번 API4 요청은 한 번 수행됐으나 초기 진단 파서 결함으로 status/header 증거가 남지 않았다.
3. API156과 API155는 이번에 모두 HTTP 403으로 gateway/application data 이전에 거부됐다.
4. 두 새 API는 공공데이터포털에서 별도 활용신청 대상이다.
5. 저장소와 Manifest에서는 실제 키가 발견되지 않았다.

### 추론

- 현 증거는 Case A~D 중 하나로 완전히 확정하기에 부족하다.
- API4의 반복 `100/100`은 해당 endpoint 또는 그 연동 backend의 일시적 가용성 문제와
  일치하지만 내부 세션/DB pool 구현은 단정하지 않는다.
- API156/API155의 403은 두 API에 대한 활용 권한 부재 가능성이 가장 먼저 검토되어야 한다.
  따라서 두 403을 KRA 공통 backend 장애나 현재 키 전체의 인증 실패로 해석하지 않는다.
- API4가 다시 HTTP 200/`00`을 반환하기 전에는 전체 수집을 재개할 근거가 없다.

## 새 API의 대체 원천 가능성

| 항목 | API156 AI기반연구 상세 | API155 AI학습용 결과 |
|---|---|---|
| 서울·부산경남 | 공식 설명상 가능 | `rccrs_cd=1/3`으로 가능 |
| 말 단위 결과 | 있음 | 있음 |
| 2022·2023 조회 구조 | 공식 페이지에서 날짜 parameter가 확인되지 않아 미확정 | `race_dt`가 있어 구조상 가능 |
| `rcTime` | 경주기록 있음 | 경주기록 있음 |
| 마체중 | 있음 | 있음 |
| rating | 있음 | 있음 |
| 기수/조교사 | ID·명칭 있음 | 명칭 있음 |
| S1F/G3F/G1F | 공식 제공 필드 설명에 없음 | 공식 제공 필드 설명에 없음 |

API156은 API4보다 현재 경주·관계자 의미가 풍부하고 API155는 날짜·경마장 조회가 명확하지만,
sectional 부재 가능성과 현재 403 때문에 API4의 완전한 대체 여부는 판단하지 않는다. 활용 권한을
확인한 뒤 별도 schema/PIT/과거 범위 검증 후보로만 남긴다.

## 다음 권장 작업

1. 공공데이터포털에서 API156·API155 활용신청 상태만 확인한다. 키 교체는 이번 범위 밖이다.
2. 다음 API4 상태 진단은 이번에 보완된 스크립트로 1회만 수행한다.
3. API4가 HTTP 200, resultCode `00`, `totalCount > 0`으로 회복된 경우에만 2022와 2023을
   서로 다른 batch로 전체 Raw 수집한다.
4. 비교 API 권한이 확보되면 각 1회 표본으로 실제 필드와 2022·2023 조회 가능성을 별도 검증한다.

공식 명세:

- [한국마사회 AI기반연구용 경주결과상세](https://www.data.go.kr/data/15150068/openapi.do)
- [한국마사회 AI학습용 경주결과](https://www.data.go.kr/data/15143803/openapi.do)
