# PLC 탐색적 배팅·경제성 백테스트 계약

## 목적과 해석 경계

현재 provisional 137개 PLC 확률 절차의 Development temporal OOF 예측을 복구해 공식 확정배당과
사후 결합한다. 목표는 손익의 구조와 시장가격 관계를 기술하는 것이며, 배팅전략을 선택하거나
수익성을 입증하는 것이 아니다.

확정배당은 베팅 마감 뒤 확정되는 사후정보다. 따라서 모든 ROI·EV 결과는 **hindsight diagnostic**이며
prediction cutoff에서 실행 가능한 수익률로 표현하지 않는다. KRA 안내상 배당률은 마감 시 확정되고,
결과 확정 뒤 환급된다.

## 모델·기간 계약

- 후보: `UNWEIGHTED_137_SIGMOID`
- Feature: 137개, hash
  `7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e`
- 모델: 기존 L2 Logistic, `class_weight=None`, 동일 Train-only preprocessing
- calibration: 각 outer train 내부의 기존 3개월 expanding temporal OOF sigmoid
- Development 전체: 2023-01-01 이상 2024-07-01 미만, 28,392행·2,675경주
- 분석 예측: 네 outer evaluation을 합친 2023-07-01 이상 2024-07-01 미만,
  예상 19,168행·1,821경주
- 기존 행 단위 OOF artifact가 없으므로 사용자가 2026-09-16 동일 절차의 결정론적 재적합을
  명시적으로 허용했다. 기존 fold 집계와 절대오차 `1e-12` 안에서 일치하지 않으면 중단한다.
- Validation 및 2024-07-01 이후 행은 접근하지 않는다.

## 배당·정산 계약

- 실제 손익: `canonical.winning_payout`의 `pool_code='연식'` 및 `confirmed_odds`
- 적중 조인: `race_id + 선택 gate_no = horse_no_1`
- 전 출전마 최종 시장배당: `canonical.runner_result.place_odds`; 시장 관계와 사후 EV에만 사용
- 사전 감사에서 OOF 19,168행 모두 `place_odds`가 있고 공식 양성 5,462행도 모두 정산배당과
  연결됐다.
- 3개 경주의 6개 적중행은 두 배당이 달랐다. 이 경우를 포함한 실제 손익은 무조건
  `confirmed_odds`를 우선한다.
- 소수배당은 원금을 포함한 총환급 배수로 해석한다. 1단위 적중 시 총환급은
  `confirmed_odds`, 미적중 시 0, 손익은 `총환급 - 1`이다.
- 적중행에 유일한 공식 정산배당이 없거나 키가 중복된 경주는 fail-closed로 제외하고 전부 보고한다.

## 사전 고정 분석

1. 모든 적격 경주에서 sigmoid 확률 1위 한 마리에 1단위 고정 베팅한다.
2. 동률은 확률 내림차순, `gate_no`, `horse_id` 오름차순으로 결정한다.
3. 신뢰도 threshold는 `0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70`만 기술한다.
4. 확률 bucket은 0.1 간격으로 고정한다.
5. 사후 EV proxy는 `sigmoid_probability × final place_odds - 1`이다. 실제 정산 손익과 다르며
   prediction cutoff에서는 사용할 수 없다.
6. 위험은 날짜·경주키 순 누적손익, 최대낙폭, 최장 연속손실, 100-bet rolling ROI, 월별 결과로
   기술한다.
7. 최고 적중배당 1건·5건 제거 민감도를 고정한다.
8. 어떤 threshold·edge rule도 결과를 보고 공식 전략으로 선택하지 않는다.

기계 판독 가능한 전체 계약은
[`plc-exploratory-betting-backtest-contract.json`](plc-exploratory-betting-backtest-contract.json)에
봉인한다.
