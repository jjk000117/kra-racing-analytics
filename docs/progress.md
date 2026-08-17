# 프로젝트 진행 현황

이 문서는 프로젝트의 주요 마일스톤 완료 시 갱신한다. 현재 프로젝트 상태를 파악해야 하는
작업에서는 `progress.md`, `decision_log.md`, `experiment_log.md`를 함께 확인한다.

## 2026-08-12 — KRA API 장애 범위 및 ServiceKey 노출 방지

- 공통 redaction 함수와 안전한 예외 문자열 경로를 구현하고 API4/API179 collector에 적용했다.
- 저장소 파일과 Manifest 100행에서 실제 키 노출 0건을 확인했다.
- API4는 호출 1회 후 진단 파서가 오류 envelope를 처리하지 못해 이번 상태 요약을 남기지 못했고
  호출 제한에 따라 재시도하지 않았다.
- 비교 API156/API155는 각각 1회 호출해 모두 HTTP 403을 확인했다.
- 비교 API 권한 여부가 미확정이므로 KRA 공통 장애나 키 전체 인증 실패로 단정하지 않았다.
- 2022·2023 전체 Raw 수집은 재개하지 않았다.
- 상세 문서: `docs/kra-api-failure-diagnostic.md`

### 활용신청 후 API4 공식 링크·호출방식 재확인

- 데이터셋 `15058305`의 Base URL과 operation이 코드의 `API4_3/raceResult_3`과 일치함을 확인했다.
- 필수·선택 파라미터와 ServiceKey 인코딩 방식에서 문제를 발견하지 못했다.
- 2022 서울 1행을 다시 한 번 호출해 HTTP 200, `resultCode=99`, 세션 `100/100`을 확인했다.
- application 계층 장애가 계속되어 2022·2023 전체 수집은 재개하지 않았다.

### 비교 API 활용신청 반영 확인

- API156과 API155가 활용신청 전 HTTP 403에서 활용신청 후 HTTP 200으로 바뀌었다.
- 두 API 모두 API4와 동일한 `resultCode=99`, 세션 `100/100`을 반환했다.
- 세 API 공통 application/연동 계층 장애 가능성이 가장 높은 Case B로 진단을 갱신했다.
- 정상 데이터는 반환되지 않았고 전체 수집은 계속 보류했다.

## 2026-08-12 — Official place baseline cutoff 및 v2 Feature 사전 이용 가능성 검증

- prediction cutoff를 결과 발생 전 실제 베팅 의사결정 시점으로 확정하되 `T-N분`은 보류했다.
- 실시간 배당을 baseline 입력에서 제외하고 betting-stage로 분리했다.
- 마체중·증감·날씨·주로상태·함수율·부가상금과 과거 G3F/G1F의 공식 의미를 검증했다.
- registry 141개를 `APPROVED` 35, `APPROVED_WITH_FLAG` 91, `NEEDS_VALIDATION` 0,
  `DEFERRED` 5, `PROHIBITED` 10으로 갱신했다.
- Snapshot v2 즉시 구현 후보는 126개이며 Snapshot 생성과 모델 학습은 수행하지 않았다.
- 상세 문서: `docs/official-place-baseline-cutoff-validation-v2.md`

## 2026-08-12 — Place Feature Snapshot v2 candidate 구현·감사

- Registry 중복 5개를 제거하고 누락된 G3F/G1F companion count 4개를 추가했다.
- Registry 140개, 즉시 구현 대상 고유 Feature 125개로 확정했다.
- 서울/부산경남 S1F 및 최종 G3F/G1F 공통화를 검증했다.
- `mart.place_feature_snapshot_v2_candidate` 48,524행·4,582경주·125 Feature를 생성했다.
- Grain·모집단·PIT·금지 사후정보·count/rate/availability 감사를 통과했다.
- 기존 baseline_v1과 Final Test 산출물은 변경하지 않았다.
- 상세 문서: `docs/place-feature-snapshot-v2-build.md`

## 2026-08-12 — Official place baseline v2 모델 입력 설계

- Snapshot 125개 Feature의 타입·결측·family·companion·모델링 역할을 전수 분류했다.
- 117개를 모델 입력 후보로 제안하고 정의상 복원 가능한 count/flag 6개를 구조 제외했다.
- 거리·경마장을 혼합한 절대 race-time median 2개는 `REVIEW_REQUIRED`로 분리했다.
- 125개 Feature 안의 `AUDIT_ONLY`는 0개이며 ID·lineage·타깃 등 22개 관리 컬럼을 모델에서 제외했다.
- recent3/5/10, 조건 적성, sectional과 family-level ablation 계약을 문서화했다.
- 모델 학습·성능 기반 선택·기존 baseline 재평가는 수행하지 않았다.
- 상세 문서: `docs/official-place-baseline-v2-model-input-design.md`

마지막 갱신: 2026-08-11

## 2026-08-11 새 공식 baseline Feature universe 재설계

- `place_logistic_baseline_v1`을 공식 기준모델이 아닌 historical experiment로 전환했다.
- API4 공식 89개 필드와 실제 Staging 49,386행을 전수 대조했다.
- 기존 계층을 변경하지 않는 `semantic.api4_runner_event_v2` View를 추가했다.
- `rcTime` 정밀도, `wgHr` 중량·증감, `track` 상태·함수율을 명확한 새 컬럼으로 정규화했다.
- S1F만 공통 의미로 매핑하고 G3F/G1F는 검증 전 경마장별로 분리했다.
- Feature 후보 141개 registry 작성: 승인 27, 플래그부 승인 87, 검증 필요 12, 후속 5, 금지 10.
- 새 공식 baseline Snapshot 후보 114개를 제안했지만 Snapshot과 모델은 아직 생성하지 않았다.

관련 문서:

- `docs/official-baseline-feature-universe-v2.md`
- `docs/official-baseline-snapshot-candidate-v2.md`
- `docs/api4-field-audit-v2.csv`
- `docs/place-feature-registry-v2.csv`

## 2026-08-11 API4 2022·2023 Raw 전체 수집 시도

- 2022년 서울·부산경남 수집 batch를 시작했으나 API가 두 요청 모두 `가용한 세션이 존재하지 않습니다. (100/100)`을 반환했다.
- 두 차례의 최소 표본 재확인에서도 같은 응답이 반복되어 외부 서비스 포화로 판정했다.
- 실패 Raw 2개와 Manifest는 보존했으며 batch audit 문제는 0건이다.
- 성공 수집 행은 0건이고 2023년 수집은 시작하지 않았다.
- 2022·2023 Staging 행은 모두 0건이며 기존 모델·진단 산출물은 변경되지 않았다.
- 다음 작업: API 회복 후 새 batch로 2022 전체 수집·audit, 이어서 2023 전체 수집·audit.

관련 문서: `docs/api4-history-raw-collection.md`

## 2026-08-11 API4 상태 재확인과 Raw·Feature 대조

- 2022년 서울 1페이지·1행을 한 번만 요청했으나 `resultCode=99`, 세션 100/100 오류가 반복됐다.
- 추가 재시도와 2022·2023 전체 수집은 수행하지 않았다.
- API4 89개 Raw 필드는 Staging에 모두 보존되지만 속도·구간·마체중·환경 필드는 현재 Snapshot과 모델에 없다.
- 구간기록은 Canonical에 미보존이고 `wgHr` 파싱 결과는 전 행 NULL이다.
- Canonical `race_time INTEGER`는 소수 정밀도를 잃으므로 후속 속도 Feature는 Staging `rcTime` 원문을 사용해야 한다.
- Snapshot·baseline_v1·Final Test 산출물은 변경하지 않았다.

관련 문서: `docs/api4-raw-feature-gap-audit.md`

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
- Canonical 마체중 결측과 말 이력 없음 4,973행 등 가용성 한계 확인. 후속 검증에서 마체중 원문은
  staging에 존재하고 결측 원인은 문자열 파싱 공백임을 확인
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
- 현재 기본정보 9개, 말 이력 14개, 기수 이력 3개, 조교사 이력 3개의 최소 Feature 29개 확정
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

### 6C 사전 검증: API26 `ilsu`와 속도·구간기록 원천

- `ilsu`가 말의 출전 간격이 아닌 경마장·경주일 단위 `경주일수`임을 확인
- API26의 조건·상금 관련 중복 필드 12개를 API4와 8/8 대조
- 첫 Snapshot 즉시 추가 권장 후보를 `rating` 하나로 좁힘
- API4에 valid-start 48,524행의 최종·구간기록, 날씨, 주로·함수율, 마체중·증감, 착차 원문이
  이미 있음을 확인
- API37 누적 구간기록은 요청 경주일 포함으로 PIT 위험이 있어 사용 금지
- 추가 API 호출·대량 수집·Snapshot·모델 구현은 수행하지 않음
- 검증 결과를 승인해 `rating`을 첫 모델 입력에 추가하고 29개 Feature 명세로 갱신
- `ilsu`는 제외하고 속도·구간·주로·마체중은 기준모델 이후 API4 개별 과거 기록으로 직접 계산

### 6C: 연승 Feature Snapshot 생성·검증

- `rating`을 포함한 승인된 29개 Feature를 `place_feature_snapshot_v1`로 구현
- `mart.feature_snapshot_place`에 4,582경주·48,524행 생성
- 공식 연승 양성 13,740행과 말 과거 이력 없음 4,973행 확인
- DNS는 제외하고 주행중지 133행·실격 3행은 실제 출전으로 보존
- 같은 날짜를 제외하고 `source_max_event_date < feature_as_of`를 강제
- 모집단·업무키·타깃·rating 원천·상태·비율·NULL·PIT 감사 `issues=0`
- 속도·G1F·G3F Feature와 모델 학습은 수행하지 않음

### 6D 사전 분석: Snapshot 월별 분포

- 월별 경주 108~180개, 출전마 1,230~1,952행과 PLC 양성률 25.88~30.51% 확인
- 말·기수·조교사 이력 가용률과 prior count P25/P50/P75 프로파일링
- 기수·조교사 left-censoring은 2024년 2~3월부터 거의 해소됨을 확인
- 말 이력은 2024년 10월부터 가용률 약 91~97%, 중앙 prior count 5회 이상
- warm-up 및 날짜순 분할 후보 A/B/C 비교 후 후보 B를 공식 분할로 확정
- Warm-up 2024-01~09, Train 2024-10~2025-09, Validation 2025-10~12,
  Final Test 2026-01~07로 고정
- Warm-up은 Feature 이력 계산에 사용하되 모델 학습 표본에서는 제외
- 모델 학습·전처리·Calibration은 수행하지 않음

### 6D: 기준모델 및 평가 설계

- Snapshot Feature 29개를 유지하고 `horse_prior_plc_hit_count`를 관리·감사용으로만 확정
- 첫 Logistic Regression 기준모델 입력을 28개로 확정
- Train에서만 범주 사전·결측 중앙값·표준화 통계를 적합하도록 전처리 계약 정의
- Train 양성률 무정보 기준선과 고정 설정 L2 Logistic Regression 비교 구조 확정
- Train 내부 분기별 expanding-window OOF 예측으로 sigmoid Calibration을 적합하도록 설계
- Validation에서 원본·보정 확률을 선택하고 Final Test는 모든 선택 후 한 번만 평가하도록 봉인
- macro Log Loss를 주 선택 지표, macro Brier와 Calibration 진단을 보조 지표로 정의
- Validation 선택·봉인 후 Train+Validation으로 동일 절차를 재적합하는 선택안 2 확정
- sigmoid 선택 시 Train+Validation에서 과거 학습→이후 3개월 OOF 원칙으로 calibrator 재적합
- 모델·전처리기·Calibration 적합과 Final Test 평가는 수행하지 않음

### 6D: 기준모델 Validation 선택·봉인 및 재적합

- 29개 Snapshot Feature 중 감사 전용 1개를 제외한 28개 입력 Pipeline 구현
- Train 전용 전처리, 무정보 기준선, Logistic 원본과 Train OOF sigmoid 후보 실행
- Validation 4,823행·439경주에서 Logistic 원본 선택
- macro Log Loss: 기준선 0.589293, 원본 0.512157, sigmoid 0.513856
- macro Brier: 기준선 0.199888, 원본 0.169727, sigmoid 0.170210
- 선택 상태를 `SEALED_BEFORE_FINAL_TEST`로 기록하고 Train+Validation 23,711행으로 재적합
- sigmoid 미선택에 따라 최종 calibrator 재적합은 실행 대상에서 제외
- 모델링 단위 테스트 6개, 전체 Pytest 23개, Ruff `src tests`, mypy 통과
- Final Test 예측·평가 미실행 및 산출물 부재 확인

### 6D: 봉인된 Final Test 1회 평가

- 봉인 contract와 Pipeline SHA256 일치 확인 후 1회 전용 명령으로 평가
- Final Test 2026-01~07의 1,050경주·11,179행 사용
- Logistic macro Log Loss 0.532267, macro Brier 0.177908
- 무정보 기준선 macro Log Loss 0.598040, macro Brier 0.203972
- Logistic micro Log Loss 0.529311, micro Brier 0.176639
- Calibration intercept 0.057017, slope 0.986839
- Validation 대비 Logistic macro Log Loss +0.020110, macro Brier +0.008181
- 평가 중 재적합·설정 변경 없음, 결과 존재 시 재실행 거부

### 6E: 월별 expanding Walk-forward 시간 안정성 진단

- baseline_v1과 동일한 최초 학습기간 2024-10~2025-09로 첫 Fold 시작
- Warm-up 이력이 반영된 기존 Snapshot과 고정 28개 raw Logistic 절차 사용
- 2025-10~2026-07의 월별 10개 expanding Fold 실행
- 2025-10~2026-04 macro Log Loss 평균 0.515343
- 2026-05~07 평균 0.551345, 월별 0.533→0.551→0.570으로 연속 상승
- 모든 월에서 무정보 기준선보다 Log Loss·Brier 개선 유지
- 7월 calibration intercept -0.252, slope 0.768과 과대예측 방향 drift 관찰
- 3개월 이동평균은 보조 진단으로만 기록
- 기존 baseline contract·Pipeline·Final Test 결과 해시 불변 확인

### 6F: 2026-05~07 Feature·타깃·경주 구성 drift 진단

- 안정기간 1,034경주·11,357행과 저하기간 455경주·4,645행 비교
- 모든 28개 입력의 평균·P10/P25/P50/P75/P90·NULL률 비교
- 경주 Grain 경마장·등급·거리·등록두수와 행 Grain 범주 비중 비교
- 12두 경주 비중 31.62%→0.22%, 8~10두 경주 16.45%→40.22% 확인
- PLC 양성률 27.32%→29.36%, +2.04%p
- 안정기간 등록두수별 비율을 저하기간 mix에 적용한 기대 양성률 29.30%
- 최근5 PLC 적중률 P75 0.50→0.40, 최근 평균착순 중앙 5.60→5.75
- history availability와 관계자 적중률은 대체로 안정적
- 모델 학습·Feature 선택·Calibration·baseline 산출물 변경 없음

## 진행 중인 작업

현재 진행 중인 구현은 없다.

## 2026-08-10 — API4 2022·2023 확장 수집 사전 검토 완료

- 2022·2023 × 서울·부산경남의 월별 메타데이터 48건과 대표 경주일 12건을 실제 조회했다.
- 모든 월에 데이터가 있었고 대표 일자 12/12가 정상 응답했다.
- 과거 표본 89개 필드는 2024 Raw와 누락·추가 없이 일치했다.
- 2022·2023 출전행은 각각 18,355건, 19,284건으로 현재 연간 규모와 유사했다.
- 2022년은 실제 연속성은 양호하지만 공식 계획에 코로나 탄력운영 규칙이 남아 있어 warm-up
  중심 사용을 권장한다.
- 권장 수집기간은 2022-01~2023-12, 보수적 모델 비교 시작점은 2023-01-01이다.
- 대량 수집, Raw/DB 변경, Snapshot·모델·기존 평가 변경은 수행하지 않았다.

다음 추천 작업은 승인 후 2022·2023을 분리 batch로 전체 Raw 수집하고 Raw audit까지만 수행하는
것이다.

## 2026-08-10 — 등록두수 조건부 손실 진단 완료

- 안정기간 1,034경주와 저하기간 455경주의 walk-forward 손실을 등록두수별로 분해했다.
- pooled Macro Log Loss 상승 +0.034512 중 구성 효과는 +0.013978(40.5%), 동일 등록두수
  내 효과는 +0.020334(58.9%)였다.
- Macro Brier 상승 +0.014377 중 구성 효과는 33.8%, 동일 등록두수 내 효과는 65.7%였다.
- 등록두수 mix만으로 전체 저하가 설명되지 않았으며 9·10·11두 경주의 동일 조건 손실 상승이
  함께 확인됐다.
- 기존 baseline_v1, Final Test, walk-forward, Feature drift, bootstrap 산출물은 변경하지 않았다.

다음 추천 작업은 9·10·11두 경주의 월별 오류가 경마장·거리·등급 또는 확률 오차 방향에
집중되는지 제한적으로 확인하는 것이다.

## 2026-08-09 — 경주 단위 Bootstrap 안정성 진단 완료

- 안정기간 2025-10~2026-04의 1,034경주 손실을 모집단으로 사용했다.
- 2026-05/06/07 실제 경주 수 175/140/140에 맞춰 경주 단위 복원추출을 10,000회 수행했다.
- 5월 실제 손실은 두 지표 모두 P97.5 밖이며 경험적 같거나 나쁜 비율은 Log Loss 1.20%,
  Brier 0.70%였다.
- 6월·7월과 3개월 동일가중 평균은 두 지표 모두 0/10,000이었다.
- 자연스러운 경주 표본 변동만으로 후반부 저하 전체를 설명하기 어렵다는 진단이며,
  가설검정이나 drift 증명으로 해석하지 않는다.
- 기존 baseline_v1, Final Test, walk-forward, Feature drift 산출물은 변경하지 않았다.

다음 추천 작업은 별도 승인 후 `registered_runner_count` 조건부 손실 분석이다.

## 다음 추천 작업

### 다음 추천 작업: 진단 결과 해석과 후속 실험 경계 결정

1. 등록두수 mix 변화와 최근 폼 변화 중 후속 검증 가치가 있는 항목을 정한다.
2. 기존 Final Test를 재선택에 사용하지 않는 새 평가 계약을 먼저 설계한다.
3. 그 계약 승인 뒤에만 별도 버전의 Feature·모델 고도화를 시작한다.

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
- `docs/api26-ilsu-speed-source-validation.md`
- `docs/feature-snapshot-build.md`
- `docs/feature-snapshot-monthly-profile.md`
- `docs/baseline-model-evaluation-design.md`
- `docs/baseline-validation-result.md`
- `docs/final-test-result.md`
- `docs/walk-forward-stability-result.md`
- `docs/feature-drift-diagnostic-result.md`
- `notebooks/05d_market_structure_analysis.ipynb`
- `notebooks/05e_confirmed_odds_profiling.ipynb`
- `notebooks/06b_feature_availability_analysis.ipynb`
- `notebooks/06c_dns_policy_validation.ipynb`
- `sql/analysis/`
## 2026-08-12 — API4 2022·2023 Raw→Staging→Semantic v2 확장 완료

- 2022 대표 batch 18,355행·1,679경주와 2023 대표 batch 19,284행·1,786경주를 수집했다.
- 두 연도 모두 월 공백, 페이지 누락·중복, Raw SHA256·크기 불일치, 업무키 중복이 0건이다.
- Raw audit 통과 후 Staging에 37,639행을 적재했고 `semantic.api4_runner_event_v2`도 같은 수만큼 확장됐다.
- 89개 원천 필드 계약과 기존 경마장별 sectional 변환이 유지됐고 실제 API 키 노출은 0건이다.
- 기존 Snapshot v1/v2와 모델·평가 산출물은 재생성하지 않았다.
- 상세 결과: `docs/api4-history-extension-2022-2023.md`
- 다음 추천 작업: 기존 계약으로 Snapshot v2 전체기간 재생성 전 월별 left-censoring 및 분할 후보 프로파일링.
## 2026-08-13 — `wgHr` 빈 증감 0kg parsing 반영, Snapshot 확장은 공식 PLC 원천 대기

- Semantic v2에서 숫자 중량 뒤 `()`를 0kg 증감으로 파싱하도록 수정했다.
- 전체 87,025행에서 5,843행이 0으로 변환됐고 중량 자체가 없는 `()` 663행은 NULL을 유지했다.
- Staging/Semantic 행 수, 업무키, 숫자 범위와 sectional source audit은 모두 통과했다.
- 2022·2023 공식 Sales/`winning_payout`이 없어 확정 PLC 타깃·Historical PLC Feature 계약을
  유지한 Snapshot 전체기간 재생성은 수행하지 않았다.
- 상세 결과: `docs/api4-wghr-parsing-and-snapshot-v2-readiness.md`
- 다음 추천 작업: 2022·2023 공식 Sales Raw 수집 가능 범위 확인 후 Raw→Staging→Canonical 확장.
## 2026-08-13 — 2022·2023 Sales 확장 및 Snapshot v2 전체기간 재생성 완료

- 연도별 Sales Raw 24,178행/26페이지를 수집하고 Raw·Staging 감사를 통과했다.
- 기존 정의 그대로 Canonical 8,065경주·87,025 출전행과 8,036개 모델 모집단 경주를 재생성했다.
- `place_feature_snapshot_v2_candidate`는 2022-01-07~2026-07-26, 85,566행·8,036경주·125 Feature로 확장됐다.
- PIT/leakage/구조 감사는 모두 통과했고 117개 MODEL_INPUT 계약을 유지한다.
- 상세 결과: `docs/sales-history-extension-and-snapshot-v2-rebuild.md`
- 다음 추천 작업: official baseline v2 날짜 분할 및 평가 프로토콜 설계.
## 2026-08-13 — Snapshot v2 Feature maturity 및 모델링 시작일 결정

- 2022-01~2023-07의 117개 MODEL_INPUT 결측과 companion count 기반 Historical family 가용성을 월별 프로파일링했다.
- 2022년 초의 강한 left-censoring이 중·후반에 크게 완화되고, 2023년 초에는 주요 장기·조건·관계자 이력이 성숙한 것을 확인했다.
- 2022년 전체를 Historical warm-up으로 사용하고 official place baseline v2 모델링 시작일을 2023-01-01로 권고했다.
- 모델 학습·평가·Feature 선택은 수행하지 않았다.
- 상세 결과: `docs/place-feature-maturity-and-modeling-start-v2.md`
## 2026-08-13 — Official place baseline v2 시간순 평가 계약 확정

- 모델 성능을 사용하지 않고 2023-01~2026-07 월별 모집단과 경마장·등록두수·등급·거리 구성을 프로파일링했다.
- Train 2023-01~2024-06, Validation 2024-07~2025-06, post-selection temporal evaluation 2025-07~2026-07을 권고 계약으로 확정했다.
- 장기 안정성 진단은 2023년을 최초 학습기간으로 두고 2024-01부터 31개 월별 expanding fold를 사용한다.
- 2026년은 baseline_v1에서 이미 확인했으므로 새로운 독립 Final Test로 표현하지 않는다.
- 모델 학습·예측·성능평가는 수행하지 않았다.
- 상세 결과: `docs/place-baseline-v2-temporal-evaluation-design.md`

## 2026-08-13 — Official place baseline v2 속도·sectional 계약 감사 완료

- race-time recent3/5 median 2개를 검토 대상이 아닌 `EXCLUDE_LOGICAL`로 확정했다.
- Snapshot 속도·sectional 16개를 전수 추적했고, 모델 입력 14개 중 race-time count 2개와
  S1F/G3F/G1F median·count 12개를 `KEEP_AS_IS`로 판정했다.
- 부산경남 G3F/G1F 누적값↔직접 구간값 35,695건은 각각 불일치 0건·최대 오차 0초였고,
  서울 계산식 불일치 및 Snapshot PIT 위반도 0건이었다.
- 모델 입력 수는 117개로 유지하고 `REVIEW_REQUIRED`는 0개가 됐다.
- 상세 결과: `docs/speed-sectional-feature-audit-v2.md`
- 다음 추천 작업: 확정된 117개 입력으로 Train-only 전처리와 제한된 Logistic baseline 실행 계약을 구현한다.

## 2026-08-17 — Official place Logistic baseline v2 Validation·봉인 완료

- 확정된 117개 입력으로 Train 2,675경주·28,392행, Validation 1,759경주·18,615행을 사용했다.
- 무정보 기준선, raw Logistic, Train temporal OOF sigmoid만 비교했다.
- sigmoid가 macro Log Loss는 0.000351 개선했지만 macro Brier는 0.000047 악화해 raw Logistic을 선택했다.
- 선택 절차를 봉인한 뒤 Train+Validation 47,007행에 동일 raw Logistic을 재적합했다.
- 개발 로더는 2025-07-01 미만으로 제한했고 post-selection prediction·손실 평가는 생성하지 않았다.
- 사전 건수 확인 SQL에서 post-selection 집계 양성률이 노출됐으나 선택 코드에는 사용되지 않은
  범위 이탈을 실행 계약 limitation으로 기록했다.
- 상세 결과: `docs/official-place-logistic-baseline-v2-validation.md`
- 다음 추천 작업: 봉인된 artifact와 contract를 변경하지 않고 post-selection temporal evaluation을 1회 실행한다.

## 2026-08-18 — Baseline v2 후속 개선 실험·평가기간 보존 정책 확정

- 2025-07~2026-07의 즉시 평가를 보류하고 최종 후보들의 공통 post-selection temporal evaluation으로 보존했다.
- 같은 117개를 사용하는 Histogram Gradient Boosting으로 모델 복잡도 효과를 먼저 분리하도록 설계했다.
- Feature 개선은 상대 경주시간과 pace-shape bundle 두 개를 우선 후보로 제한했다.
- 모델·Feature 선택은 2023-01~2024-06의 4개 quarterly expanding fold에서 수행하고 기존 Validation은
  봉인된 소수 후보의 최종 개발 비교에만 사용한다.
- 새 모델·prediction·Feature·Snapshot은 생성하지 않았고 평가기간도 추가 조회하지 않았다.
- 상세 결과: `docs/post-baseline-v2-improvement-experiment-design.md`
- 다음 추천 작업: 2024-07 이후 접근을 차단한 inner temporal CV harness와 실험 registry만 구현한다.
