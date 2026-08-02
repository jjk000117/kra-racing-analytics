# 프로젝트 진행 현황

이 문서는 프로젝트의 주요 마일스톤 완료 시 갱신한다. 현재 프로젝트 상태를 파악해야 하는
작업에서는 `progress.md`, `decision_log.md`, `experiment_log.md`를 함께 확인한다.

마지막 갱신: 2026-08-02

## 현재 완료한 작업

### 0단계: 프로젝트 계약과 정책

- Python + SQL + DuckDB 기반 독립 프로젝트 구조 확정
- 기존 `horse_racing` 저장소를 읽기 전용 참고자료로 제한
- Raw 불변성, Manifest, 상태코드, Point-in-Time과 데이터 누수 방지 정책 문서화
- 기존 Anaconda와 프로젝트 전용 `kra-racing-analytics` Conda 환경 사용

### 1단계: 개발 환경

- Python 패키지와 CLI 구조 구성
- DuckDB 초기화와 필수 스키마 검사 구현
- Pytest, Ruff, mypy 개발 도구 구성
- JupyterLab을 재현 가능한 분석 환경으로 채택

### 2단계: Historical API 수집과 Raw 검증

- API4_3 경주결과 수집: 49,386행
- API179_1 매출·확정배당 수집: 32,074행
- 요청·응답·Raw 파일·SHA256·배치 Manifest 연결
- 두 API의 경주 범위와 Raw 완전성 프로파일링

### 3단계: SQL Staging

- Raw 원문을 변경하지 않는 DuckDB Staging 적재 구현
- 경주결과 49,386행, 매출 32,074행 적재
- 재실행 멱등성, 파싱 상태, Raw lineage와 행 수 대사 검증

### 4단계: Canonical과 품질검사

- Canonical 경주 4,600건, 출전결과 49,386건, 매출 32,074건 생성
- 버전 관리되는 경주결과 상태 정책과 복합 DNS 규칙 구현
- 경주 취소 2건과 결과 미확정 9건을 경주 단위 예외로 관리
- 취소 사유는 분석 상태에서 제거하고 근거 메모에만 보존
- 품질 이슈 911건 기록, ERROR 0건, Canonical 감사 `issues=0`

### 5B: 사업성 분석용 Star Schema 설계

- 날짜·경마장·등급·승식 Dimension 설계
- 경주와 경주×승식 Fact Grain 확정
- Canonical 전체를 보존하고 시장 Mart에서만 적격 경주를 선택하도록 설계
- 10개 등급과 7개 승식을 사전 제외 없이 유지

### 5C: DuckDB Star Schema와 Mart

- `analytics` Dimension, Fact, 요약 View 구현
- `fact_race` 4,600행, `fact_sales` 32,074행 생성
- 정상 완료·7개 공식 승식 완전 경주 4,582건 선정
- 월·경마장·등급·승식별 분석 Mart 생성
- 키·매핑·lineage·매출 합계 감사 `issues=0`

### 5D: 시장 구조 분석

- 실행된 Jupyter Notebook과 재현 가능한 SQL 작성
- 2024-01-05~2026-07-26의 시장 적격 경주 4,582건 분석
- 월별 경주당 평균 매출 변동계수 약 5% 확인
- 서울·부산경남 모두 유지하고 경마장 차원으로 통제하기로 결정
- 등급별 규모와 경주당 매출 차이를 확인하고 10개 등급 전체 유지
- 7개 승식 시장 구성을 비교하되 매출만으로 후보를 선정하지 않음
- Pytest 13개, Ruff, Notebook 전체 실행과 집계 대사 통과

### 5E-1: 공식 적중배당 원문 프로파일링

- 시장 적격 4,582경주 × 7개 승식의 `confirmed_odds_raw` 32,074행 검사
- 원본 행 결측 0건, 50,494개 공식 적중 조합 파싱 성공
- 동착과 출전두수 규칙으로 승식별 한 행에 1~6개 조합이 존재함을 확인
- 마번 ①~⑮와 `(16)`, 공백 2개 구분자, 정수·소수 배당 형식 확인
- 중복 마번·중복 조합·0 이하 배당·파싱 오류 0건
- 실행된 Jupyter Notebook, 재사용 가능한 프로파일링 파서와 단위 테스트 작성

## 진행 중인 작업

현재 진행 중인 구현은 없다.

## 다음 추천 작업

### 5E-2: 공식 적중배당 Canonical 테이블 구현

1. 목표 Grain을 `경주 × 승식 × 공식 적중 조합`으로 구현한다.
2. 원문, 조합 순서, 정수 마번, 확정배당과 lineage를 보존한다.
3. 순서형 승식은 원문 순서를 유지하고 비순서형 승식은 canonical 조합을 함께 저장한다.
4. 파싱 실패, 중복 조합, 선택 수 불일치와 비양수 배당 감사를 추가한다.
5. Canonical·Star 전체 대사와 재실행 멱등성을 검증한다.

적중배당은 경주 후 정보이므로 모델 Feature에는 사용하지 않고 시장 구조 분석과 백테스트
정산에만 사용한다.

## 현재 주요 산출물

- `docs/star-schema-design.md`
- `docs/star-schema-build.md`
- `docs/market-structure-analysis.md`
- `docs/confirmed-odds-profiling.md`
- `notebooks/05d_market_structure_analysis.ipynb`
- `notebooks/05e_confirmed_odds_profiling.ipynb`
- `sql/analysis/`
