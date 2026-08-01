# KRA Racing Analytics

KRA 공식 OpenAPI 과거 데이터를 이용하는 Python + SQL 기반 독립 분석 프로젝트입니다.

현재 상태는 **2단계: Historical Collector와 Manifest 완료**입니다. API4_3 경주 결과와 API179_1 매출·확정배당을 같은 기간으로 수집했습니다.

## 확정된 방향

```text
KRA OpenAPI
  → Immutable Raw
  → SQL Raw Manifest
  → SQL Staging
  → SQL Canonical
  → SQL Star Schema / Mart
  → Jupyter 검증 및 후속 보고서/포트폴리오
```

- 초기에는 과거 데이터를 수동 전체 수집합니다.
- 초기 데이터베이스는 DuckDB이며 기본 파일 위치는 `data/warehouse/kra.duckdb`입니다.
- Python은 기존 Anaconda의 전용 `kra-racing-analytics` Conda 환경에서 실행합니다.
- 브라우저 JupyterLab은 탐색과 검증에 사용합니다.
- 시각화·보고서 도구는 데이터 계층 완성 후 선택하고 Mart Parquet를 공통 인터페이스로 지원합니다.
- 최신 증분 수집과 자동 운영은 후속 확장으로 남깁니다.
- `request_id`, `batch_id`, SHA256, 적재시각과 변환 버전을 유지하여 나중에 증분 처리를 추가할 수 있게 합니다.
- 기존 `horse_racing` 저장소는 읽기 전용 참고 자료입니다.

## 문서

- [프로젝트 계약](PROJECT_CHARTER.md)
- [데이터 계층 계약](docs/data-contracts.md)
- [상태코드 정책](docs/status-code-policy.md)
- [Point-in-Time 및 누수 방지](docs/point-in-time-policy.md)
- [단계별 구현 기준](docs/implementation-gates.md)
- [API4_3 수집 실행 기록](docs/api4_3-collection.md)
- [API179_1 수집 실행 기록](docs/api179-collection.md)
- [데이터베이스 선택 ADR](docs/decisions/0001-database-selection.md)
- [Python 환경 선택 ADR](docs/decisions/0002-python-environment.md)

## 개발 환경

기존 Anaconda의 `base`와 분리된 프로젝트 환경을 사용합니다.

```powershell
C:\Users\jjk00\anaconda3\Scripts\conda.exe run -n kra-racing-analytics python --version
```

패키지 설치 후 주요 명령은 다음과 같습니다.

```powershell
C:\Users\jjk00\anaconda3\Scripts\conda.exe run -n kra-racing-analytics python -m kra_analytics doctor
C:\Users\jjk00\anaconda3\Scripts\conda.exe run -n kra-racing-analytics python -m kra_analytics database init
C:\Users\jjk00\anaconda3\Scripts\conda.exe run -n kra-racing-analytics python -m kra_analytics database check
C:\Users\jjk00\anaconda3\Scripts\conda.exe run -n kra-racing-analytics jupyter lab
```

## API4_3 수집 명령

`KRA_API_KEY`가 프로세스 환경에 설정된 상태에서 실행합니다. 키는 명령 출력, Raw 경로, Manifest URL에 기록하지 않습니다.

```powershell
python -m kra_analytics collect race-results --year 2024 --year 2025 --year 2026 --meet 1 --meet 3 --all-pages --page-size 1000
python -m kra_analytics collect audit <batch_id>
```

API179_1은 같은 기간을 다음 명령으로 수집합니다.

```powershell
python -m kra_analytics collect sales --year 2024 --year 2025 --year 2026 --meet 1 --meet 3 --all-pages --page-size 1000
```
