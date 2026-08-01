# 상태코드 처리 정책

## 원칙

출전 참여와 수치 착순을 분리한다.

- `valid_start`: 이력의 출전·노출 건수에 포함할 수 있는 이벤트
- `valid_finish`: 평균착순, 최근착순, 승·연승 횟수와 비율에 사용할 수 있는 공식 수치 착순

초기 계승 정책은 다음과 같다.

- 공식 착순 `1~16`: `valid_start=true`, `valid_finish=true`
- 코드 `91`, `92`: `valid_start=true`, `valid_finish=false`
- 그 밖의 특수 코드: 기본적으로 두 값 모두 `false`
- 미등록 코드는 추정하지 않고 `UNKNOWN`으로 분류하여 품질 이슈를 생성한다.

Canonical `race_status_v1`의 실제 저장 상태는 다음과 같다.

| `ord` | `result_status` | valid start | valid finish |
|---|---|---:|---:|
| 1~16 | `FINISHED` | true | true |
| 91, 92 | `PARTICIPATED_NON_FINISH` | true | false |
| 93, 94, 95이며 `rcTime=0` | `DNS` | false | false |
| 0, 93, 94, 95, 99이며 위 복합조건 불충족 | `NON_STANDARD_UNRESOLVED` | false | false |
| 결측 | `MISSING` | false | false |

참고 저장소에서 확정한 `93/94/95 + rcTime=0` 복합조건은 Canonical에서도 DNS로 사용한다. 단일 `ord` 코드만으로는 DNS를 판정하지 않는다.

상태코드 매핑은 SQL 참조 테이블 또는 버전 관리된 seed로 관리하며 변환 코드에 흩어져 하드코딩하지 않는다.

단일 코드 seed는 `canonical.result_status_policy`, `ord+rcTime` 복합규칙은 `canonical.result_status_composite_rule`에 `policy_version=race_status_v1`로 저장한다.

## 집계 규칙

- 평균·최소·최대·최근 착순에는 `valid_finish`만 사용한다.
- `wins`: 유효 착순 1
- `places`: 유효 착순 1~3
- 승률과 연승률의 분모는 유효 착순 건수로 명시한다.
- 출전 수와 유효 착순 수를 별도 지표로 제공한다.
- 결측치를 0이나 정상 이력으로 대체하지 않는다.

## 확정 전 검증

실제 수집 데이터에서 모든 `ord` 값의 빈도와 대표 원본을 감사한다. 알려지지 않은 코드가 발견되면 공식 근거를 확인한 후 매핑 버전을 올린다.
