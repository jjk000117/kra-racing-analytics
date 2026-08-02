# ruff: noqa: E501 -- Reader-facing Korean Markdown is kept as natural sentences.
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
        markdown("""# 5E-1 공식 적중배당 원문 프로파일링

## tl;dr

- 시장 분석 대상 4,582경주의 7개 승식, 총 32,074개 `confirmed_odds_raw` 행은 모두 비어 있지 않다.
- 관찰된 원문은 `마번조합-배당` 형식이며, 여러 적중 조합은 공백 2개로 구분된다. 마번은 ①~⑮와 `(16)`으로 표현된다.
- 현재 데이터 전체를 제안한 규칙으로 해석했을 때 32,074행과 50,494개 적중 조합이 모두 성공했고, 중복 마번·중복 조합·0 이하 배당은 없다.
- 동착 때문에 단승·복승·쌍승·삼복승·삼쌍승도 일부 행에 2개 적중 조합이 있다. 따라서 정규화 목표 Grain은 `경주 × 승식 × 공식 적중 조합`이어야 한다.
- 쌍승식·삼쌍승식은 순서를 보존하고, 복승식·복연승식·삼복승식은 마번을 정렬한 canonical 조합을 별도로 만든다.
"""),
        markdown("""## Context & Methods

이 Notebook은 배당 수준으로 승식을 평가하기 전에 API179의 적중배당 문자열이 일관되게 정규화 가능한지 확인한다. 원문은 변경하지 않으며 DuckDB를 읽기 전용으로 연다.

### Key Assumptions

- 모집단은 `analytics.mart_market_sales`의 4,582경주 × 7개 공식 승식이다.
- 적중배당은 경주 종료 후 정보이므로 모델 Feature로 사용할 수 없다.
- 현재 관찰된 형식의 100% 해석 성공은 향후 API 형식이 바뀌지 않는다는 보장이 아니다. 정규화 단계에는 실패 행 격리와 감사를 유지해야 한다.
"""),
        code("""from pathlib import Path

import duckdb
import pandas as pd

from kra_analytics.odds_profiling import profile_confirmed_odds

PROJECT_ROOT = Path.cwd()
if not (PROJECT_ROOT / "pyproject.toml").is_file():
    PROJECT_ROOT = PROJECT_ROOT.parent
DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "kra.duckdb"
pd.options.display.float_format = "{:,.2f}".format

connection = duckdb.connect(str(DB_PATH), read_only=True)
source = connection.execute(
    "SELECT s.sales_id, s.race_id, p.pool_name_raw AS pool_code, "
    "p.pool_code AS pool_code_standard, p.pool_name_official, "
    "p.selection_count, p.order_matters, s.confirmed_odds_raw, "
    "r.race_date, r.meet_code, r.race_no "
    "FROM analytics.mart_market_sales s "
    "JOIN analytics.dim_pool p USING (pool_key) "
    "JOIN canonical.race r USING (race_id) "
    "ORDER BY r.race_date, r.meet_code, r.race_no, p.display_order"
).df()
connection.close()
"""),
        markdown("""## Data

### 1. 모집단과 원문 완전성
"""),
        code("""source_summary = pd.Series({
    "rows": len(source),
    "races": source["race_id"].nunique(),
    "pools": source["pool_code_standard"].nunique(),
    "blank_raw_rows": source["confirmed_odds_raw"].isna().sum()
        + source["confirmed_odds_raw"].fillna("").str.strip().eq("").sum(),
    "date_min": source["race_date"].min(),
    "date_max": source["race_date"].max(),
})
source_summary.to_frame("value")
"""),
        code("""assert len(source) == 4582 * 7
assert source["race_id"].nunique() == 4582
assert source["pool_code_standard"].nunique() == 7
assert source_summary["blank_raw_rows"] == 0
"""),
        markdown("""## Results

### 2. 전체 형식 해석과 무결성 검사

원문에서 조합별 행을 풀어내되 아직 DB 테이블에는 적재하지 않는다. 이 단계의 목적은 다음 정규화 설계를 검증하는 것이다.
"""),
        code("""parsed, issues = profile_confirmed_odds(source)

duplicate_grain = parsed.duplicated(["sales_id", "source_order"]).sum()
duplicate_combinations = parsed.duplicated(
    ["sales_id", "horse_numbers_canonical"]
).sum()
nonpositive_odds = parsed["confirmed_odds"].le(0).sum()

validation = pd.Series({
    "source_rows": len(source),
    "parsed_source_rows": parsed["sales_id"].nunique(),
    "parsed_combination_rows": len(parsed),
    "parse_issue_rows": len(issues),
    "duplicate_grain_rows": duplicate_grain,
    "duplicate_combination_rows": duplicate_combinations,
    "nonpositive_odds_rows": nonpositive_odds,
})
validation.to_frame("value")
"""),
        code("""assert parsed["sales_id"].nunique() == len(source)
assert issues.empty
assert duplicate_grain == 0
assert duplicate_combinations == 0
assert nonpositive_odds == 0
"""),
        markdown("""### 3. 승식별 원문 길이와 적중 조합 개수

단일 조합 승식도 동착 경주에서는 2개 조합이 기록된다. 연승식은 2~4개, 복연승식은 3개 또는 6개 조합이다.
"""),
        code("""row_profile = source.assign(
    raw_length=source["confirmed_odds_raw"].str.len(),
    combination_count=source["sales_id"].map(parsed.groupby("sales_id").size()),
)

length_summary = row_profile.groupby(
    ["pool_code_standard", "pool_name_official"], sort=False
).agg(
    source_rows=("sales_id", "size"),
    min_raw_length=("raw_length", "min"),
    max_raw_length=("raw_length", "max"),
    min_combinations=("combination_count", "min"),
    max_combinations=("combination_count", "max"),
).reset_index()
length_summary
"""),
        code("""combination_distribution = (
    row_profile.groupby(
        ["pool_code_standard", "pool_name_official", "combination_count"]
    ).size().rename("source_rows").reset_index()
)
combination_distribution
"""),
        markdown("""### 4. 동착으로 적중 조합 수가 늘어난 경주

통상 개수(WIN/QNL/EXA/TLA/TRI=1, PLC/QPL=3)와 다른 행만 표시한다. 연승식 2개는 출전두수 규칙에 따른 정상 가능성이 있으므로 동착과 동일시하지 않고 정규화에서는 관찰값 그대로 보존한다.
"""),
        code("""usual_count = {"WIN": 1, "PLC": 3, "QNL": 1, "EXA": 1, "QPL": 3, "TLA": 1, "TRI": 1}
exceptions = row_profile[
    row_profile["combination_count"]
    != row_profile["pool_code_standard"].map(usual_count)
][[
    "race_date", "meet_code", "race_no", "pool_code_standard",
    "pool_name_official", "combination_count", "confirmed_odds_raw"
]]
exceptions
"""),
        markdown("""### 5. 승식별 확정배당 분포

배당은 평균보다 중앙값과 상위 분위수를 중심으로 본다. 이 표는 형식 프로파일의 부가 결과이며 아직 승식 선정 근거로 단독 사용하지 않는다.
"""),
        code("""odds_profile = parsed.merge(
    source[["sales_id", "pool_code_standard", "pool_name_official"]], on="sales_id"
).groupby(["pool_code_standard", "pool_name_official"], sort=False)["confirmed_odds"].agg(
    combinations="size",
    minimum="min",
    q25=lambda values: values.quantile(0.25),
    median="median",
    q75=lambda values: values.quantile(0.75),
    q95=lambda values: values.quantile(0.95),
    q99=lambda values: values.quantile(0.99),
    maximum="max",
).reset_index()
odds_profile
"""),
        markdown("""### 6. 마번 표현과 순서 정책 검증

마번 16은 `(16)`으로 표현되며 현재 25개 조합에서 관찰된다. 순서가 중요한 쌍승·삼쌍은 원문 순서를 유지하고, 그 외 조합 승식은 비교와 중복 검사를 위해 오름차순 canonical 조합을 별도로 둔다.
"""),
        code("""horse_16_items = parsed["horse_numbers_source"].map(lambda values: 16 in values).sum()
order_policy = source[[
    "pool_code_standard", "pool_name_official", "selection_count", "order_matters"
]].drop_duplicates().sort_values("pool_code_standard")
display(pd.Series({"combinations_containing_horse_16": horse_16_items}).to_frame("value"))
order_policy
"""),
        markdown("""## Takeaways

1. **정규화 가능성**: 현재 32,074행과 50,494개 적중 조합은 제안 규칙으로 모두 해석되며 즉시 확인된 형식 오류는 없다.
2. **목표 Grain**: 동착이 존재하므로 `race × pool`이 아니라 `race × pool × winning combination`으로 만들어야 정보 손실이 없다.
3. **원문 보존**: `confirmed_odds_raw`, `sales_id`, `source_order`를 유지해야 파싱 결과를 원문까지 역추적할 수 있다.
4. **마번 저장**: 표시 문자열과 별도로 마번을 정수 1~16으로 저장한다. `(16)`은 16으로 변환한다.
5. **순서 처리**: EXA·TRI는 원문 순서를 보존하고 QNL·QPL·TLA는 정렬된 canonical 조합을 함께 저장한다.
6. **안전장치**: 이후 새 데이터에서 미지원 문자, 선택 수 불일치, 중복 마번, 중복 조합, 0 이하 배당이 나오면 조용히 버리지 말고 품질 이슈로 격리한다.
"""),
    ]
    target = Path("notebooks/05e_confirmed_odds_profiling.ipynb")
    nbformat.write(notebook, target)
    print(target)


if __name__ == "__main__":
    main()
