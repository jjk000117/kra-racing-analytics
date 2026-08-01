# KRA Racing Analytics

KRA 공식 OpenAPI 과거 데이터를 이용하는 Python + SQL + Power BI 기반 독립 분석 프로젝트입니다.

현재 상태는 **0단계: 프로젝트 계약 확정**입니다. 아직 수집기, SQL 스키마 또는 Power BI 모델은 구현하지 않았습니다.

## 확정된 방향

```text
KRA OpenAPI
  → Immutable Raw
  → SQL Raw Manifest
  → SQL Staging
  → SQL Canonical
  → SQL Star Schema / Mart
  → Jupyter 검증 및 Power BI
```

- 초기에는 과거 데이터를 수동 전체 수집합니다.
- 초기 데이터베이스는 DuckDB이며 기본 파일 위치는 `data/warehouse/kra.duckdb`입니다.
- Python과 Jupyter는 DuckDB를 직접 사용하고 Power BI는 Mart Parquet를 읽습니다.
- 최신 증분 수집과 자동 운영은 후속 확장으로 남깁니다.
- `request_id`, `batch_id`, SHA256, 적재시각과 변환 버전을 유지하여 나중에 증분 처리를 추가할 수 있게 합니다.
- 기존 `horse_racing` 저장소는 읽기 전용 참고 자료입니다.

## 문서

- [프로젝트 계약](PROJECT_CHARTER.md)
- [데이터 계층 계약](docs/data-contracts.md)
- [상태코드 정책](docs/status-code-policy.md)
- [Point-in-Time 및 누수 방지](docs/point-in-time-policy.md)
- [단계별 구현 기준](docs/implementation-gates.md)
- [데이터베이스 선택 ADR](docs/decisions/0001-database-selection.md)
