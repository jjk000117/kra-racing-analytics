from pathlib import Path

import nbformat


def markdown(text: str) -> nbformat.NotebookNode:
    return nbformat.v4.new_markdown_cell(text)


def code(text: str) -> nbformat.NotebookNode:
    return nbformat.v4.new_code_cell(text)


notebook = nbformat.v4.new_notebook()
notebook["metadata"]["kernelspec"] = {
    "display_name": "Python 3 (kra-racing-analytics)",
    "language": "python",
    "name": "python3",
}
notebook["metadata"]["language_info"] = {"name": "python", "version": "3.12"}
notebook["cells"] = [
    markdown(
        """# PLC exploratory betting and economic backtest

This notebook is the inspectable reporting companion for the sealed Development-only analysis.
It reads the row-level OOF and summary artifacts produced by
`kra_analytics.exploratory_betting_backtest`; it does not retrain a model or access Validation.

Final PLC odds and confirmed payouts are post-cutoff information. All ROI and EV results below
are retrospective diagnostics, not deployable strategy performance."""
    ),
    code(
        """from pathlib import Path
import json
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path.cwd().resolve()
if ROOT.name == 'notebooks':
    ROOT = ROOT.parent
OUTPUT = ROOT / 'data/exports/modeling/plc_exploratory_betting_backtest_v1'
result = json.loads((OUTPUT / 'result.json').read_text(encoding='utf-8'))
thresholds = pd.read_csv(OUTPUT / 'confidence_threshold_summary.csv')
buckets = pd.read_csv(OUTPUT / 'probability_bucket_summary.csv')
monthly = pd.read_csv(OUTPUT / 'monthly_strategy_summary.csv')
edges = pd.read_csv(OUTPUT / 'retrospective_ev_summary.csv')
cumulative = pd.read_csv(OUTPUT / 'cumulative_profit.csv')
assert result['validation_access_count'] == 0
assert result['rows_on_or_after_2024_07_01_loaded'] == 0
assert result['oof_restoration']['max_absolute_delta'] <= 1e-12"""
    ),
    markdown("## Coverage and fixed Top1 settlement"),
    code(
        """pd.DataFrame([
    result['settlement_audit'],
    result['top1_fixed'],
], index=['settlement_audit', 'top1_fixed']).T"""
    ),
    markdown("## Predeclared confidence sensitivity (no threshold selection)"),
    code(
        """display(thresholds[['threshold', 'bets', 'bet_rate', 'hit_rate', 'roi',
                    'net_profit', 'max_drawdown', 'longest_losing_streak']])
fig, left = plt.subplots(figsize=(9, 4))
left.plot(thresholds['threshold'], thresholds['roi'], marker='o', label='ROI')
left.plot(thresholds['threshold'], thresholds['hit_rate'], marker='o', label='Hit rate')
left.set(xlabel='Minimum Top1 probability', ylabel='Rate')
right = left.twinx()
right.bar(thresholds['threshold'], thresholds['bets'], width=0.025, alpha=0.2)
right.set_ylabel('Bets')
left.legend(); plt.show()"""
    ),
    markdown("## Probability calibration and final-market payout structure"),
    code(
        """display(buckets)
fig, left = plt.subplots(figsize=(10, 4))
x = range(len(buckets))
left.plot(x, buckets['mean_predicted_probability'], marker='o', label='Predicted')
left.plot(x, buckets['observed_plc_rate'], marker='o', label='Observed')
left.set_xticks(list(x), buckets['probability_bucket'], rotation=45)
left.set_ylabel('Probability / hit rate')
right = left.twinx()
right.plot(x, buckets['median_final_place_odds'], color='tab:green', marker='s')
right.set_ylabel('Median final PLC odds')
left.legend(); plt.show()"""
    ),
    markdown("## Hindsight EV buckets — not decision-time EV"),
    code("display(edges)"),
    markdown("## Monthly stability and cumulative risk"),
    code(
        """display(monthly[['month', 'bets', 'hit_rate', 'roi', 'net_profit']])
fig, axes = plt.subplots(1, 2, figsize=(13, 4))
axes[0].bar(monthly['month'], monthly['roi'])
axes[0].tick_params(axis='x', rotation=45)
axes[0].set(title='Monthly hindsight ROI', ylabel='ROI')
axes[1].plot(cumulative['bet_number'], cumulative['cumulative_profit'])
axes[1].set(title='Top1 cumulative profit', xlabel='Bet', ylabel='Units')
plt.tight_layout(); plt.show()"""
    ),
    markdown(
        """## Interpretation boundary

- The model strongly overlaps the final market favorite structure, but no decision-time odds were
  observed.
- Fixed Top1 and every predeclared confidence threshold lost money in this Development OOF period.
- Final-payout EV buckets are hindsight-only and cannot be used to select a live edge rule.
- No Validation or data on/after 2024-07-01 was accessed."""
    ),
]

target = Path("notebooks/12_plc_exploratory_betting_backtest.ipynb")
target.parent.mkdir(parents=True, exist_ok=True)
nbformat.write(notebook, target)
print(target)
