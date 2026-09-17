# PLC 탐색적 배팅·경제성 백테스트 결과

## 결론

provisional 137개 Feature의 Development temporal OOF sigmoid 확률을 기존 집계와 완전히
동일하게 복구했다. 1,821개 경주에서 매 경주 확률 1위 한 마리에 1단위를 걸었다고 가정하면
적중률은 `61.3948%`였지만 공식 확정배당 기준 순손익은 `-240.4`단위, ROI는 `-13.2015%`였다.

고정한 여덟 confidence threshold에서도 ROI는 모두 음수였다. 확률 기준을 높이면 적중률은
대체로 올라갔지만 선택된 말의 배당이 낮아지고 베팅 수가 줄어 손실 구조를 제거하지 못했다.
이는 **historical final-payout diagnostic**이며 decision-time odds가 없는 상태의 실전 수익률이나
deployable strategy 검증이 아니다.

## OOF·모집단·정산 감사

- Feature: 137개, hash
  `7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e`
- 네 Development outer fold의 raw/calibrated 지표 및 calibrator 계수 최대 재현 오차: `0.0`
  (허용 `1e-12`)
- 분석 범위: 2023-07-01~2024-06-30, 19,168행·1,821경주
- in-sample prediction: 0행
- `canonical.runner_result.place_odds` 연결: 19,168/19,168, `100%`
- 공식 PLC 양성 및 `canonical.winning_payout.confirmed_odds` 연결: 5,462/5,462, `100%`
- target/payout 불일치, 제외 행·경주: 0
- 출전마 최종배당과 공식 적중 정산배당이 다른 행: 3개 경주의 6행. 실제 손익은 공식
  `confirmed_odds`를 우선했다.

PLC 적중마 수는 2마리인 경주 4개, 3마리 1,814개, 4마리 3개였다. 연승식은 원칙적으로
7두 이하에서 1·2위가 적중하지만 등록두수와 최종 유효 출전두수 차이 및 동착이 존재할 수 있다.
따라서 기존 계약대로 `ord`나 등록두수로 재구성하지 않고 공식 적중 조합만 사용했다.

## 배당·손익 정의

- stake: 선택 1건당 1단위
- 적중 gross return: 공식 `confirmed_odds × 1단위` (원금 포함)
- 미적중 gross return: 0
- net profit: `gross return - stake`
- ROI: `총 net profit / 총 stake`

KRA 경마시행 안내에 따르면 배당률은 발매 마감과 함께 확정되고 결과 확정 뒤 환급된다. 따라서
확정배당은 예측시점에 이용할 수 없다. KRA 용어상 배당률 1.0은 베팅액과 환급액이 같은 경우이므로
본 계산은 소수배당을 원금 포함 총환급 배수로 처리한다.

## Top1 fixed baseline

| 항목 | 결과 |
|---|---:|
| 경주·베팅 수 | 1,821 |
| 적중 | 1,118 |
| 적중률 | 61.3948% |
| 총 stake | 1,821.0 |
| 총환급 | 1,580.6 |
| 순손익 | -240.4 |
| ROI | -13.2015% |
| 적중 평균 / 중앙 배당 | 1.414 / 1.3 |
| 최고 적중배당 | 4.7 |
| 최대낙폭 | 243.5단위 |
| 최장 연속손실 | 6회 |

누적손익은 짧은 반등은 있으나 전체 기간에 걸쳐 하락했다. 100-bet rolling ROI는 중앙
`-13.3%`, 최저 `-34.8%`, 최고 `+5.0%`였다.

## 고정 confidence threshold 민감도

| 최소 Top1 P | 베팅 | 베팅률 | 적중률 | ROI | 순손익 |
|---:|---:|---:|---:|---:|---:|
| 0.35 | 1,780 | 97.75% | 62.02% | -12.66% | -225.4 |
| 0.40 | 1,720 | 94.45% | 62.62% | -12.45% | -214.2 |
| 0.45 | 1,553 | 85.28% | 64.26% | -10.79% | -167.5 |
| 0.50 | 1,265 | 69.47% | 65.22% | -12.17% | -153.9 |
| 0.55 | 880 | 48.33% | 68.98% | -10.43% | -91.8 |
| 0.60 | 530 | 29.10% | 73.21% | -8.85% | -46.9 |
| 0.65 | 287 | 15.76% | 73.52% | -12.44% | -35.7 |
| 0.70 | 102 | 5.60% | 77.45% | -8.04% | -8.2 |

모든 값은 사전 고정 grid의 기술통계다. 가장 덜 음수인 행도 표본이 작은 사후 결과일 뿐 최종
threshold로 선택하지 않는다.

## 확률·시장 구조

- 확률 bucket이 높아질수록 관측 PLC 적중률은 전반적으로 증가했다.
- 0.1 이하 bucket의 관측 적중률은 5.54%, 0.6~0.7은 71.37%, 0.7~0.8은 76.04%였다.
- 반대로 최종 연승배당 중앙값은 11.6에서 1.1까지 낮아졌다. 높은 모델 확률은 낮은 최종 시장배당과
  강하게 연결됐다.
- Spearman(`model P`, final place odds) = `-0.7771`.
- 경주 내 model rank와 낮은 배당 rank Spearman = `0.7590`.
- Top1 선택의 65.29%는 최종배당 1.5 이하, 88.91%는 2.0 이하였다.

따라서 모델이 시장과 전혀 다른 말을 고르는 구조라고 말할 근거는 없다. 다만 final odds는
prediction cutoff 뒤의 값이므로 동시점 독립정보 비교도 아니다. `1/odds`는 pari-mutuel takeout과
연승식 복수 적중 구조를 반영하지 않으므로 시장확률로 변환하지 않았다.

## Retrospective EV와 고배당 의존성

전 출전마의 `sigmoid_probability × final_place_odds - 1`을 사후 EV proxy로 계산했다. 이 값이
양수인 모든 구간에서도 실제 단위베팅 ROI는 음수(`-21.06%`~-`31.91%`)였다. final odds를
미리 알았다는 가정 아래에서도 단순 곱은 실행 가능한 edge 규칙이 아니며, threshold를 선택하지 않았다.

Top1 최고 적중배당 1건을 환급 0으로 두면 ROI는 `-13.46%`, 최고 5건을 0으로 두면
`-14.34%`였다. 원래부터 ROI가 음수이고 최고배당도 4.7에 그쳐, 결과가 한두 고배당 적중 때문에
양수로 보이는 구조는 아니었다.

## 월별 안정성

12개월 모두 ROI가 음수였다. 가장 덜 음수인 2024-01은 `-7.71%`, 가장 낮은 2023-10은
`-26.05%`였다. 적중률은 월별 56.05%~65.79%였지만 낮은 배당 때문에 어느 달도 손익분기점을
넘지 못했다.

## 말할 수 있는 것과 없는 것

확인된 사실:

- 동일한 temporal OOF 확률을 정확히 복구했고 공식 target·정산배당이 100% 연결됐다.
- 이 Development 기간의 고정 Top1과 사전 고정 confidence grid는 모두 음수 ROI였다.
- 높은 모델 확률은 높은 적중률과 낮은 final payout 양쪽에 연결됐고 모델 순위는 final market
  인기 순위와 강하게 겹쳤다.

말할 수 없는 것:

- 실제 구매시점 odds, odds drift, scratches/기수변경, wager placement 가능성을 반영한 결과가 아니다.
- 실전 수익전략·deployable ROI·fresh generalization을 검증하지 않았다.
- final payout EV 구간이나 confidence threshold를 공식 전략으로 선택하지 않았다.
- 이 결과만으로 모델에 독립적인 market edge가 없다고 단정할 수 없다. 이를 검증하려면 먼저
  timestamped decision-time odds가 필요하다.

## 산출물과 보호

- 코드: `src/kra_analytics/exploratory_betting_backtest.py`
- 단위 테스트: `tests/test_exploratory_betting_backtest.py`
- 노트북: `notebooks/12_plc_exploratory_betting_backtest.ipynb`
- 노트북 생성기: `scripts/build_plc_exploratory_betting_notebook.py`
- git-ignored machine artifacts:
  `data/exports/modeling/plc_exploratory_betting_backtest_v1/`
- Validation 접근 0, 2024-07-01 이후 로드 0, post-2025-07 접근 0
- source/experiment DB 및 봉인 계약·기존 결과 hash는 실행 전후 동일
- DB write 및 다른 worktree 변경 없음

## Sources

- 로컬 데이터 계약: [`place-model-data-contract.md`](place-model-data-contract.md)
- 공식 정산 Canonical: [`winning-payout-canonical-build.md`](winning-payout-canonical-build.md)
- KRA 경마시행 안내: <https://race.kra.co.kr/raceguide/RaceProcessGetService.do>
- KRA 경마용어: <https://race.kra.co.kr/raceguide/RaceWordSearchService.do?pageIndex=66>
