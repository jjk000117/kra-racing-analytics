# 공식 연승 Baseline Snapshot 후보 명세 v2

상태: cutoff 및 Feature 사전 이용 가능성 검증 완료. Snapshot 미구현, 모델 미학습.

## Prediction cutoff와 구현 가능 범위 (2026-08-12)

- cutoff: 경주 결과 발생 전의 실제 베팅 의사결정 시점. 정확한 `T-N분`은 아직 고정하지 않는다.
- 실시간 배당: baseline 입력 제외, 후속 betting-stage only.
- API4 확정 배당과 현재 경주 sectional: 사후정보이므로 계속 금지.
- registry 141개 중 즉시 Snapshot v2 구현 후보는 126개다.
- `NEEDS_VALIDATION` 12개는 공식 화면·명세·저장값 대조를 거쳐 모두 해소했다.
- 현재 마체중·증감·날씨·주로상태·함수율과 부가상금 1~3은 `APPROVED`다.
- 과거 G3F/G1F 최근 3/5회 중앙값은 경마장별 원천을 동일한 최종 600m/200m 초로
  변환하는 조건으로 `APPROVED_WITH_FLAG`다.
- 상세 근거와 변환식: `docs/official-place-baseline-cutoff-validation-v2.md`

## 목적과 버전 경계

새 공식 baseline은 `place_logistic_baseline_v1`의 28개 입력을 증분 수정하지 않는다. `semantic.api4_runner_event_v2`와 `docs/place-feature-registry-v2.csv`를 원천 계약으로 사용해 별도 Snapshot 버전으로 설계한다.

제안 Snapshot 버전명은 `place_feature_snapshot_v2_candidate`다. 이 이름은 아직 물리 테이블이나 모델 버전을 생성하지 않는다.

## Grain과 모집단

- Grain: `경주 × 베팅 가능 출전마`
- 업무키: `race_id + horse_id`
- 타깃: 공식 연승 적중 여부
- 모집단: 기존 DNS 말 단위 제외 정책과 정상 시행 경주 계약 승계
- 현재 경주 결과 상태는 모집단·타깃 감사에만 사용하고 Feature에 사용하지 않음

## Feature 그룹

| 그룹 | 후보 수 | Snapshot 처리 |
|---|---:|---|
| 즉시 계산 후보 | 126 | 값·관측 count·가용성·lineage 저장 후보 |
| 추가 검증 후 포함 | 0 | 이번 cutoff 검증에서 모두 판정 완료 |
| 후속 고도화 | 5 | v2 첫 구현 범위에서 제외 |
| 사용 금지 | 10 | 계산 금지와 audit rule로 관리 |

126개 즉시 후보의 정확한 이름과 계산 정의는 `docs/place-feature-registry-v2.csv`에서 `recommendation_group=IMMEDIATE_BASELINE`으로 조회한다. Snapshot 구현 시 이 목록을 임의 축소하지 않으며, 계산 불가능한 항목은 구현 중 조용히 제외하지 않고 registry status를 갱신한다.

## 필수 관리·감사 컬럼

- `snapshot_version`, `feature_as_of`, `source_batch_id`, `semantic_version`
- `history_window_start_date`, `source_max_event_date`, `history_complete`
- entity/window/condition별 관측 count
- structural missing과 ordinary NULL 구분 플래그
- 모집단 상태와 제외 이유

## PIT 불변조건

- 모든 Historical join은 `hist.race_date < cur.race_date`
- 같은 경주일의 다른 경주 사용 금지
- 현재 경주의 착순·시간·sectional·착차·배당·매출 사용 금지
- 현재 날씨·주로·마체중은 prediction cutoff 전에 관측된 값만 사용
- API26/API37 누적값 사용 금지

## 속도·sectional 계약

- 경주시간은 `valid_race_time_seconds`만 사용
- `0`과 비출전·취소·유효하지 않은 기록 제외
- 단순 시간은 동일거리 또는 거리 companion과 함께 사용
- S1F는 `s1f_seconds` 사용 가능
- G3F/G1F는 검증된 경마장별 변환식으로 최종 600m/200m 초를 생성
- 복잡한 속도지수와 코너 페이스는 후속 고도화

## 결측 계약

- 이력 없음: 값 NULL, count 0, availability false
- 거리/경마장 구조상 필드 없음: structural missing true
- `wgHr='중량()'`: 중량 사용, 증감 NULL
- `wgHr='()'`: 중량·증감 NULL
- 날씨 `-`, 주로 `(0%)`: unknown/상태 NULL로 보존하고 임의 범주화 금지

## 종료 조건

다음 구현 단계는 126개 즉시 후보를 계산하는 Snapshot과 PIT·lineage·결측 audit까지만 수행한다. 모델 학습과 성능 기반 Feature 선택은 별도 단계다.
