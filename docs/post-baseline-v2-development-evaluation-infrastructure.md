# Post-baseline v2 development evaluation infrastructure

기준일: 2026-08-18  
상태: 구현·감사 완료, 개선 모델·Feature·prediction 미생성

## 결론

개발 loader는 `2023-01-01 <= race_date < 2024-07-01`만 읽도록 고정했다. 호출자가 날짜를
넣는 인터페이스를 제공하지 않으며, 공통 guard는 2024-07-01 이후를 포함하는 요청을 SQL 실행
전에 거부한다. 실제 데이터는 2,675경주·28,392행이다.

## 고정 quarterly expanding fold

| Fold | 계약상 학습 | 계약상 평가 | 실제 학습 경주/행 | 실제 평가 경주/행 | 변환 열 |
|---|---|---|---:|---:|---:|
| fold_1 | 2023-01~06 | 2023-07~09 | 854 / 9,224 | 427 / 4,458 | 185 |
| fold_2 | 2023-01~09 | 2023-10~12 | 1,281 / 13,682 | 494 / 5,229 | 202 |
| fold_3 | 2023-01~12 | 2024-01~03 | 1,775 / 18,911 | 432 / 4,707 | 232 |
| fold_4 | 2023-01~2024-03 | 2024-04~06 | 2,207 / 23,618 | 468 / 4,774 | 244 |

모든 fold에서 실제 최대 학습일은 실제 최소 평가일보다 앞섰고 경주 ID 교집합은 없었다.
변환 열 수의 증가는 expanding train에서 관측된 One-hot 범주가 늘어난 결과다.

## Train-only preprocessing

각 fold마다 봉인된 v2 Pipeline에서 `ColumnTransformer`만 새로 clone한다. 해당 fold의 학습행으로
`fit_transform`, 평가행에는 `transform`만 호출하며 분류기 `fit`과 prediction은 호출하지 않는다.
단위 테스트는 평가에만 존재하는 범주가 encoder vocabulary에 들어가지 않고, 평가의 극단값이
numeric median에 반영되지 않는 것을 확인한다.

## Experiment registry

로컬 registry는
`data/exports/modeling/post_baseline_v2/development_registry.json`에 저장하며 Git 대상이 아니다.
각 실험은 `experiment_id`, 생성 시각, 상태, 모델·Feature 설정, Feature SHA256, fold별 지표,
Validation 접근 횟수와 접근 사유·시각을 기록한다.

네 fold 지표가 모두 기록되어야 `FROZEN_FOR_VALIDATION`으로 전환할 수 있다. 봉인된 후보의
Validation 접근은 명시적으로 기록하며 후보당 1회가 지나면 추가 기록을 거부한다. 현재 registry는
빈 상태이고 Validation 접근 횟수는 0이다.

## 봉인 산출물 보호

`docs/official-place-baseline-v2-protection.json`에 `run_contract.json`과
`refit_artifact.joblib`의 기대 SHA256을 고정했다. 준비 감사는 파일 존재와 전체 hash 일치를
확인하고 불일치 시 즉시 실패한다. 이번 실행 전후 두 hash는 동일했다.

## 실행 및 범위

재실행 명령은 `kra-analytics model prepare-development-evaluation`이다. 결과는 로컬
`data/exports/validation/post_baseline_v2_development_infrastructure/infrastructure_audit.json`에
저장한다. HistGradientBoosting, F1/F2, 분류기 학습, prediction, 기존 Validation,
2025-07 이후 평가와 baseline v2 재적합은 수행하지 않았다.

다음 단계는 M1 설정을 실행 전에 1~2개로 봉인한 뒤 같은 117개 입력으로 네 development fold에서만
HistGradientBoosting을 실행하는 것이다.
