# 데이터 계층 계약

## Raw

KRA API 응답 바이트의 불변 증거다. 정상 JSON뿐 아니라 `NO_DATA`, API 오류, 비정상 응답도 보존한다. 기존 파일을 덮어쓰지 않으며 SHA256을 기록한다.

## Raw Manifest

API 요청 한 건당 한 행을 기록한다. HTTP 상태와 API 업무상태를 분리한다.

필수 업무상태:

- `SUCCESS`
- `NO_DATA`
- `HTTP_ERROR`
- `EMPTY_BODY`
- `INVALID_JSON`
- `API_ERROR`
- `INVALID_SCHEMA`
- `REQUEST_MISMATCH`
- `REQUEST_ERROR`

HTTP 2xx만으로 성공 처리하지 않는다. API 결과코드, 필수 구조, 요청 범위와 응답 범위를 함께 검증한다.

## Staging

Raw의 `item`을 SQL 행과 열로 펼친 원천 보존 계층이다.

- 원천 필드와 원천 행 순서를 보존한다.
- 원천 값은 불필요하게 보정하지 않는다.
- `request_id`, `batch_id`, `source_row_number`, `raw_sha256`를 포함한다.
- 업무적으로 잘못된 행도 조사 가능하도록 남긴다.
- 파싱할 수 없는 Raw는 Manifest에는 남지만 Staging 행으로 만들지 않는다.

## Quality

Staging 검사는 오류 행을 조용히 삭제하지 않는다. `quality.data_issue`가 원천 행을 참조하고 규칙, 심각도, 발견시각, 변환 버전을 기록한다.

최소 심각도:

- `INFO`: 관찰 및 범위 정보
- `WARNING`: 분석 시 주의가 필요하지만 보존 가능한 값
- `ERROR`: Canonical 승격을 막는 위반

## Canonical

프로젝트가 승인한 표준 타입, 업무 키, 코드 의미가 적용된 계층이다.

- 결정적이고 멱등적으로 생성한다.
- 중복 원천의 값이 같으면 동일 증거로 처리할 수 있다.
- 동일 업무 키의 값이 충돌하면 임의로 최신 값을 선택하지 않는다.
- 충돌은 품질 오류로 기록하고 해당 행의 승격을 중단한다.
- 모든 행은 Raw 요청까지 추적 가능해야 한다.

## Mart

후속 보고서·포트폴리오 분석용 Star Schema다. Canonical 의미를 바꾸지 않으며 Fact와 Dimension으로 재구성한다. 초기에는 중복 저장을 줄이기 위해 일부 Mart를 SQL View로 구현할 수 있다.

## 재구축 계약

- Raw부터 전체 SQL 데이터베이스를 재구축할 수 있어야 한다.
- Staging부터 Canonical과 Mart를 재생성할 수 있어야 한다.
- 정책 변경 때문에 API를 다시 호출하도록 강제하지 않는다.
- 동일 입력과 동일 변환 버전은 동일 Canonical 결과를 만들어야 한다.
