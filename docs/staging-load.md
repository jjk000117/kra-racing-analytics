# 3단계 SQL Staging

## 결과

| 테이블 | 원천 API | 정식 배치 행 | 실제 Staging 행 | 신규 삽입 |
|---|---|---:|---:|---:|
| `staging.race_result` | API4_3 | 49,386 | 49,386 | 49,386 |
| `staging.sales_dividend` | API179_1 | 32,074 | 32,074 | 32,074 |

최적화 후 최초 적재 시간은 API4_3 약 17.3초, API179_1 약 3.6초였다. 동일 배치를 다시 실행했을 때 두 테이블 모두 `inserted_rows=0`이며, 완료된 적재와 행 수가 일치하면 Raw 재파싱을 생략한다.

## 보존 구조

두 테이블은 다음 lineage 열을 공통으로 가진다.

- `staging_row_id`: `raw_file_id + source_row_number`의 결정적 SHA256
- `batch_id`
- `request_id`
- `raw_file_id`
- `raw_sha256`
- `source_row_number`: API 응답 `items.item`의 1-based 순서
- `loaded_at`
- `transform_version`: 현재 `staging_v1`
- `source_item_json`: 개별 item 원문 JSON

API4_3은 관측된 원천 89개 필드를 `VARCHAR`로 보존한다. API179_1은 `amt`, `meet`, `odds`, `pool`, `rcDate`, `rcNo` 6개 필드를 보존한다.

## 안전 변환 열

Staging은 원문을 바꾸지 않고 변환 결과를 별도 열로 병행한다.

- API4_3: `ord`, `ord_numeric`, `ord_parse_valid`
- API179_1: `amt`, `amt_numeric`, `amt_parse_valid`

`ord=0/91~99`의 의미는 이 단계에서 확정하지 않는다. 숫자로 변환되더라도 공식 순위인지 여부는 Canonical 상태코드 정책에서 결정한다. `odds`도 복합 문자열 원문으로 유지한다.

## 멱등성과 트랜잭션

`staging_row_id`와 `(raw_file_id, source_row_number)`가 중복을 방지한다. 적재는 하나의 트랜잭션에서 실행되어 행 수 대조 실패 시 부분 결과를 커밋하지 않는다. `staging.load_run`은 기대 행 수, 실제 행 수, 신규 삽입 수와 변환 버전을 기록한다.

대량 행은 pandas DataFrame을 DuckDB에 등록하고 `INSERT ... SELECT`로 한 번에 전달한다. Python 행별 `executemany`는 넓은 API4_3 테이블에서 비효율적이어서 사용하지 않는다.

## 감사 검사

`staging check`는 다음을 SQL로 재검산한다.

- `load_run.expected_rows = load_run.staged_rows = 실제 테이블 행 수`
- 모든 Staging 행의 `request_id`, `raw_file_id`, `raw_sha256` 연결
- 각 Raw 파일의 행 수와 Manifest `item_count` 일치
- `source_row_number`가 1부터 `item_count`까지 연속
- 원문 숫자 변환 가능 여부와 parse flag 일치

두 정식 배치의 검사 결과는 모두 `issues=0`이다.

## 실행 명령

```powershell
python -m kra_analytics staging load 20260801T152038430395Z_api4_3_34c281ed
python -m kra_analytics staging load 20260801T153512893532Z_api179_1_9d682cd1
python -m kra_analytics staging check 20260801T152038430395Z_api4_3_34c281ed
python -m kra_analytics staging check 20260801T153512893532Z_api179_1_9d682cd1
```

다음 Canonical 단계에서는 Staging 원문을 기반으로 날짜·경마장·경주번호·출전마·승식 키와 상태코드 정책을 적용한다. 매출·확정배당은 계속 post-race 계층으로 분리한다.
