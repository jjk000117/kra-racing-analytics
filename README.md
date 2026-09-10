# KRA Racing Analytics

한국마사회(KRA) 공식 OpenAPI의 과거 경주·매출·확정배당 데이터를 수집하고, 예측 시점 기준의 분석 데이터와 연승(PLC) 확률모델을 구축하는 Python + SQL 프로젝트입니다.

이 프로젝트는 단순히 모델 점수를 높이는 것보다 다음을 우선합니다.

- 원천 응답부터 모델 입력까지 추적 가능한 데이터 계층
- 상태코드와 업무 Grain이 명확한 분석 데이터
- 현재 경주 결과가 과거 이력에 섞이지 않는 Point-in-Time(PIT) Feature
- 시간 순서를 보존한 개발·검증 절차
- 성공뿐 아니라 실패한 실험과 중단 근거까지 남기는 재현성

현재는 **2022~2026 데이터 계층과 125개 Feature Snapshot을 구축하고, L133에 T1 4개와 R1 7개를 더한 LR1 144개 Logistic 후보까지 검증한 상태**입니다. LR1은 Development와 기존 노출 Validation reproduction에서 race-macro Log Loss와 Brier를 모두 작게 개선했습니다. 이는 fresh final test나 운영모델 확정을 뜻하지 않으며 2025-07 이후 기간은 계속 보호합니다.

## 프로젝트 범위

```text
KRA OpenAPI
  → Immutable Raw + Manifest
  → SQL Staging
  → Canonical / Semantic
  → Star Schema / Analytical Mart
  → PIT Feature Snapshot
  → 시간 기반 Development CV
  → 별도 Validation
```

- Python: API 수집, 실행 제어, 데이터·모델 감사
- SQL/DuckDB: 원문 보존, 업무 규칙, Canonical, Star Schema, Feature 집계
- scikit-learn: Logistic Regression, sigmoid calibration, 제한적 비교 실험
- Pytest·Ruff·mypy: 계약과 구현 검증

데이터베이스 기본 위치는 `data/warehouse/kra.duckdb`입니다. Raw 데이터와 모델 산출물은 저장소에 직접 포함하지 않습니다.

## 현재 데이터 규모

전체기간은 2022-01-07~2026-07-26입니다.

| 계층·데이터 | 행 또는 경주 수 |
|---|---:|
| Canonical 경주 | 8,065경주 |
| Canonical 출전마 결과 | 87,025행 |
| Canonical 경주×승식 매출 | 56,252행 |
| Canonical 공식 적중배당 | 88,545행 |
| 7개 승식 완전 모델 모집단 | 8,036경주 |
| Place Feature Snapshot v2 | 85,566행 |
| Snapshot Feature | 125개 |
| Official baseline v2 모델 입력 | 117개 |

2022년은 Historical warm-up으로 사용하고 공정한 모델링 시작일은 2023-01-01로 고정했습니다.

## 데이터 안전성과 품질 계약

### Raw와 lineage

- API 응답은 수정하지 않는 immutable Raw로 보존합니다.
- `request_id`, `batch_id`, 요청 조건, 수집시각, Raw 경로, 파일 크기와 SHA256을 Manifest에 기록합니다.
- ServiceKey 원문은 URL, 로그, 예외, Raw와 Manifest에 저장하지 않습니다.
- 이전 실패 batch도 증거 기록으로 보존하며 성공 batch로 덮어쓰지 않습니다.

### 업무 상태와 모집단

- 정상 완주, DNS, 주행중지, 실격, 취소와 비표준 결과를 서로 구분합니다.
- `ord`로 공식 PLC 적중 여부를 대체하지 않습니다.
- `place_hit`은 공식 매출·확정배당 원천의 연승 적중마로만 생성합니다.
- Canonical 전체를 보존하고 모델·시장 Mart에서 명시적인 적격 조건을 적용합니다.

### Point-in-Time

Historical Feature는 항상 다음 조건을 만족합니다.

```text
historical.race_date < feature_as_of
```

현재 경주의 착순, 적중 여부, 배당, 경주기록, sectional과 착차는 모델 입력에서 제외합니다. 실시간 배당은 baseline Feature가 아니라 향후 betting-stage 정보로 분리합니다.

## Feature Snapshot v2

Snapshot Grain은 `race_id + horse_id`이며 125개 Feature를 보존합니다. 이 중 구조적으로 복원 가능한 항목 등을 제외한 117개가 official baseline v2 입력입니다.

주요 Feature family는 다음과 같습니다.

- 현재 경주 조건: 경마장, 거리, 등급, 등록두수, 게이트, 부담중량, rating
- 말 이력: 전체, recent3/5/10, 동일거리, 동일경마장
- 관계자 이력: 기수, 조교사, 마주
- 조합 이력: 말×기수, 말×조교사
- Historical 기록: race time, S1F, G3F, G1F, 마체중
- 현재 field-relative 정보와 이력 가용성·count

거리와 경마장을 섞은 절대 race-time recent median 2개는 논리적 이유로 모델 입력에서 제외했습니다. 고정 길이 sectional은 서울·부산경남 원천을 공통 물리 구간으로 정규화한 Historical Feature만 사용합니다.

## 모델 개발과 시간 검증

### 날짜 역할

| 역할 | 기간 |
|---|---|
| Historical warm-up | 2022-01~2022-12 |
| Development | 2023-01~2024-06 |
| 별도 Validation | 2024-07~2025-06 |
| 공통 post-selection temporal evaluation | 2025-07~2026-07 |

Development에서는 네 개의 quarterly expanding temporal fold를 사용합니다. 각 fold는 학습일이 평가일보다 앞서며, 결측 대체·scaling·범주 vocabulary는 해당 fold의 학습 부분에서만 적합합니다.

2025-07 이후 구간은 아직 대표 후보 평가에 사용하지 않았습니다. 기존 정보 노출 이력이 있으므로 완전히 unseen인 Final Test가 아니라, 후보들이 모두 봉인된 뒤 사용하는 공통 post-selection temporal evaluation으로 정의합니다.

### Official baseline v2

첫 기준 절차는 117개 입력을 사용하는 L2 Logistic Regression입니다.

- 수치형: Train median imputation + scaling
- 범주형: Train 최빈값 대체 + OneHotEncoder
- Calibration: Train 내부 expanding temporal OOF 예측으로 sigmoid 적합
- 주요 지표: race-level Macro Log Loss·Brier와 Micro Log Loss·Brier

117개 baseline에서는 sigmoid가 두 Macro 지표를 함께 개선하지 못해 raw Logistic을 선택했습니다.

## Post-baseline Feature 실험

모델 복잡도와 Feature 정보 추가 효과를 분리하기 위해 모든 실험에서 모집단, 시간 fold와 Logistic 설정을 고정했습니다.

| 후보 | 내용 | Development 판정 |
|---|---|---|
| B0 | Logistic + 기존 117 | 기준 |
| F1 | 과거 경주 내 상대 race-time 6개 | KEEP |
| F2 | Historical pace-shape 8개 | DROP |
| F3 | 현재 경주 field-relative 10개 | KEEP |
| F1+F3 | 기존 117 + F1 6 + F3 10 = 133개 | KEEP_COMBINATION |

F1+F3는 Development에서 F3 단독보다 Macro Log Loss와 Macro Brier를 모두 4/4 fold에서 개선해 유일한 Validation 후보로 봉인했습니다.

## L133+sigmoid Validation 결과

133개 Feature 후보는 별도 Validation 2024-07~2025-06의 1,759경주·18,615행에서 평가했습니다.

| 지표 | B0 | L133+sigmoid | 상대 감소 |
|---|---:|---:|---:|
| Macro Log Loss | 0.540603 | **0.533529** | 1.31% |
| Macro Brier | 0.180464 | **0.177825** | 1.46% |
| Micro Log Loss | 0.538189 | **0.531177** | 1.30% |
| Micro Brier | 0.179429 | **0.176836** | 1.45% |

두 Macro 지표 모두 B0보다 12/12개월 개선해 사전 규칙상 `PROMOTE`했습니다. 이 판정은 **F1+F3 Feature representation의 개선이 Development뿐 아니라 별도 Validation에서도 재현됐다**는 의미이며, 프로젝트의 최종 모델 확정을 뜻하지 않습니다.

설명용 진단에서는 다음을 확인했습니다.

- Validation PLC 양성률: 28.34%
- ROC-AUC: 0.7213
- PR-AUC: 0.5085
- 경주 내 예측 1위 말의 PLC 적중률: 59.52%
- Top-3에 최소 한 적중마가 포함된 경주: 91.87%
- 전체 PLC 적중마 Recall@3: 49.36%

모델 선택용 Validation 접근은 1회로 제한했습니다. 이후 누락된 row-level prediction을 동일 봉인 절차로 복원한 설명용 재접근 1회는 `DESCRIPTIVE_DIAGNOSTIC_REACCESS`로 별도 기록했으며 후보·Feature·calibration·threshold 선택에는 사용하지 않았습니다.

## 실패 실험과 중단 결정

| 실험 | 결과 | 결정 |
|---|---|---|
| 117개 입력 HistGradientBoosting | Logistic 대비 안정적 개선 없음 | DROP |
| 133개 입력 H133 | Macro LL/Brier 모두 0/4 fold 개선 | DROP_NONLINEAR |
| 선형 pairwise RA1 | NDCG@3 소폭 개선, 확률 손실 4/4 악화 | DROP_RACE_AWARE |

성능이 좋지 않은 결과도 계약과 함께 보존하고, 결과를 확인한 뒤 Feature 정의나 설정을 소급 변경하지 않았습니다.

## 현재 PLC 연구 상태

Historical Trend T1 4개를 구현하고 데이터 수준 감사를 완료했습니다.

- F1 time-percentile recent5 추세
- S1F recent5 개선 추세
- G3F recent5 개선 추세
- G1F recent5 개선 추세

Development 28,392행·2,675경주에서 가용률은 82.79%였고 PIT, 순서, NULL, 수기 slope 재계산 감사를 통과했습니다. 아직 target 기반 모델 성능은 확인하지 않았습니다.

동일 Logistic·동일 네 development fold에서 `L133`과 `L133 + T1`만 비교한 결과 Macro Log Loss와 Brier가 4개 fold 중 3개에서 함께 개선됐습니다. 평균 상대 개선은 약 0.13~0.15%로 작아, official 후보를 변경하지 않고 T1을 후속 후보로만 유지합니다.

조건 적합성 A1은 LT1 대비 안정적 개선이 없어 `DROP_A1`으로 종료했습니다. 반면 current-field
relative R1 7개를 더한 LR1은 Development 3/4 fold에서 두 primary 손실을 함께 개선했고, 기존 노출
Validation에서도 Macro Log Loss/Brier를 `0.533332/0.177797`에서 `0.532780/0.177586`으로 낮춰
`REPRODUCE_R1` 판정을 받았습니다. 개선 폭은 작고 Recall@3·NDCG@3는 소폭 악화했습니다.

다음 큰 단계는 최종 Feature diagnostics, serving feasibility, odds/market layer 조사 순서입니다.
Feature 진단은 즉시 삭제하기 위한 절차가 아니며, 상관이나 importance만으로 변수를 제거하지 않습니다.

## 주요 문서

- [프로젝트 진행 현황](docs/progress.md)
- [설계 결정 기록](docs/decision_log.md)
- [실험 기록](docs/experiment_log.md)
- [데이터 계층 계약](docs/data-contracts.md)
- [상태코드 정책](docs/status-code-policy.md)
- [Point-in-Time 및 누수 방지](docs/point-in-time-policy.md)
- [2022~2023 Sales 확장과 Snapshot v2 재생성](docs/sales-history-extension-and-snapshot-v2-rebuild.md)
- [Snapshot v2 구축](docs/place-feature-snapshot-v2-build.md)
- [117개 모델 입력 설계](docs/official-place-baseline-v2-model-input-design.md)
- [시간 분할과 평가 설계](docs/place-baseline-v2-temporal-evaluation-design.md)
- [F1/F2/F3 Feature 설계](docs/post-baseline-v2-feature-bundle-design.md)
- [F1/F2/F3 Development 결과](docs/post-baseline-v2-feature-bundle-development-results.md)
- [F1+F3 Validation 결과](docs/post-baseline-v2-f1-f3-one-time-validation-result.md)
- [L133 설명용 성능 진단](docs/l133-sigmoid-validation-descriptive-performance-diagnostic.md)
- [H133 Development 결과](docs/post-baseline-v2-h133-development-result.md)
- [RA1 Development 결과](docs/post-baseline-v2-ra1-development-result.md)
- [Historical Trend T1 구현 감사](docs/post-baseline-v2-historical-trend-feature-implementation-audit.md)
- [Historical Trend T1 development 결과](docs/post-baseline-v2-t1-development-result.md)
- [LR1 Validation reproduction 결과](docs/post-baseline-v2-relative-r1-validation-result.md)

## 개발 환경

Python 3.12와 DuckDB를 사용하며 기존 Anaconda의 `base`와 분리된 전용 환경을 권장합니다.

```powershell
conda create -n kra-racing-analytics python=3.12
conda activate kra-racing-analytics
python -m pip install -e ".[dev]"
```

기본 점검 명령은 다음과 같습니다.

```powershell
python -m kra_analytics doctor
python -m kra_analytics database init
python -m kra_analytics database check
pytest
ruff check .
mypy src
```

## 수집 예시

`KRA_API_KEY`가 프로세스 환경에 설정돼 있어야 합니다. 키는 실행 출력과 저장 산출물에 기록하지 않습니다.

```powershell
python -m kra_analytics collect race-results --year 2024 --year 2025 --year 2026 --meet 1 --meet 3 --all-pages --page-size 1000
python -m kra_analytics collect sales --year 2024 --year 2025 --year 2026 --meet 1 --meet 3 --all-pages --page-size 1000
python -m kra_analytics collect audit <batch_id>
```

수집 범위와 batch는 실행 전에 명시적으로 선택하며, 기존 Raw batch를 수정하거나 덮어쓰지 않습니다.

## 아직 포함하지 않은 범위

- L133+sigmoid의 2025-07 이후 공통 temporal evaluation
- LR1 이후 최종 Feature diagnostics와 serving feasibility audit
- decision-time odds 원천 조사와 market layer
- 확정배당과 예측확률을 결합한 betting strategy
- 공제·배당·수수료를 반영한 경제성 평가
- 최신 증분 수집과 자동 운영
- Power BI·대시보드 또는 서비스 배포

따라서 현재 결과는 **데이터 파이프라인, PIT Feature와 확률예측 품질 검증** 범위로 해석해야 하며 실제 투자수익을 입증한 결과가 아닙니다.
