# KRA Racing Analytics — 프로젝트 계약

## 1. 목적

KRA 공식 OpenAPI의 과거 경주결과와 매출 데이터를 수집·검증하여 Python, SQL, Power BI 기반의 독립적인 경마 데이터 분석 프로젝트를 구축한다.

초기 버전의 목표는 예측 모델이나 자동 운영이 아니라 다음을 재현 가능하게 완성하는 것이다.

- API 응답 원본의 불변 보존과 수집 이력 추적
- SQL Staging, Canonical, Star Schema의 단계적 구축
- 상태코드와 Point-in-Time 정책이 적용된 신뢰 가능한 분석 데이터
- Power BI에서 경주, 출전마, 말, 기수, 조교사, 매출을 분석할 수 있는 모델

기존 `horse_racing` 저장소는 참고 자료이자 읽기 전용 원천이다. 기존 R 코드를 Python으로 번역하거나 기존 산출물을 신규 프로젝트의 공식 Canonical 데이터로 간주하지 않는다.

## 2. 초기 범위

### 포함

- 경마장: 서울(`meet=1`), 부산경남(`meet=3`)
- 경주결과: KRA API4_3
- 매출·확정배당: KRA API179_1
- 기간: API에서 재수집 가능한 과거 범위 중 기존 프로젝트와 동등한 범위를 우선 목표로 하며, 실제 시작일·종료일은 수집 전 API 범위 점검 결과로 고정한다.
- 실행 방식: 사용자가 명시적으로 실행하는 수동 전체 수집 및 전체 재구축
- 분석 환경: 로컬 Python, Jupyter, DuckDB, Power BI

### 제외

- 제주 경마장
- 최신 증분 수집
- 예약 실행, 자동 재시도 운영, 알림
- 실시간 또는 준실시간 대시보드
- 예측 모델, 베팅 추천, 자동 베팅
- 기존 R 모델 및 R Feature Dataset의 이식

제외 항목은 현재 아키텍처를 유지한 채 후속 단계에서 추가할 수 있어야 한다.

## 3. 데이터 흐름

```text
KRA OpenAPI
  → Immutable Raw 파일
  → SQL raw Manifest
  → SQL Staging
  → SQL 품질 검사
  → SQL Canonical
  → SQL Star Schema / Mart
  → Jupyter 검증 및 Power BI 분석
```

각 계층은 독립적으로 재실행할 수 있어야 한다. 상태코드나 Canonical 규칙이 변경되어도 API를 다시 호출하지 않고 Raw 또는 Staging부터 재처리할 수 있어야 한다.

## 4. 기술 역할

- Python: API 호출, Raw 저장, 파일 수준 검증, Manifest 기록, Staging 적재, 실행 CLI
- SQL: 타입 검사, 업무 규칙 검사, 중복·충돌 처리, Canonical 및 Star Schema 생성
- Jupyter: 탐색, 샘플 대조, 품질 및 지표 검증. 공식 운영 로직은 노트북에만 두지 않는다.
- Power BI: `mart` 계층만 조회한다. Raw와 Staging을 직접 조회하지 않는다.

초기 데이터베이스는 DuckDB로 확정한다. Python과 Jupyter는 DuckDB를 직접 사용하고 Power BI는 DuckDB의 `mart` 계층에서 내보낸 Parquet를 사용한다.

## 5. 저장 및 추적 계약

모든 요청과 원천 행은 최소한 다음 정보를 추적할 수 있어야 한다.

- `request_id`: API 요청 한 건의 고유 식별자
- `batch_id`: 한 번의 실행 단위 식별자
- `raw_path`: 불변 Raw 파일 위치
- `raw_sha256`: Raw 바이트의 SHA256
- `requested_at`, `collected_at`, `loaded_at`
- `source_row_number`: 원천 응답 내 행 순서
- `schema_version`
- `transformation_version`
- 수집 및 변환 상태

동일 명령의 재실행이 Canonical 행을 중복 생성하지 않는 멱등성을 보장한다.

## 6. 주요 업무 키

- 경주: `race_date + meet_code + race_no`
- 출전 이벤트: 경주 키 + `horse_id`
- 말: KRA `hrNo`
- 기수: KRA `jkNo`
- 조교사: KRA `trNo`
- 매출: 경주 키 + `betting_type`

이름은 표시 및 감사 속성이며 기본 조인 키로 사용하지 않는다.

## 7. 보안 및 원본 정책

- API 키는 환경변수 `KRA_API_KEY`에서만 읽는다.
- API 키를 코드, Raw, SQL, Manifest, 로그, 노트북 출력에 기록하지 않는다.
- Raw는 API 응답 바이트 그대로 저장하고 덮어쓰지 않는다.
- 실패 응답도 수집 증거로 보존하되 Canonical에는 포함하지 않는다.
- 기존 `horse_racing` 저장소의 파일은 생성·수정·삭제하지 않으며 Commit·Push하지 않는다.

## 8. 0단계 완료 기준

- 프로젝트 목적과 초기 범위가 문서화됨
- Raw → Staging → Canonical → Mart 경계가 정의됨
- 주요 업무 키와 lineage 필드가 정의됨
- API 상태 및 상태코드 처리 원칙이 정의됨
- Point-in-Time 및 누수 방지 원칙이 정의됨
- 초기 DB로 DuckDB가 선택되고 향후 서버형 DB 재검토 조건이 기록됨
- 단계별 Go/No-Go 기준이 정의됨
