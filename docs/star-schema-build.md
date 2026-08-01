# 5C DuckDB Star Schema 구축 결과

## 구현 결과

Canonical을 수정하지 않고 `analytics` 스키마에 사업성 분석용 Dimension, Fact, Mart를
구축했다. 변환 버전은 `star_v1`이며 전체 재구축은 하나의 트랜잭션으로 실행된다.

| 객체 | Grain | 행 수 |
|---|---|---:|
| `analytics.dim_date` | 날짜 | 934 |
| `analytics.dim_meet` | 경마장 | 2 |
| `analytics.dim_race_grade` | 경주 등급 | 10 |
| `analytics.dim_pool` | 승식 | 7 |
| `analytics.fact_race` | 경주 | 4,600 |
| `analytics.fact_sales` | 경주 × 승식 | 32,074 |
| `analytics.mart_complete_race` | 시장 적격 경주 | 4,582 |
| `analytics.mart_market_sales` | 시장 적격 경주 × 승식 | 32,074 |

날짜 범위는 2024년 1월부터 2026년 7월까지 31개월이다. 수집 시작 월과 종료 월은
`dim_date.is_boundary_month`로 표시하여 월별 비교에서 부분 월 가능성을 구분한다.

## 시장 적격 경주 판정

`fact_race.is_market_eligible`은 다음 조건을 모두 만족할 때만 true다.

```text
race_status = COMPLETED
공식 승식 매핑 수 = 7
경주·승식 행 수 = 7
```

실제 분포는 다음과 같다.

| 경주 상태 | 시장 적격 | 경주 수 |
|---|---:|---:|
| `COMPLETED` | true | 4,582 |
| `COMPLETED` | false | 7 |
| `RACE_CANCELLED` | false | 2 |
| `RESULT_NOT_FINALIZED` | false | 9 |

정상 완료지만 매출이 없는 7경주는 0원으로 대체하지 않는다. 취소와 결과 미확정 경주도
Fact에는 남기고 시장 Mart에서만 제외한다.

## 생성한 분석 View

- `analytics.mart_complete_race`
- `analytics.mart_market_sales`
- `analytics.mart_monthly_market`
- `analytics.mart_meet_market`
- `analytics.mart_grade_market`
- `analytics.mart_grade_meet_market`

모든 요약 View는 7개 승식을 그대로 포함한다. 특정 승식을 모델 후보로 미리 지정하지 않는다.

## 대사 결과

- `fact_race`와 Canonical 경주 행 수 일치
- `fact_sales`와 Canonical 매출 행 수 일치
- 시장 적격 경주 4,582건 확인
- 시장 Mart의 모든 경주가 서로 다른 7개 승식을 정확히 한 번씩 보유
- Star 매출 합계와 Canonical 매출 합계 일치
- 매출 합계: 13,098,987,380,400원
- 등급·승식 미매핑 0건
- Fact 키 중복 0건
- Dimension 및 Canonical lineage 단절 0건
- Star 감사 결과: `issues=0`

## 실행 명령

```powershell
python -m kra_analytics star build
python -m kra_analytics star check
```

`star build`는 Canonical 감사가 통과한 경우에만 실행되며 동일 입력으로 반복 실행해도 같은
행 수와 업무키를 생성한다.

## 검증

- Pytest: 13개 통과
- Ruff: 통과
- Star 종단 테스트: 수집 → Staging → Canonical → Star 재구축과 반복 실행 검증
- mypy 1.20.2: 프로젝트 코드 오류가 아닌 도구 내부 오류로 완료되지 않음

## 다음 단계

다음 단계에서는 구축된 Mart를 사용해 월, 경마장, 등급, 승식별 시장 구조를 실제로 분석한다.
그 결과를 확인한 뒤 모델 후보 승식을 선정한다. 확정배당 원문의 적중 조합 정규화는 승식
후보 분석에 필요한 범위가 확정된 후 별도 설계한다.
