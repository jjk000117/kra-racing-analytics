# 4단계 Canonical과 품질 검사

## 결과

Staging 테이블을 수정하지 않고 다음 새 테이블을 생성했다.

| 테이블 | Grain | 행 수 |
|---|---|---:|
| `canonical.race` | 경주 | 4,600 |
| `canonical.runner_result` | 경주·출전마 | 49,386 |
| `canonical.sales_dividend` | 경주·승식 | 32,074 |
| `quality.data_issue` | 품질 이슈 | 911 |

변환 버전은 `canonical_v1`, 상태정책 버전은 `race_status_v1`이다. 전체 재구축은 하나의 트랜잭션으로 실행되며 실패하면 기존 Canonical 상태로 롤백된다.

## 표준 키와 타입

- `race_id`: `YYYY-MM-DD|meet_code|RNN`
- `runner_result_id`: `race_id|H{horse_id}`
- `sales_id`: `race_id|P{pool_code}`
- 경주일: `DATE`
- 경마장: 서울 `1`, 부산경남 `3`
- 경주번호·거리·출발번호·경주기록: 정수형
- 부담중량·마체중·단승/연승배당: 숫자형
- 매출: `DECIMAL(20,0)`

각 Canonical 행은 `source_staging_row_id`와 `source_batch_id`를 통해 Staging, Raw 파일, API 요청과 SHA256까지 추적할 수 있다.

## 상태코드 정책

공식 착순은 `ord=1~16`만 허용한다. `91/92`는 참고 저장소의 확정 정책을 계승해 출전 이력에는 포함하지만 착순 통계에서는 제외한다. `93/94/95 + rcTime=0`은 DNS로 분류한다. 해당 복합조건을 충족하지 않는 `0/93/94/95/99`는 의미를 추정하지 않고 미해결 비표준 상태로 보존한다.

| 상태 | 행 수 |
|---|---:|
| `FINISHED` | 48,493 |
| `PARTICIPATED_NON_FINISH` | 137 |
| `DNS` | 660 |
| `NON_STANDARD_UNRESOLVED` | 96 |

세부 비표준 코드 분포는 `0=85`, `91=3`, `92=134`, `93=11`, `94=378`, `95=271`, `99=11`이다. `93/94/95` 660행은 모두 `rcTime=0`으로 DNS 복합조건을 충족했다. 단일 코드와 복합조건 매핑은 `canonical.result_status_policy` 및 `canonical.result_status_composite_rule` seed에서 정책 버전별로 관리한다.

## 품질 이슈

| 규칙 | 심각도 | 건수 |
|---|---|---:|
| `NON_STANDARD_ORD` | WARNING | 893 |
| `RACE_WITHOUT_SALES` | WARNING | 18 |
| 전체 ERROR | ERROR | 0 |

매출 없는 18경주는 `canonical.race`와 `canonical.runner_result`에 유지하고 매출 분석에서만 제외한다. 2026년 최근 경주는 원천 집계 지연 가능성이 있으나 현재 원인을 확정하지 않는다.

다음 오류 규칙도 구현되어 있으며 발생 시 해당 업무 키를 Canonical로 승격하지 않는다.

- `INVALID_RACE_KEY`
- `DUPLICATE_RUNNER_KEY`
- `RACE_ATTRIBUTE_CONFLICT`
- `INVALID_SALES_ROW`
- `DUPLICATE_SALES_KEY`
- `SALES_WITHOUT_RACE`

## 누수 방지 경계

`canonical.sales_dividend.is_post_race`는 항상 true다. 매출과 확정배당은 시장 분석·사후 정산에만 사용하며 예측 Feature 입력으로 사용할 수 없다. 경주 결과와 매출 Canonical을 물리적으로 분리한다.

## 감사 결과

`canonical check`는 다음을 확인하며 실제 결과는 `issues=0`이다.

- transform run과 실제 테이블 행 수 일치
- 공식 착순이 1~16 범위인지 확인
- 모든 출전결과와 매출 행의 부모 경주 존재
- 모든 Canonical 행의 Staging lineage 존재
- `quality.data_issue`의 ERROR 부재

## 실행 명령

```powershell
python -m kra_analytics canonical build --race-batch-id 20260801T152038430395Z_api4_3_34c281ed --sales-batch-id 20260801T153512893532Z_api179_1_9d682cd1
python -m kra_analytics canonical check
```
