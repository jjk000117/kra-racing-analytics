# Post-baseline v2 F1/F2/F3 구현·데이터 감사

## 결론

봉인된 registry와 1:1로 대응하는 F1 6개, F2 8개, F3 10개를
`mart.place_feature_snapshot_v2_engineered_candidate`에 구현했다. 전체 85,566행·8,036경주에서
업무키 중복, PIT 위반, percentile 범위 위반, recent count 관계 위반과 count/value 모순은 모두
0건이다. 기존 117개 입력은 변경하지 않았으며 세 bundle을 이후 Logistic development 실험에서
독립적으로 선택할 수 있다.

## 구현 계층과 lineage

- 기존 125개 Snapshot Feature는 `mart.place_feature_snapshot_v2_candidate`에서 그대로 승계한다.
- F1은 Canonical runner 상태와 Semantic `valid_race_time_seconds`를 결합해 과거 경주 안에서
  event-level 상대시간과 평균동률 percentile을 먼저 계산한 뒤 말별 recent3/recent5로 집계한다.
- F2는 Semantic 공통 `s1f_seconds`, `historical_g3f_seconds`, `historical_g1f_seconds`로 과거
  event-level pace quantity를 먼저 계산한 뒤 recent3/recent5로 집계한다.
- F3는 기존 Snapshot의 cutoff-known 원본 Feature를 동일 경주 안에서만 상대화한다.
- F1/F2 최대 참조일은 `quality.post_baseline_v2_feature_source_audit`에 별도로 보존한다.

F1 비교집단은 `FINISHED`, valid start, valid finish, 양의 유효 race time을 모두 만족하는 말로
한정했다. 비교 가능 말이 3두 미만인 경주는 제외한다. 실제 전체 원천의 비교집단은 경주당
6~16두였으며 3두 미만으로 제외된 유효 경주는 없었다.

F2는 두 식을 event-level에서 독립 계산했다.

- late kick: `(G3F - 3 × G1F) / 2`
- finish versus start: `S1F - G1F`

2022~2025의 유효 완주행은 두 식의 공동 sectional이 모두 존재했다. 2026년 서울에서는
11,226개 유효 완주행 중 80개에서 공동 sectional이 없어 두 F2 계열에서 제외했다. 부산경남의
공동 sectional 누락은 없었다.

F3 percentile은 NULL 원본을 비교집단에서 제외하고 average tie를 적용했다. 높은 값이 좋은
원본은 오름차순 average rank를 0~1로 바꾸고, sectional처럼 낮은 값이 좋은 원본은 방향을
반전했다. 비교 가능 3두 미만 비율은 장기/최근5 PLC 및 sectional 3.61%, 동일거리 PLC 7.59%,
기수·조교사 recent10 0.24%였고 rating과 부담중량은 0%였다.

## Feature 가용성과 범위

전체 가용률과 값 범위는
`data/exports/validation/post_baseline_v2_feature_bundles/feature_profile_overall.csv`, 연도별·경마장별
가용률은 각각 `availability_by_year.csv`, `availability_by_meet.csv`에 저장했다.

- F1/F2 요약값 전체 가용률은 91.53%, count는 100%다.
- F3는 rating·부담중량 100%, 기수 99.53%, 조교사 99.68%, 장기/최근5 PLC와 sectional 약
  91.31%, 동일거리 PLC 71.39%다.
- 연도별 최소 가용률은 F1/F2가 2022년 82.03%에서 2026년 95.08%로 증가했다. F3 최소값은
  57.53%에서 78.01%로 증가해 warm-up에 따른 이력 성숙과 일치한다.
- 서울/부산경남 최소 가용률 차이는 F1/F2 0.16%p, F3 0.77%p로 작았다.
- 모든 percentile은 `[0, 1]` 안에 있었고 NaN/Inf 및 count/value 모순은 발견되지 않았다.
- time advantage 범위는 -32.6~3.7초다. 큰 음수는 유효 완주로 분류된 매우 느린 과거 기록의
  영향이며 파싱 불가능값이나 PIT 위반은 아니다. 이번 계약은 임의 winsorization을 추가하지 않는다.

## 독립 표본 재계산과 중복 감사

F1은 5개 과거 경주의 원천 race time을 직접 정렬해 동률 average rank와 0=열위/1=우위 방향을
재계산했다. F3 rating percentile은 3개 표본 경주에서 상관 서브쿼리로 독립 재계산했고 저장값과
차이는 전 행 0이었다. 표본은 `f1_percentile_sample_recalculation.csv`와
`f3_percentile_sample_recalculation.csv`에 보존했다.

신규 count와 가장 가까운 기존 sectional/race-time count를 비교한 결과 모든 쌍에서
7,241~7,277행이 달랐다. 이는 F1의 경주 비교집단 조건과 F2의 같은 event 공동 관측 조건 때문이며
deterministic duplicate가 아니다. bundle 이름 중복은 0이고 registry 24개와 구현 24개가 정확히
일치한다. best-time gap, raw rank, F1/F2 재상대화, 추가 window는 생성하지 않았다.

## PIT·leakage와 보호 결과

- F1/F2 참조 최대일 `>= feature_as_of`: 0행
- F3 계산 원천: 현재 경주의 cutoff-known 기존 Snapshot Feature만 사용
- 현재 경주 착순, `place_hit`, 배당, race time, sectional, 착차를 신규 식에 사용: 0개
- 현재 경주의 결과 컬럼은 기존 Snapshot 관리/타깃 컬럼으로만 승계되며 신규 Feature 계산에는
  참여하지 않는다.
- 기존 model input: 117개, hash
  `cc18ef4bf88438ccbfbe836a29aec34f5356e52976b834124a065c89e57e8d2b`
- 봉인 run contract와 refit artifact SHA256은 보호 manifest와 일치했다.

따라서 데이터 계약 관점의 blocker는 없다. 다음 단계는 동일한 네 development temporal fold에서
B0, B0+F1, B0+F2, B0+F3를 사전 계약 그대로 실행하는 것이다. Validation 및 2024-07 이후 데이터는
이번 구현·감사에서 모델 성능 평가에 사용하지 않았다.

## 재현 명령과 산출물

```powershell
kra-analytics feature build-post-baseline-bundles
kra-analytics feature check-post-baseline-bundles
```

감사 CSV/JSON은
`data/exports/validation/post_baseline_v2_feature_bundles/`에 저장된다. 주요 파일은 전체·연도별·경마장별
가용성, F1 비교집단, F2 공동 sectional, F3 비교 가능 두수, 독립 표본 재계산, 구조 중복 감사와
`audit_summary.json`이다.
