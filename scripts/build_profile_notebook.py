from __future__ import annotations

from pathlib import Path

import nbformat


def markdown(text: str):
    return nbformat.v4.new_markdown_cell(text)


def code(text: str):
    return nbformat.v4.new_code_cell(text)


def main() -> None:
    notebook = nbformat.v4.new_notebook()
    notebook["metadata"]["kernelspec"] = {
        "display_name": "Python 3 (kra-racing-analytics)",
        "language": "python",
        "name": "python3",
    }
    notebook["cells"] = [
        markdown("""# 2C Raw Data Profiling

## tl;dr

- 정식 배치 기준 API4_3은 49,386개 출전 행·4,600경주이고 API179_1은 32,074개 승식 행·4,582경주다.
- 업무 키 중복과 필수 키 결측은 모두 0건이다.
- 매출 경주는 결과에 100% 결합되며, 결과 경주 중 18개에는 매출이 없다.
- 매출은 7개 승식이 경주마다 한 행씩 존재하고 금액 형식 오류는 0건이다.
"""),
        markdown("""## Context & Methods

### Key Assumptions

- Manifest에서 API별 완료 배치 중 요청 수가 가장 큰 전체 배치를 선택한다.
- API4_3 grain은 `rcDate + meet + rcNo + hrNo`, API179_1은 `rcDate + meet + rcNo + pool`이다.
- 경주 결합 키는 `rcDate + meet + rcNo`이며 경마장 명칭은 코드 1/3으로 정규화한다.
- Raw 파일은 읽기만 하며 수정하지 않는다.
"""),
        code("""from pprint import pprint

from kra_analytics.profiling import build_raw_profile

profile = build_raw_profile()
"""),
        markdown("## Data\n\n### 1. 배치와 기본 범위"),
        code("""summary_fields = (
    "files", "rows", "columns_union", "columns_common", "date_min", "date_max"
)
pprint(
    {
        "race_batch_id": profile["race_batch_id"],
        "sales_batch_id": profile["sales_batch_id"],
        "race": {key: profile["race"][key] for key in summary_fields},
        "sales": {key: profile["sales"][key] for key in summary_fields},
    }
)
"""),
        markdown("## Results\n\n### 2. 키·결측·결합 품질"),
        code("""pprint({
    "race_required_missing": profile["race"]["missing_required"],
    "sales_required_missing": profile["sales"]["missing_required"],
    "race_duplicate_key_rows": profile["race"]["duplicate_business_key_rows"],
    "sales_duplicate_key_rows": profile["sales"]["duplicate_business_key_rows"],
    "race_exact_duplicates": profile["race"]["exact_duplicate_rows"],
    "sales_exact_duplicates": profile["sales"]["exact_duplicate_rows"],
    "race_distinct_races": profile["race_distinct_races"],
    "sales_distinct_races": profile["sales_distinct_races"],
    "shared_races": profile["shared_races"],
    "race_without_sales": profile["race_without_sales"],
    "sales_without_race": profile["sales_without_race"],
    "race_join_rate": profile["race_join_rate"],
    "sales_join_rate": profile["sales_join_rate"],
})
"""),
        markdown("### 3. 매출 도메인과 예외 경주"),
        code("""pprint({
    "sales_pools": profile["sales_pools"],
    "sales_amount_invalid": profile["sales_amount_invalid"],
    "by_scope": profile["by_scope"],
})
pprint(profile["race_without_sales_details"])
"""),
        markdown("""## Takeaways

1. 정식 배치 내부 업무 키 중복이 없어 후보 키를 Staging에서 유지할 수 있다.
2. API4_3의 89개 필드는 원문 중심으로 적재하며 선택 필드 결측은 그대로 보존한다.
3. API179_1의 6개 필드와 7개 승식은 안정적이며 `amt` 변환 검사를 자동화한다.
4. 매출 없는 18경주는 삭제하지 않고 품질 이슈로 격리한다.
5. 매출·확정배당은 post-race 정보이므로 예측 Feature 계층과 분리한다.
"""),
    ]
    nbformat.write(notebook, Path("notebooks/02c_raw_data_profiling.ipynb"))


if __name__ == "__main__":
    main()
