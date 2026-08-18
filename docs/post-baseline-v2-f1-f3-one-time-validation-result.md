# Post-baseline v2 F1+F3 one-time Validation 결과

## 결론

봉인 계약에 따른 유일한 Validation 접근을 실행했고 접근 횟수는 0에서 1로 변경됐다. F1+F3
sigmoid가 raw보다 전체 Macro Log Loss와 Macro Brier를 모두 개선해 probability procedure로
선택됐다. 선택된 후보는 B0보다 두 전체 Macro 지표를 모두 개선했고 12/12개월에서 각각 반복돼
사전 규칙상 `PROMOTE`다.

여기서 PROMOTE는 “F1+F3를 포함한 133개 Feature representation의 개선 효과가 development
temporal CV뿐 아니라 별도 Validation 기간에서도 재현됐다”는 의미로 한정한다. 프로젝트 최종 모델로
확정하거나 Train+Validation 재적합을 수행한 것은 아니다.

## 실행 전 계약 검증

- 계약 JSON SHA256:
  `3096508623ba4ecff034caac347107161b8c3f1e30b7b46f901511256e02e1b3`
- Feature: 기존 117 + F1 6 + F3 10 = 133개
- Feature hash:
  `18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182`
- 이름·순서, Registry·구현, PIT·결측, 전처리, Logistic, OOF calibration, 판정 규칙: 일치
- Validation 접근 횟수: 0
- 봉인 baseline run contract/refit artifact와 개발 결과 보호 hash: 일치

모든 preflight가 통과한 뒤 접근 ledger를 먼저 1로 기록하고 데이터를 읽었다.

## 표본과 전체 지표

- Train: 2023-01-06~2024-06-30, 28,392행·2,675경주
- Validation: 2024-07-05~2025-06-29, 18,615행·1,759경주
- Validation 양성률: 28.3427%

| 후보 | Macro LL | Macro Brier | Micro LL | Micro Brier | Cal. intercept | Cal. slope |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 0.540603 | 0.180464 | 0.538189 | 0.179429 | -0.0648 | 0.8929 |
| F1+F3 raw | 0.534210 | 0.177977 | 0.531968 | 0.177039 | -0.0932 | 0.8880 |
| F1+F3 sigmoid | **0.533529** | **0.177825** | **0.531177** | **0.176836** | 0.0310 | 1.0151 |

Sigmoid는 raw 대비 Macro LL -0.000680, Macro Brier -0.000152로 두 지표를 모두 개선했다.
따라서 사전 규칙대로 sigmoid를 선택했다.

선택된 sigmoid의 B0 대비 차이는 다음과 같다.

| 지표 | 절대 차이(후보-B0) | 상대 감소율 |
|---|---:|---:|
| Macro Log Loss | -0.007073 | 1.308% |
| Macro Brier | -0.002639 | 1.462% |
| Micro Log Loss | -0.007013 | 1.303% |
| Micro Brier | -0.002594 | 1.445% |

## 월별 반복성

| 월 | Δ Macro LL | Δ Macro Brier |
|---|---:|---:|
| 2024-07 | -0.005913 | -0.001996 |
| 2024-08 | -0.005371 | -0.002117 |
| 2024-09 | -0.009522 | -0.003227 |
| 2024-10 | -0.002929 | -0.000811 |
| 2024-11 | -0.006747 | -0.003207 |
| 2024-12 | -0.007269 | -0.002908 |
| 2025-01 | -0.009262 | -0.003618 |
| 2025-02 | -0.005738 | -0.001565 |
| 2025-03 | -0.006773 | -0.002620 |
| 2025-04 | -0.010381 | -0.004383 |
| 2025-05 | -0.006646 | -0.002536 |
| 2025-06 | -0.008498 | -0.002479 |

Macro Log Loss와 Macro Brier 모두 12/12개월 개선했다. 사전 최소 요건은 각각 6개월이었다.

## 세그먼트 보조 진단

- 경마장: 2/2 모두 두 Macro 지표 개선
- 등급: 10개 중 9개 개선
- 등록두수: 9개 중 7개 개선
- 거리: 10개 중 8개 개선

악화 세그먼트는 주로 표본이 매우 작은 조건이었다. 2,200m는 1경주·8행, 2,300m는 2경주·22행,
13두는 5경주·64행, 14두는 9경주·123행이었다. 이 결과는 진단용이며 Feature나 설정 변경에
사용하지 않는다.

## Development와의 방향 비교

Development에서 F1+F3는 B0 대비 Macro LL -0.007853, Macro Brier -0.002733이었다.
Validation에서도 -0.007073/-0.002639로 두 지표의 방향과 대략적인 크기가 유지됐다. 따라서
development에서 관찰한 개선 방향이 별도 Validation에서도 재현됐다.

## Leakage·보호 감사

- Train/Validation 시간 순서 위반: 0
- OOF fold 시간 순서 위반: 0
- Historical PIT 위반: 0
- 업무키 중복: 0
- Validation 전처리 fit 사용: 없음
- Logistic 및 OOF 수렴 경고: 0
- 2025-07-01 이후 로드 행: 0
- Train+Validation 재적합: 수행하지 않음
- Post-selection temporal evaluation: 수행하지 않음
- 봉인 baseline run contract/refit artifact: 변경 없음

## 접근 기록과 산출물

`data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/`에 다음을 저장했다.

- `validation_access.json`: 접근 1회, 완료, 재접근 금지
- `result.json`
- `overall_metrics.csv`
- `monthly_metrics.csv`
- `monthly_selected_vs_b0.csv`
- `segment_metrics.csv`
- `calibration_table.csv`
- `train_oof_folds.csv`

다음 단계는 결과를 변경하지 않고 133개+sigmoid 절차를 후속 후보로 봉인할지 결정하는 것이다.
이번 단계에서는 재적합이나 2025-07 이후 평가를 수행하지 않는다.
