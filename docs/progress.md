# 프로젝트 진행 현황

이 문서는 프로젝트의 주요 마일스톤 완료 시 갱신한다. 현재 프로젝트 상태를 파악해야 하는
작업에서는 `progress.md`, `decision_log.md`, `experiment_log.md`를 함께 확인한다.

마지막 갱신: 2026-08-08

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

### 5E-2: 공식 적중배당 Canonical 테이블

- `경주 × 승식 × 공식 적중 조합` Grain의 `canonical.winning_payout` 구현
- 32,074개 매출·배당 원문에서 50,494개 조합 적재
- 마번 1~16, 순서형·비순서형 조합, 숫자형 배당과 원문 lineage 보존
- `canonical_v2`, `winning_payout_v1` 변환·파서 버전 적용
- 동착 순위와 승식별 조합 수 자동 대사 구현
- 연승식의 발매시점 출주두수 불확실성을 반영해 공식 원문을 우선하도록 처리
- Canonical과 기존 Star Schema 감사 `issues=0`
- Pytest 16개, Ruff, mypy와 실제 전체 재구축 멱등성 검사 통과

### 5F: 승식 후보 파레토 비교

- 승식별 경주 수를 제외하고 가능 조합 수와 나이브 적중확률 분포 계산
- 확정배당을 ROI가 아닌 시장 구조와 극단값 의존 지표로 비교
- 임의 가중치·종합점수 없이 시장 규모·적중확률·선택 공간·꼬리비율로 파레토 판정
- 연승식·복승식·복연승식·삼복승식을 비지배 후보로 유지
- 단승식·쌍승식·삼쌍승식은 다른 승식에 지배되어 1차 후보에서 제외
- 등록두수 기준과 동착 제외 민감도에서도 후보 집합이 유지됨을 확인

### 5G: 첫 모델과 복승 후속 방향 결정

- 첫 완성 모델을 연승식 적중 여부의 말 단위 확률모델로 확정
- 첫 모델의 목적을 Feature 파이프라인·날짜순 검증·확률평가·Calibration 완성으로 정의
- 복승식을 핵심 후속 목표로 유지하고 조합 직접 분류를 첫 기본안으로 결정
- 별도 결합모델과 순위 기반 공동확률은 복승 기준모델 이후 고도화 후보로 유지
- 연승 확률을 복승 조합확률로 자동 변환하지 않도록 모델 경계를 명시

### 6A: 연승 모델링 데이터 계약 설계

- 예측 단위를 `경주 × 베팅 가능 출전마`, 타깃을 공식 PLC 적중마 여부로 확정
- 연승 발매 마감 직전을 운영 예측시점으로 두고 일 단위 이력은 경주일 미만으로 제한
- 완료·PLC 공식 결과·모집단 복원 가능 경주만 지도학습 후보로 정의
- Feature 분류와 추가 API 판단 원칙만 확정하고 실제 목록은 6B로 이관
- 시간순 Train·Validation·Final Test와 확률평가·Calibration 계약 확정
- 현재 데이터의 발매 대상 모집단 복원 가능성을 6B의 선행 확인사항으로 지정

### 6B: Feature 가용성 검토 및 설계

- 4,582경주에서 `is_valid_start` 기반 개발 프록시 48,524행과 공식 양성 13,740행 확인
- 공식 연승 적중마 미결합과 invalid-start 양성 0건 확인
- DNS 659행·605경주의 발매 대상 불확실성을 확인하고 DNS 없는 3,977경주·42,632행을
  민감도 집합으로 정의
- 현재 기본 컬럼과 Point-in-Time 과거 이력 Feature 후보를 분류
- 마체중 100% 결측과 말 이력 없음 4,973행 등 가용성 한계 확인
- 부족한 정보를 계약 필수·기준모델 우선·성능 고도화·있으면 좋음으로 구분
- 추가 API는 기준모델과 가용성 검토 근거가 생긴 뒤 결정하도록 유지

### 6C 사전 검증: DNS 모델링 모집단 정책

- DNS 605경주의 경주별 DNS 수와 경주 진행·공식 승식 무결성을 재검증
- DNS 1두 555경주, 2두 46경주, 3두 4경주로 99.34%가 1~2두 취소임을 확인
- 경주 취소·결과 미확정·공식 승식 누락·타깃 이상 0건 확인
- DNS 말 659행만 제외하고 605경주와 실제 출전마 5,892행을 유지하도록 확정
- 주행정지 말 동반 13경주는 실제 출전 후 비완주로 보존
- DNS 없는 집합은 주 모집단이 아니라 선택적 민감도 비교로 변경

### 6C 사전 설계: Feature 후보와 KRA API 메타데이터 대조

- 연승 예측 Feature를 경주 맥락·출전마·과거 폼·관계자·부담·준비도·혈통·환경·시장·최종 출전 범주로 정리
- 현재 API4_3 기반 Point-in-Time 이력과 추가 KRA API의 제공 필드·예측시점 가용성을 비교
- 첫 역사적 Snapshot은 현 데이터로 진행하고 API26_2는 미래 경기의 사전 스냅샷 축적 후보로 제안
- API26_2 누적 성적·상금 11개 필드는 기존 Point-in-Time 오류 정책에 따라 계속 사용 금지
- Feature 계산식·Snapshot 구현·추가 API 수집은 수행하지 않음

### 6C 설계: 첫 역사적 Feature Snapshot 명세

- A안을 승인하고 첫 Snapshot 원천을 API4_3으로 한정
- 현재 기본정보 8개, 말 이력 14개, 기수 이력 3개, 조교사 이력 3개의 최소 Feature 28개 확정
- 정상 완주·주행중지·실격·DNS의 출전수·완주수·착순·PLC 적중·최근 폼 처리 규칙 확정
- 과거 PLC 적중률의 분모를 실제 출전수로 정의하고 완주율·평균착순과 분리
- 이력 부족, NULL, 좌측 절단, 같은 날짜 제외와 Point-in-Time 감사 컬럼 정의
- Feature Snapshot 구현은 수행하지 않음

### API26_2 과거 출전표 Point-in-Time 표본 검증

- 서울·부산경남 2두의 2024~2025 과거 경주일 8건을 실제 호출
- API26 Raw 응답 8건과 redacted 요청·SHA256 Manifest를 기존 구조로 보존
- 통산·최근1년 출전 및 1·2·3위 횟수가 말별 모든 과거 날짜에서 고정됨을 확인
- 누적 8개 필드를 현재값/사후값으로 판정해 Historical Feature 사용 금지 유지
- 레이팅·부담중량·등록두수와 경주·출전 기본정보 13개는 API4 과거값과 8/8 일치
- Snapshot 구현과 API26 대량 수집은 수행하지 않음

## 진행 중인 작업

현재 진행 중인 구현은 없다.

## 다음 추천 작업

### 6C: Feature Snapshot 구현

1. API26 검증으로 PIT 후보가 된 레이팅을 첫 Snapshot에 추가할지 결정한다.
2. 최종 승인된 Feature와 관리·감사 컬럼을 SQL/Python으로 구현한다.
3. 상태별 분모·분자와 최근 5회 경계 단위 검사를 작성한다.
4. `source_max_event_date < race_date`와 같은 날짜 결과 제외를 검사한다.
5. 구현 결과의 행 수·업무키·타깃 결합·NULL 분포를 위험 범위에 맞게 검증한다.

적중배당은 경주 후 정보이므로 모델 Feature에는 사용하지 않고 시장 구조 분석과 백테스트
정산에만 사용한다.

## 현재 주요 산출물

- `docs/star-schema-design.md`
- `docs/star-schema-build.md`
- `docs/market-structure-analysis.md`
- `docs/confirmed-odds-profiling.md`
- `docs/winning-payout-canonical-build.md`
- `docs/pool-candidate-pareto-analysis.md`
- `docs/model-scope-decision.md`
- `docs/place-model-data-contract.md`
- `docs/feature-availability-review.md`
- `docs/dns-population-policy-validation.md`
- `docs/feature-api-metadata-review.md`
- `docs/feature-snapshot-spec.md`
- `docs/api26-pit-validation.md`
- `notebooks/05d_market_structure_analysis.ipynb`
- `notebooks/05e_confirmed_odds_profiling.ipynb`
- `notebooks/06b_feature_availability_analysis.ipynb`
- `notebooks/06c_dns_policy_validation.ipynb`
- `sql/analysis/`
