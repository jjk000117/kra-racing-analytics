# Official place baseline v2 시간순 평가 설계

## 결론

Official place baseline v2는 다음 날짜 역할을 사용한다.

- Historical warm-up: **2022-01-01 ~ 2022-12-31**
- Train: **2023-01-01 ~ 2024-06-30**
- Validation: **2024-07-01 ~ 2025-06-30**
- Post-selection temporal evaluation: **2025-07-01 ~ 2026-07-26**
- Expanding walk-forward: 2023년 전체를 최초 학습기간으로 사용하고 **2024-01부터 월별 평가**, 분기 단위는 보조 rollup

이 계약은 모델 성능을 보지 않고 기간 길이, 표본 규모, 12개월 계절 커버리지와 이후 평가기간 길이만으로 선택했다. 2026년은 baseline_v1 과정에서 이미 확인했으므로 새로운 독립 Final Test 또는 완전히 unseen holdout이라고 표현하지 않는다.

## 분석 범위와 모집단

- 원천: `mart.place_feature_snapshot_v2_candidate`
- 모델링 가능 기간: 2023-01-01 ~ 2026-07-26
- 분석 Grain: 월별 valid-start 출전마 행과 distinct 경주
- 총 43개월, 6,357경주, 67,435행, PLC 양성 19,067행
- 월별 108~190경주, 1,230~2,013행
- PLC 양성률 25.63~30.51%; 모집단 기술통계로만 사용
- 모든 월에 서울과 부산경남이 모두 존재
- 월별 서울 경주 비중 49.68~68.18%, 부산경남 31.82~50.32%
- 등록두수 월별 중앙값 10~12두, P25 9~12두, P75 11~12두

주요 등급은 국6등급 28.50%, 국5등급 25.69%, 혼4등급 13.07%, 국4등급 11.39%다. 주요 거리는 1200m 29.81%, 1400m 22.27%, 1300m 16.31%, 1800m 12.82%, 1600m 9.96%다. 월별 상세 구성은 별도 CSV에 보존한다.

## 날짜 분할 후보 비교

| 후보 | Train | Validation | Post-selection temporal evaluation | 장점 | 단점 |
|---|---|---|---|---|---|
| A 기준안 | 2023-01~2024-12, 24개월, 3,549경주/37,514행 | 2025-01~06, 6개월, 885경주/9,493행 | 2025-07~2026-07, 13개월, 1,923경주/20,428행 | 긴 Train과 긴 평가기간 | Validation이 1~6월만 포함해 연간 계절 커버리지 불완전 |
| **B 권고안** | **2023-01~2024-06, 18개월, 2,675경주/28,392행** | **2024-07~2025-06, 12개월, 1,759경주/18,615행** | **2025-07~2026-07, 13개월, 1,923경주/20,428행** | **세 구간 모두 충분한 규모, Train·Validation이 12개 월-of-year 포함, 긴 평가기간 유지** | A보다 Train이 6개월 짧음 |
| C 달력연도 Validation | 2023-01~2024-12, 24개월, 3,549경주/37,514행 | 2025-01~12, 12개월, 1,758경주/18,742행 | 2026-01~07, 7개월, 1,050경주/11,179행 | 긴 Train과 완전한 달력연도 Validation | 평가기간이 7개월뿐이고 계절 커버리지가 불완전하며 2026은 이미 확인된 기간 |

명확한 통계적 최적점은 없다. B는 단순한 반기 경계, 12개월 Validation, 13개월 후속 평가를 동시에 제공해 가장 설명 가능하고 재현하기 쉽다.

## Validation의 역할

Validation은 미리 제한한 baseline 절차 중 하나를 선택하는 데만 사용한다.

허용되는 선택:

- 전처리 세부 방식
- 결측 대체 방식과 필요한 missing indicator
- 범주형 처리 방식과 unknown category 처리
- Logistic Regression 수렴을 위한 solver·반복 횟수 등 제한된 설정
- raw probability와 사전 정의된 calibration 절차 중 선택
- 확정된 117개 MODEL_INPUT 계약의 전처리 적용 방식
- 사전에 문서화한 소수 baseline 후보 비교

허용하지 않는 선택:

- 117개 Feature의 대규모 성능 기반 선택
- 결과를 보며 반복하는 Feature 추가·제거
- 광범위한 hyperparameter search
- Validation 하위 월을 반복 탐색해 유리한 기간만 선택
- post-selection temporal evaluation 결과를 이용한 소급 재선택

Validation은 12개월·1,759경주·18,615행이며 모든 월-of-year를 포함한다. 제한된 설정 선택과 월별 안정성 확인에는 충분한 구조다. 이는 통계적 power 임계값을 새로 주장한 것이 아니라 후보 사이의 상대적 규모와 계절 커버리지 판단이다.

## Post-selection temporal evaluation의 의미

2025-07-01~2026-07-26은 모든 v2 설정을 Validation에서 선택하고 평가 계약을 봉인한 뒤 한 번 사용하는 시간 외 평가 구간이다.

목적:

- 선택된 절차가 이후 13개월에서도 유지되는지 확인
- 시간에 따른 예측 안정성과 calibration drift 확인
- 경마장·등록두수·등급·거리 구성 변화에 대한 진단

이 구간은 v2 절차보다 시간상 뒤에 있지만 완전히 unseen인 데이터는 아니다. 특히 2026년은 baseline_v1 및 후속 진단에서 이미 확인했다. 따라서 결과는 v2의 **post-selection temporal generalization evidence**로 해석하며, 새로운 독립 Final Test 성능이라고 주장하지 않는다.

이 평가 결과를 보고 전처리·Feature·모델·calibration 설정을 변경하면 해당 기간은 개발 데이터가 된다. 변경된 절차는 새 버전으로 관리하고, 이 구간을 같은 버전의 post-selection 평가로 다시 주장하지 않는다.

## Expanding walk-forward 계약

고정 분할과 별도로 장기 시간 안정성을 다음과 같이 진단한다.

1. 2022년은 Snapshot Historical Feature warm-up으로만 사용한다.
2. 최초 모델 학습기간은 2023-01-01~2023-12-31로 고정한다.
3. 첫 평가 fold는 2024-01이다.
4. 이후 매 fold에서 2023-01-01부터 평가월 직전까지의 모든 과거 데이터로 동일한 봉인 절차를 재적합한다.
5. 바로 다음 한 달만 평가한다.
6. 마지막 fold는 2026-07이며 2026-07-26까지의 부분월이라는 사실을 표시한다.
7. 총 31개 월별 fold를 사용한다.

월별 평가 표본은 108~180경주, 1,230~1,952행이며 중앙값은 147경주·1,551행이다. 시간 변화의 발생 시점을 유지하기에 충분한 규모이므로 월별 fold를 권고한다. 분기별 재학습 fold로 바꾸지 않고, 3개월 결과를 합친 분기 rollup을 보조 안정성 요약으로 제공한다. 마지막 2026-Q3는 7월만 포함하므로 완전 분기와 직접 비교하지 않는다.

Walk-forward는 설정 선택이나 반복 최적화에 사용하지 않는다. 다음 지표를 사전 정의해 기록한다.

- Macro Log Loss
- Micro Log Loss
- Macro Brier Score
- Micro Brier Score
- Calibration intercept
- Calibration slope

보조 segment 진단은 경마장, 등록두수, 등급, 거리로 제한한다. 희소 segment는 행·경주 수를 함께 보고하고 성능 순위를 과도하게 해석하지 않는다.

## 전체 평가 프로토콜

1. **Train 적합:** 전처리 통계, 결측 대체값, 범주 사전과 Logistic 절차를 Train에서만 적합한다.
2. **Validation 비교:** 허용된 소수 설정만 2024-07~2025-06에서 비교한다. 평가 구간은 열지 않는다.
3. **절차 선택:** 확정된 117개 입력, 전처리, Logistic 설정과 calibration 여부를 하나로 선택한다. 제외 확정된 race-time median은 다시 선택 대상으로 열지 않는다.
4. **계약 봉인:** 선택 이유, 코드 버전, Feature registry, 날짜 경계, 지표 정의와 random seed를 실행 계약으로 저장한다.
5. **Train+Validation 재적합:** 평가 전에 동일 절차를 2023-01~2025-06에 재적합한다. Calibration이 선택되면 Train+Validation 안에서 과거→미래의 expanding-window OOF 예측으로 calibrator를 새로 적합한다.
6. **Post-selection temporal evaluation:** 2025-07~2026-07을 한 번 평가하고 결과를 이유로 같은 버전의 설정을 변경하지 않는다.
7. **Walk-forward 진단:** 봉인된 절차를 월별 expanding 방식으로 재적합해 장기 안정성을 별도로 기록한다. 이 결과는 모델 선택 근거가 아니다.

평가 시점보다 미래 데이터를 전처리, 범주 사전, 결측 통계, 모델 또는 calibrator 적합에 사용하지 않는다.

## 2026-08-18 후속 개발 정책 변경

즉시 post-selection temporal evaluation을 실행한다는 이전 순서를 보류한다. 2025-07-01~2026-07-26은
Logistic baseline v2, 같은 117개를 사용하는 비선형 후보와 필요한 Feature engineering 후보가
모두 개발기간 안에서 확정·봉인될 때까지 공통 평가기간으로 보존한다.

후속 모델·Feature 선택은 2023-01~2024-06의 inner temporal CV에서 수행하고, 2024-07~2025-06
Validation은 사전 정의한 소수 후보의 최종 개발 비교에만 사용한다. 공통 평가기간은 모든 후보를
동일 시점에 한 번 비교하며 결과를 보고 같은 버전을 수정하지 않는다. 기존 정보 노출 때문에
완전히 unseen인 Final Test라고 표현하지 않는 기존 원칙은 유지한다.

상세 실험 설계: `docs/post-baseline-v2-improvement-experiment-design.md`

## 산출물

- `data/exports/validation/place_baseline_v2_temporal_design/monthly_population.csv`
- `data/exports/validation/place_baseline_v2_temporal_design/monthly_meet_mix.csv`
- `data/exports/validation/place_baseline_v2_temporal_design/monthly_registered_runner_distribution.csv`
- `data/exports/validation/place_baseline_v2_temporal_design/monthly_grade_distance_mix.csv`
- `data/exports/validation/place_baseline_v2_temporal_design/split_candidates.csv`
- `data/exports/validation/place_baseline_v2_temporal_design/walk_forward_period_sizes.csv`
- `data/exports/validation/place_baseline_v2_temporal_design/recommended_timeline.csv`
- `data/exports/validation/place_baseline_v2_temporal_design/summary.json`
- 재현 스크립트: `scripts/design_place_baseline_v2_temporal_evaluation.py`

프로젝트가 명시적으로 저장소 내 포트폴리오 문서와 CSV를 요청했으므로 별도 HTML/MCP 보고서를 만들지 않고 이 Markdown 문서를 주 보고서로 사용한다.
