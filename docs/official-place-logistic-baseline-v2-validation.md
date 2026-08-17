# Official place Logistic baseline v2 Validation 및 실행 계약 봉인

기준일: 2026-08-17  
모델 버전: `official_place_logistic_baseline_v2`  
상태: Validation 선택·Train+Validation 재적합 완료, post-selection temporal evaluation 미실행

## 결론

확정된 117개 입력과 시간 분할로 Logistic Regression을 학습했다. Validation에서 무정보
기준선, raw Logistic, Train temporal OOF로 적합한 sigmoid만 비교했다. sigmoid는 macro Log
Loss를 0.000351 낮췄지만 macro Brier를 0.000047 높였으므로 두 핵심 macro 지표를 함께
개선하지 못했다. 작은 차이에 복잡도를 추가하지 않는 사전 선택 규칙에 따라 **raw Logistic**을
공식 절차로 봉인했다.

2025-07-01 이후 데이터는 모델 개발 로더의 SQL 상한에서 차단했다. 해당 기간의 prediction,
손실·calibration 평가와 walk-forward는 수행하지 않았고 선택 코드에도 전달하지 않았다. 다만
실행 전 분할 건수 확인용 진단 SQL이 이 구간의 경주·행 수와 집계 PLC 양성률을 함께 출력한
범위 이탈이 있었다. 따라서 이번 실행은 계산 경로상 격리는 지켰지만 분석자 관점의 target 접근이
완전히 0이었다고 주장하지 않는다.

## 데이터와 입력 계약

| 구간 | 경주 | 행 | 역할 |
|---|---:|---:|---|
| Historical warm-up, 2022년 | 모델 적합 제외 | 모델 적합 제외 | Snapshot Historical 계산에만 사용 |
| Train, 2023-01~2024-06 | 2,675 | 28,392 | 전처리·Logistic·OOF calibrator 적합 |
| Validation, 2024-07~2025-06 | 1,759 | 18,615 | 세 후보 비교와 절차 선택 |
| Train+Validation 재적합 | 4,434 | 47,007 | 봉인된 raw Logistic 최종 artifact 적합 |

- Snapshot: `mart.place_feature_snapshot_v2_candidate`
- Target: 공식 PLC `place_hit`
- 입력: inventory의 `MODEL_INPUT` 117개
- Feature 목록 SHA256: run contract의 `model_input_sha256`에 저장
- `EXCLUDE_LOGICAL` 2개 및 `EXCLUDE_STRUCTURAL` 6개 유입: 0개
- 개발 로더 최대 날짜: 2025-06-29
- Grain 중복 및 타깃 NULL/비이진 값: 0건

## 전처리 계약

- 범주형 11개: Train 최빈값 대체 후 `OneHotEncoder(handle_unknown="ignore")`
- 일반 수치형 98개: Train 중앙값 대체 후 `StandardScaler`
- 유효 관측 count 8개: NULL은 원천 계약상 과거 유효 관측 0건이므로 0으로 변환 후 scaling
- 추가 missing indicator: 0개

count 8개는 `horse_recent3/5`의 race-time, S1F, G3F, G1F count다. 이들은 companion이 없는
실질 결측 Feature가 아니라 다른 Historical median의 표본 수 companion이다. 중앙값 대체는
관측 이력을 허위로 만들기 때문에 결정론적 0 처리가 더 직접적인 계약이다. 그 밖의 결측
Historical 값은 이미 count companion을 함께 입력하므로 indicator를 중복 추가하지 않았다.

후보 선택용 pipeline은 Train에서만 fit했고 Validation에는 transform만 적용했다. OOF 각
pipeline도 해당 fold의 과거 training portion에서만 fit했다. Train+Validation 전처리는 절차
봉인 후 향후 평가용 artifact를 만들기 위해 별도로 재적합했다.

## Logistic 설정

단일 설정만 사용했다.

- penalty: L2
- `C=1.0`
- solver: `lbfgs`
- `max_iter=2000`
- class weight: 없음
- random seed: `20260817`
- 수렴 경고: 후보 적합, OOF 5개 fold, 최종 재적합 모두 0건

C·penalty·solver grid search, 자동 Feature selection과 다른 모델 family 비교는 수행하지 않았다.

## Train temporal OOF calibration

첫 3개월로 학습한 뒤 다음 3개월을 예측하고, 학습창을 3개월씩 확장했다. 모든 fold는
`max(training date) < min(prediction date)`를 만족했다.

| Fold | 학습기간 | 예측기간 | 학습 경주/행 | 예측 경주/행 |
|---:|---|---|---:|---:|
| 1 | 2023-01-06~03-31 | 2023-04-01~06-30 | 413 / 4,643 | 441 / 4,581 |
| 2 | 2023-01-06~06-30 | 2023-07-01~09-24 | 854 / 9,224 | 427 / 4,458 |
| 3 | 2023-01-06~09-24 | 2023-10-06~12-31 | 1,281 / 13,682 | 494 / 5,229 |
| 4 | 2023-01-06~12-31 | 2024-01-05~03-31 | 1,775 / 18,911 | 432 / 4,707 |
| 5 | 2023-01-06~2024-03-31 | 2024-04-05~06-30 | 2,207 / 23,618 | 468 / 4,774 |

OOF 예측에만 sigmoid를 적합했으며 Validation target은 calibrator fit에 사용하지 않았다.

## Validation 결과

Train 양성률로 만든 무정보 기준확률은 `0.282650`이었다.

| 후보 | Macro Log Loss | Macro Brier | Micro Log Loss | Micro Brier | Cal. intercept | Cal. slope |
|---|---:|---:|---:|---:|---:|---:|
| 무정보 기준선 | 0.599945 | 0.204862 | 0.596163 | 0.203097 | -0.927524 | 정의 불가 |
| Logistic raw | 0.540603 | **0.180464** | 0.538189 | 0.179429 | -0.064820 | 0.892884 |
| Logistic+sigmoid | **0.540252** | 0.180511 | **0.537719** | **0.179424** | 0.086514 | 1.056727 |

두 Logistic 후보 모두 무정보 기준선을 충분히 개선해 117개 입력에 예측 정보가 있음을 확인했다.
sigmoid의 변화는 macro Log Loss -0.000351, macro Brier +0.000047로 방향이 엇갈렸다.
Calibration slope는 sigmoid가 1에 더 가까웠지만 intercept 절대값은 raw가 더 작았다. 따라서
calibration이 명확한 종합 개선을 제공했다고 보지 않았다.

## 월별·세그먼트 진단

Raw Logistic 월별 macro Log Loss는 0.515067~0.563449, 월별 표준편차는 0.012423이었다.
가장 낮은 달은 2025-03, 가장 높은 달은 2024-08이었다. 2025-06은 0.554753이었지만 12개월
전체에서 단조로운 악화 패턴은 없었다. sigmoid는 12개월 중 Log Loss 6개월, Brier 5개월만
raw보다 낮아 월별로도 일관된 개선은 아니었다.

Raw 기준 주요 세그먼트 차이:

- 부산경남 macro Log Loss 0.528670, 서울 0.548872
- 표본이 충분한 등록두수에서는 12두 0.507445, 9두 0.572022
- 주요 등급에서는 국6등급 0.524428, 1등급 0.557251
- 표본이 20경주 이상인 거리에서는 1300m 0.532195, 1000m 0.585553

이는 오류 특성 진단이며 Feature 또는 모델 설정 변경 근거로 사용하지 않았다. 13두 이상,
2200m·2300m와 일부 OPEN 등급은 경주 수가 적으므로 성능 순위를 일반화하지 않는다.

## 봉인 및 재적합

- 선택 절차: `logistic_raw`
- 상태: `SEALED_BEFORE_POST_SELECTION_TEMPORAL_EVALUATION`
- Train+Validation 재적합: 수행
- 재적합 기간: 2023-01-01~2025-06-30
- 재적합 행/경주: 47,007 / 4,434
- calibration 재적합: raw가 선택되어 불필요, 수행하지 않음
- post-selection 예측 생성: 없음
- post-selection 손실·calibration 평가: 없음
- 제한사항: 사전 건수 확인 SQL에서 post-selection 집계 양성률이 노출됐으나 모델·calibrator·선택 규칙 입력에는 사용되지 않음
- contract payload SHA256:
  `1abcaf927dedc50c4c2f87ca54b9b2471d058cbfdee7655f72626021ae87d85a`

범위 이탈 기록 전 동일 실행을 한 번 재현해 run contract 파일 hash와 payload hash가 모두
동일함을 확인했다. 최종 계약은 이 제한사항 필드를 포함해 다시 생성하고 payload hash를 검증했다.
기존 `place_logistic_baseline_v1`의 contract, pipeline, Final Test 결과 hash도 작업 전후 동일했다.

## 산출물

로컬 모델 산출물 경로:

`data/exports/modeling/official_place_logistic_baseline_v2/`

- `run_contract.json`, `run_contract.sha256`
- `model_inputs.txt`
- `refit_artifact.joblib`
- `validation_result.json`
- `train_oof_folds.csv`
- `validation_calibration_table.csv`
- `validation_monthly_metrics.csv`
- `validation_segment_metrics.csv`

이 경로는 대용량·실행 산출물 정책에 따라 Git에서 제외된다. 구현 코드는
`src/kra_analytics/modeling_v2.py`, 실행 명령은 `model official-v2-validation`이다.
