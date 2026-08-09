# 6D 연승 기준모델 Validation 선택 및 재적합 결과

실행일: 2026-08-09  
모델 버전: `place_logistic_baseline_v1`  
Snapshot 버전: `place_feature_snapshot_v1`  
상태: Validation 선택·봉인 및 Train+Validation 재적합 완료, Final Test 미실행

## 결론

Validation macro Log Loss가 가장 낮은 **Logistic 원본 확률**을 최종 절차로 선택했다. 무정보
기준선보다 명확히 개선됐고 sigmoid 보정은 원본보다 Log Loss와 Brier Score가 모두 소폭 나빠
채택하지 않았다.

선택된 28개 입력, Train 중앙값·범주·표준화 전처리, L2 Logistic Regression `C=1.0`,
`class_weight=None`, `solver=lbfgs` 설정을 봉인했다. 동일 설정을 Train+Validation 23,711행에
재적합했으며 Final Test 예측과 평가는 생성하지 않았다.

## 실행 표본

| 구간 | 행 | 경주 | 용도 |
|---|---:|---:|---|
| Train | 18,888 | 1,788 | 전처리·Logistic·OOF sigmoid 후보 적합 |
| Validation | 4,823 | 439 | 세 후보 선택 |
| Train+Validation | 23,711 | 2,227 | 봉인된 Logistic 원본 절차 재적합 |

Warm-up 행은 학습에 사용하지 않았고 Final Test는 개발 로더의 SQL 경계
`race_date < 2026-01-01` 밖에 두었다.

## Validation 비교

| 후보 | Macro Log Loss | Macro Brier | Micro Log Loss | Micro Brier | Calibration intercept | slope |
|---|---:|---:|---:|---:|---:|---:|
| 무정보 기준선 | 0.589293 | 0.199888 | 0.586380 | 0.198527 | -0.980164 | NULL |
| Logistic 원본 | **0.512157** | **0.169727** | **0.510656** | **0.169097** | 0.109664 | 1.150189 |
| Logistic+sigmoid | 0.513856 | 0.170210 | 0.512279 | 0.169551 | 0.173404 | 1.252360 |

Logistic 원본의 macro Log Loss는 무정보 기준선보다 약 0.07714 낮고 macro Brier는 약 0.03016
낮다. sigmoid는 원본 대비 macro Log Loss가 약 0.00170, macro Brier가 약 0.00048 높아 선택하지
않았다. 임의 종합점수나 유의성 주장은 사용하지 않는다.

무정보 기준선은 모든 예측확률이 같아 calibration intercept와 slope를 동시에 식별할 수 없다.
계약에 따라 intercept는 Validation 관측 양성률의 logit으로, slope는 NULL로 기록했다.

## Train OOF Calibration 후보

| Fold | 과거 학습 행 | 이후 3개월 OOF 행 |
|---|---:|---:|
| 2024-10-04~2024-12-29 → 2025-01-03~2025-03-30 | 4,969 | 4,803 |
| 2024-10-04~2025-03-30 → 2025-04-04~2025-06-29 | 9,772 | 4,690 |
| 2024-10-04~2025-06-29 → 2025-07-04~2025-09-28 | 14,462 | 4,426 |

OOF 확률로 적합한 sigmoid 후보의 계수는 intercept `-0.050823`, slope `0.918438`이었다. 최종
선택은 Logistic 원본이므로 이 calibrator는 최종 절차에 포함하지 않는다. 따라서
Train+Validation 재적합에서 calibration OOF와 새 calibrator는 생성 대상이 아니다.

## 봉인 산출물과 Final Test 상태

로컬 실행 산출물:

- `data/exports/modeling/place_logistic_baseline_v1/run_contract.json`
- `data/exports/modeling/place_logistic_baseline_v1/pipeline.joblib`

`run_contract.json`은 28개 Feature 순서, 전처리 규칙, Logistic 설정, OOF 원칙, Validation 지표,
선택 상태 `SEALED_BEFORE_FINAL_TEST`를 기록한다.

- `final_test_predictions_created = false`
- `final_test_evaluated = false`
- Final Test 예측 파일 없음

Final Test 실행은 이번 단계 범위 밖이며 별도의 명시적 승인 전에는 수행하지 않는다.

## 검증

- 모델링 단위 테스트 6개 통과
- 전체 Pytest 23개 통과
- `ruff check src tests` 통과
- `mypy src/kra_analytics` 통과
- OOF 각 fold에서 `train_end < prediction_start` 확인
- Validation 예측확률의 NULL·무한대·범위 위반 없음
- 29개 Snapshot Feature와 28개 모델 입력 수, 감사 전용 Feature 제외 확인

저장소 전체 Ruff 실행에서 기존 Notebook 2개의 사전 존재 형식 경고 8건이 확인됐지만 이번 모델링
변경 파일과 `src`, `tests` 검사는 통과했다.
