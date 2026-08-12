# API4 `wgHr` parsing 및 Snapshot v2 전체기간 준비 상태

기준일: 2026-08-13

## 확정한 Semantic v2 parsing

- `480()` → `horse_weight_kg=480`, `horse_weight_change_kg=0`
- `480(+5)` → `horse_weight_kg=480`, `horse_weight_change_kg=5`
- `480(-5)` → `horse_weight_kg=480`, `horse_weight_change_kg=-5`
- `()` → 두 값 모두 NULL

숫자 중량 뒤 빈 괄호만 0으로 해석한다. 이 정책은 직전 실제 출전 마체중과의 직접 비교에서
2026년 7월 이전 5,313/5,313행이 0kg으로 일치한 결과에 근거한다. 2026년 7월의 13건 불일치는
같은 달 명시적 `+N/-N` 대조군에서도 200건 발생했으므로 별도 원천 품질 제한으로 유지한다.

## Semantic 전체기간 audit

- Staging/Semantic: 각각 87,025행
- 업무키 중복, 경주시간·마체중 파싱 실패, 비현실 범위: 모두 0건
- `중량()` → 0: 5,843행
- `()` → NULL: 663행
- 경마장 반대편 sectional 원천 혼입: 0건

## Snapshot v2 재생성 blocker

현재 확정된 모델 데이터 계약은 `place_hit`과 모든 Historical PLC 적중률의 유일한 근거를
`canonical.winning_payout(pool_code='PLC')`의 공식 적중마 목록으로 제한한다.

현재 원천 범위:

- API4 Staging/Semantic: 2022~2026
- Sales Staging, Canonical 모집단 및 공식 winning payout: 2024~2026

따라서 2022·2023을 Historical warm-up으로 넣으면 horse/jockey/trainer/owner 및 interaction의
PLC 이력을 기존 정의대로 계산할 수 없다. `ord` 또는 착순 기준으로 대체하면 타깃 계약 변경이므로
이번 작업에서 임의 적용하지 않는다. 또한 2022·2023을 Snapshot 출력 행으로 만들 공식 PLC 타깃도 없다.

Snapshot v2 전체기간 재생성 전에 2022·2023 공식 Sales/배당 Raw를 수집·감사하고,
Canonical winning payout 및 모집단을 같은 계약으로 확장해야 한다. 그 전까지 기존 Snapshot v2와
117개 모델 입력 계약은 변경하지 않는다.

