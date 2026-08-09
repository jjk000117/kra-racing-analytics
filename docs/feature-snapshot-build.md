# 6C 연승 Feature Snapshot 생성

생성일: 2026-08-09  
상태: 승인된 29개 Feature 생성·감사 완료, 모델 미학습

## 결과

`place_feature_snapshot_v1`을 DuckDB `mart.feature_snapshot_place`에 생성했다.

| 항목 | 결과 |
|---|---:|
| Snapshot 행 | 48,524 |
| 경주 | 4,582 |
| 공식 연승 양성 | 13,740 |
| 말 과거 이력 없음 | 4,973 |
| PIT 위반 | 0 |
| 감사 이슈 | 0 |

행 Grain은 `race_id + horse_id`다. 기존 시장 적격 경주의 `is_valid_start=true` 행만 포함하므로
DNS는 제외되고 주행중지 133행과 실격 3행은 실제 출전으로 유지됐다.

## 구현 범위

- 현재 경주 기본정보 9개: 기존 8개와 `rating`
- 말 이력 14개
- 기수 이력 3개
- 조교사 이력 3개
- 공식 PLC `place_hit` 타깃과 관리·감사 컬럼
- Snapshot 실행 이력: `mart.feature_snapshot_run`

Feature 계산식과 상태별 분모·분자는 `docs/feature-snapshot-spec.md`를 그대로 구현했다. 속도,
G1F, G3F, S1F, 코너, 주로, 마체중 Feature는 생성하지 않았다. API37 누적 구간기록도 참조하지
않는다.

## Point-in-Time 구현

모든 말·기수·조교사 이력은 다음 조건을 먼저 적용한다.

```text
historical.race_date < current.race_date = feature_as_of
```

같은 날짜의 다른 경주는 전부 제외한다. Snapshot에는 각 행이 참조한 가장 늦은 과거 경주일을
`source_max_event_date`로 저장하며 감사에서 다음을 강제한다.

```text
source_max_event_date IS NULL
OR source_max_event_date < feature_as_of
```

현재 결과의 착순·기록·배당·매출은 Feature 계산에 사용하지 않는다. 현재 결과상태와
`place_hit`은 모집단·타깃 감사 컬럼으로만 저장한다.

## 검증 결과

| 검증 | 결과 |
|---|---:|
| `race_id + horse_id` 중복 | 0 |
| 모집단 행 수 불일치 | 0 |
| 공식 PLC 타깃 불일치 | 0 |
| API4 `rating` 원천 불일치 | 0 |
| `source_max_event_date >= feature_as_of` | 0 |
| DNS 포함 | 0 |
| 상태 정책 불일치 | 0 |
| 비율 범위·분모·NULL 규칙 위반 | 0 |
| `history_complete=true` | 0 |

추가 가용성 결과:

- `rating`, `horse_age`, `carried_weight` NULL: 각각 0행
- 모든 역사적 원천일이 NULL인 행: 212행
- 최근 5회가 모두 존재하는 행: 27,638행
- 동일거리 과거 이력이 없는 행: 15,115행
- 기수·조교사 ID NULL: 각각 0행
- 관측 범위: 2024-01-05~2026-07-26
- 가장 늦은 참조 과거일: 2026-07-25

## 재현 명령

```powershell
conda run -n kra-racing-analytics kra-analytics feature build
conda run -n kra-racing-analytics kra-analytics feature check
```

`feature build`는 하나의 트랜잭션에서 현재 Snapshot을 재구축하고, 전용 감사에 실패하면
rollback한다. 동일 입력으로 다시 실행해도 같은 Grain과 집계 결과를 만든다.

## 구현 경로

- DDL: `sql/ddl/008_create_feature_snapshot.sql`
- 변환 SQL: `sql/transforms/003_build_feature_snapshot.sql`
- Python 실행·감사: `src/kra_analytics/feature_snapshot.py`
- CLI: `src/kra_analytics/cli.py`
- 단위 테스트: `tests/test_feature_snapshot.py`

모델 학습, 데이터 분할, Calibration과 성능평가는 이번 단계에서 수행하지 않았다.
