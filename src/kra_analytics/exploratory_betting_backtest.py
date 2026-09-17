from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.balanced_class_weight_ablation import (
    BASELINE_NAME,
    _evaluate,
    _fit_raw,
    feature_contract,
    temporal_oof,
)
from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS, _fold_frames
from kra_analytics.experiment_database import (
    connect_source_database,
    resolve_experiment_database_paths,
)
from kra_analytics.modeling import fit_sigmoid_calibrator
from kra_analytics.modeling_v2 import TARGET_COLUMN
from kra_analytics.paths import ProjectPaths
from kra_analytics.prize_bonus_ablation import _sha256_file
from kra_analytics.relative_experiment import _load_frame

EXPERIMENT_VERSION = "plc_exploratory_betting_backtest_v1"
CONTRACT_PATH = "docs/plc-exploratory-betting-backtest-contract.json"
REFERENCE_RESULT = (
    "data/exports/modeling/"
    "plc_balanced_class_weight_development_ablation_v1/result.json"
)
OUTPUT_DIRECTORY = f"data/exports/modeling/{EXPERIMENT_VERSION}"
THRESHOLDS = (0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)
PROBABILITY_EDGES = tuple(np.linspace(0.0, 1.0, 11))
EDGE_EDGES = (-np.inf, -0.50, 0.00, 0.25, 0.50, 1.00, np.inf)
EDGE_LABELS = (
    "<=-0.50",
    "(-0.50,0.00]",
    "(0.00,0.25]",
    "(0.25,0.50]",
    "(0.50,1.00]",
    ">1.00",
)
REPRODUCTION_TOLERANCE = 1e-12


def load_contract(paths: ProjectPaths) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (paths.root / CONTRACT_PATH).read_text(encoding="utf-8")
    )
    if payload["contract_version"] != EXPERIMENT_VERSION:
        raise ValueError("Unexpected exploratory betting contract version")
    upstream = payload["upstream_model"]
    if (
        upstream["feature_count"] != 137
        or upstream["feature_hash"]
        != "7dd442ec9e2f2be47f438947bbec9e51d7f6851514f3400455f3e4292898417e"
        or upstream["name"] != BASELINE_NAME
        or upstream["class_weight"] is not None
    ):
        raise ValueError("Sealed 137-feature model contract mismatch")
    scope = payload["scope"]
    if any(
        scope[name]
        for name in (
            "validation_access_allowed",
            "post_2024_07_access_allowed",
            "post_2025_07_access_allowed",
        )
    ):
        raise ValueError("Contract permits forbidden temporal access")
    if tuple(payload["fixed_analyses"]["confidence_thresholds"]) != THRESHOLDS:
        raise ValueError("Confidence threshold grid mismatch")
    return payload


def longest_losing_streak(hits: pd.Series) -> int:
    longest = 0
    current = 0
    for hit in hits.astype(bool):
        if hit:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def max_drawdown(profits: pd.Series) -> float:
    cumulative = profits.astype(float).cumsum()
    wealth = cumulative + 1.0
    drawdown = wealth.cummax() - wealth
    return float(drawdown.max()) if not drawdown.empty else 0.0


def summarize_bets(bets: pd.DataFrame) -> dict[str, float | int]:
    if bets.empty:
        return {
            "bets": 0,
            "hits": 0,
            "hit_rate": float("nan"),
            "total_stake": 0.0,
            "gross_return": 0.0,
            "net_profit": 0.0,
            "roi": float("nan"),
            "average_winning_payout": float("nan"),
            "median_winning_payout": float("nan"),
            "max_winning_payout": float("nan"),
            "max_drawdown": 0.0,
            "longest_losing_streak": 0,
        }
    ordered = bets.sort_values(["race_date", "race_id"]).copy()
    wins = ordered.loc[ordered["place_hit"].astype(bool), "confirmed_odds"]
    stake = float(ordered["stake"].sum())
    gross = float(ordered["gross_return"].sum())
    return {
        "bets": len(ordered),
        "hits": int(ordered["place_hit"].sum()),
        "hit_rate": float(ordered["place_hit"].mean()),
        "total_stake": stake,
        "gross_return": gross,
        "net_profit": gross - stake,
        "roi": (gross - stake) / stake,
        "average_winning_payout": float(wins.mean()),
        "median_winning_payout": float(wins.median()),
        "max_winning_payout": float(wins.max()),
        "max_drawdown": max_drawdown(ordered["profit"]),
        "longest_losing_streak": longest_losing_streak(ordered["place_hit"]),
    }


def select_top1(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values(
        ["race_id", "sigmoid_probability", "gate_no", "horse_id"],
        ascending=[True, False, True, True],
    )
    selected = ordered.groupby("race_id", observed=True, sort=False).head(1).copy()
    selected = selected.sort_values(["race_date", "race_id"]).reset_index(drop=True)
    selected["stake"] = 1.0
    selected["gross_return"] = np.where(
        selected["place_hit"].astype(bool), selected["confirmed_odds"], 0.0
    )
    selected["profit"] = selected["gross_return"] - selected["stake"]
    return selected


def _restore_oof_predictions(
    paths: ProjectPaths, contract_payload: dict[str, Any]
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    model_contract = feature_contract(paths)
    if (
        len(model_contract.inputs) != contract_payload["upstream_model"]["feature_count"]
        or model_contract.feature_hash
        != contract_payload["upstream_model"]["feature_hash"]
    ):
        raise ValueError("Runtime Feature contract differs from the sealed contract")
    frame = _load_frame(paths, model_contract)
    if len(frame) != 28_392 or frame["race_id"].nunique() != 2_675:
        raise ValueError("Development population mismatch")
    if str(frame["race_date"].max()) >= "2024-07-01":
        raise ValueError("Development boundary violation")
    reference_payload = json.loads(
        (paths.root / REFERENCE_RESULT).read_text(encoding="utf-8")
    )
    reference = {
        row["fold_id"]: row
        for row in reference_payload["fold_metrics"]
        if row["candidate"] == BASELINE_NAME
    }
    restored: list[pd.DataFrame] = []
    fold_metrics: list[dict[str, Any]] = []
    max_absolute_delta = 0.0
    comparison_keys = (
        "raw_macro_log_loss",
        "raw_macro_brier",
        "raw_micro_log_loss",
        "raw_micro_brier",
        "raw_calibration_intercept",
        "raw_calibration_slope",
        "calibrated_macro_log_loss",
        "calibrated_macro_brier",
        "calibrated_micro_log_loss",
        "calibrated_micro_brier",
        "calibrated_calibration_intercept",
        "calibrated_calibration_slope",
        "calibrated_top1_plc_hit_rate",
        "calibrated_micro_recall_at_3",
        "calibrated_macro_ndcg_at_3",
        "calibrator_intercept",
        "calibrator_slope",
    )
    for fold in DEVELOPMENT_FOLDS:
        train, evaluation = _fold_frames(frame, fold)
        raw, _, warnings = _fit_raw(train, evaluation, model_contract, None)
        oof, oof_folds, _ = temporal_oof(train, model_contract, None)
        calibrator = fit_sigmoid_calibrator(
            train.loc[oof.index, TARGET_COLUMN], oof.to_numpy(dtype=float)
        )
        calibrated = calibrator.predict(raw)
        metrics: dict[str, Any] = {
            "fold_id": fold.fold_id,
            **_evaluate("raw", evaluation, raw),
            **_evaluate("calibrated", evaluation, calibrated),
            "calibrator_intercept": calibrator.intercept,
            "calibrator_slope": calibrator.slope,
            "warning_count": len(warnings)
            + sum(int(item["warning_count"]) for item in oof_folds),
        }
        deltas = {
            key: float(metrics[key]) - float(reference[fold.fold_id][key])
            for key in comparison_keys
        }
        fold_max = max(abs(value) for value in deltas.values())
        max_absolute_delta = max(max_absolute_delta, fold_max)
        if fold_max > REPRODUCTION_TOLERANCE:
            raise ValueError(
                f"OOF restoration failed for {fold.fold_id}: max delta {fold_max}"
            )
        metrics["reference_max_absolute_delta"] = fold_max
        fold_metrics.append(metrics)
        output = evaluation.loc[
            :,
            [
                "race_id",
                "horse_id",
                "race_date",
                "gate_no",
                "registered_runner_count",
                TARGET_COLUMN,
            ],
        ].copy()
        output["fold_id"] = fold.fold_id
        output["raw_probability"] = raw
        output["sigmoid_probability"] = calibrated
        restored.append(output)
    predictions = pd.concat(restored, ignore_index=True)
    if (
        len(predictions) != contract_payload["scope"]["expected_oof_rows"]
        or predictions["race_id"].nunique()
        != contract_payload["scope"]["expected_oof_races"]
        or predictions.duplicated(["race_id", "horse_id"]).any()
        or str(predictions["race_date"].max()) >= "2024-07-01"
    ):
        raise ValueError("Restored OOF population or boundary mismatch")
    audit = {
        "passed": True,
        "tolerance": REPRODUCTION_TOLERANCE,
        "max_absolute_delta": max_absolute_delta,
        "in_sample_probability_rows": 0,
    }
    return predictions, fold_metrics, audit


def _load_payouts(paths: ProjectPaths) -> tuple[pd.DataFrame, pd.DataFrame]:
    databases = resolve_experiment_database_paths(paths=paths)
    with connect_source_database(database_paths=databases) as connection:
        runner_odds = connection.execute(
            """
            SELECT rr.race_id, rr.horse_id, CAST(rr.place_odds AS DOUBLE) AS final_place_odds
            FROM canonical.runner_result AS rr
            JOIN canonical.race AS race USING (race_id)
            WHERE race.race_date >= DATE '2023-07-01'
              AND race.race_date < DATE '2024-07-01'
            """
        ).fetchdf()
        payouts = connection.execute(
            """
            SELECT payout.race_id, payout.horse_no_1 AS gate_no,
                   CAST(payout.confirmed_odds AS DOUBLE) AS confirmed_odds
            FROM canonical.winning_payout AS payout
            JOIN canonical.race AS race USING (race_id)
            WHERE payout.pool_code = ?
              AND race.race_date >= DATE '2023-07-01'
              AND race.race_date < DATE '2024-07-01'
            """,
            ["연식"],
        ).fetchdf()
    return runner_odds, payouts


def _join_and_audit_settlement(
    predictions: pd.DataFrame, runner_odds: pd.DataFrame, payouts: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if runner_odds.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate race/runner final odds key")
    if payouts.duplicated(["race_id", "gate_no"]).any():
        raise ValueError("Duplicate official PLC payout key")
    joined = predictions.merge(
        runner_odds, on=["race_id", "horse_id"], how="left", validate="one_to_one"
    ).merge(payouts, on=["race_id", "gate_no"], how="left", validate="many_to_one")
    payout_hit = joined["confirmed_odds"].notna()
    target_hit = joined[TARGET_COLUMN].astype(bool)
    mismatch = payout_hit != target_hit
    invalid_odds = joined["final_place_odds"].isna() | (joined["final_place_odds"] <= 0)
    excluded_races = set(joined.loc[mismatch | invalid_odds, "race_id"].astype(str))
    eligible = joined.loc[~joined["race_id"].astype(str).isin(excluded_races)].copy()
    eligible["retrospective_final_payout_ev"] = (
        eligible["sigmoid_probability"] * eligible["final_place_odds"] - 1.0
    )
    confirmed_difference = eligible.loc[target_hit.loc[eligible.index]].copy()
    confirmed_difference["odds_difference"] = (
        confirmed_difference["final_place_odds"]
        - confirmed_difference["confirmed_odds"]
    ).abs()
    audit = {
        "prediction_rows": len(joined),
        "prediction_races": int(joined["race_id"].nunique()),
        "runner_odds_joined_rows": int(joined["final_place_odds"].notna().sum()),
        "runner_odds_join_rate": float(joined["final_place_odds"].notna().mean()),
        "official_positive_rows": int(target_hit.sum()),
        "official_payout_rows_matched": int((target_hit & payout_hit).sum()),
        "target_payout_mismatch_rows": int(mismatch.sum()),
        "excluded_rows": int(joined["race_id"].astype(str).isin(excluded_races).sum()),
        "excluded_races": len(excluded_races),
        "eligible_rows": len(eligible),
        "eligible_races": int(eligible["race_id"].nunique()),
        "final_place_vs_confirmed_mismatch_rows": int(
            (confirmed_difference["odds_difference"] > 1e-9).sum()
        ),
        "cancelled_or_invalid_races_in_model_population": 0,
    }
    return eligible, audit


def _threshold_summary(top1: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total_races = top1["race_id"].nunique()
    for threshold in THRESHOLDS:
        selected = top1.loc[top1["sigmoid_probability"] >= threshold]
        summary = summarize_bets(selected)
        rows.append(
            {
                "threshold": threshold,
                "eligible_races": int(selected["race_id"].nunique()),
                "bet_rate": len(selected) / total_races,
                **summary,
            }
        )
    return pd.DataFrame(rows)


def _bucket_summary(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["probability_bucket"] = pd.cut(
        work["sigmoid_probability"], PROBABILITY_EDGES, include_lowest=True
    )
    grouped = work.groupby("probability_bucket", observed=False)
    rows: list[dict[str, Any]] = []
    for bucket, group in grouped:
        hits = group.loc[group[TARGET_COLUMN].astype(bool), "confirmed_odds"]
        rows.append(
            {
                "probability_bucket": str(bucket),
                "runner_count": len(group),
                "race_count": int(group["race_id"].nunique()),
                "mean_predicted_probability": float(group["sigmoid_probability"].mean()),
                "observed_plc_rate": float(group[TARGET_COLUMN].mean()),
                "calibration_gap": float(
                    group[TARGET_COLUMN].mean() - group["sigmoid_probability"].mean()
                ),
                "mean_final_place_odds": float(group["final_place_odds"].mean()),
                "median_final_place_odds": float(group["final_place_odds"].median()),
                "hit_runner_mean_confirmed_payout": float(hits.mean()),
            }
        )
    return pd.DataFrame(rows)


def _edge_summary(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["edge_bucket"] = pd.cut(
        work["retrospective_final_payout_ev"],
        EDGE_EDGES,
        labels=EDGE_LABELS,
        include_lowest=True,
    )
    work["stake"] = 1.0
    work["gross_return"] = np.where(
        work[TARGET_COLUMN].astype(bool), work["confirmed_odds"], 0.0
    )
    work["profit"] = work["gross_return"] - work["stake"]
    rows: list[dict[str, Any]] = []
    for bucket, group in work.groupby("edge_bucket", observed=False):
        rows.append(
            {
                "edge_bucket": str(bucket),
                "runner_count": len(group),
                "race_count": int(group["race_id"].nunique()),
                "observed_hit_rate": float(group[TARGET_COLUMN].mean()),
                "mean_final_place_odds": float(group["final_place_odds"].mean()),
                "mean_hindsight_ev": float(
                    group["retrospective_final_payout_ev"].mean()
                ),
                "retrospective_realized_roi": float(group["profit"].sum() / len(group)),
            }
        )
    return pd.DataFrame(rows)


def _monthly_summary(top1: pd.DataFrame) -> pd.DataFrame:
    work = top1.copy()
    work["month"] = pd.to_datetime(work["race_date"]).dt.to_period("M").astype(str)
    rows = []
    for month, group in work.groupby("month", sort=True):
        rows.append({"month": month, **summarize_bets(group)})
    return pd.DataFrame(rows)


def _risk_tables(top1: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cumulative = top1.sort_values(["race_date", "race_id"]).copy()
    cumulative["bet_number"] = np.arange(1, len(cumulative) + 1)
    cumulative["cumulative_profit"] = cumulative["profit"].cumsum()
    cumulative["running_peak"] = (cumulative["cumulative_profit"] + 1.0).cummax()
    cumulative["drawdown"] = cumulative["running_peak"] - (
        cumulative["cumulative_profit"] + 1.0
    )
    rolling = cumulative.loc[:, ["bet_number", "race_date", "race_id"]].copy()
    rolling["rolling_100_bet_roi"] = (
        cumulative["profit"].rolling(100, min_periods=100).sum() / 100.0
    )
    sensitivities: dict[str, Any] = {"original": summarize_bets(cumulative)}
    winning_indices = (
        cumulative.loc[cumulative[TARGET_COLUMN].astype(bool), "confirmed_odds"]
        .sort_values(ascending=False)
        .index
    )
    for count in (1, 5):
        adjusted = cumulative.copy()
        removed = list(winning_indices[:count])
        adjusted.loc[removed, "gross_return"] = 0.0
        adjusted["profit"] = adjusted["gross_return"] - adjusted["stake"]
        sensitivities[f"top_{count}_winning_payouts_set_to_zero"] = {
            **summarize_bets(adjusted),
            "removed_confirmed_odds": [
                float(value)
                for value in cumulative.loc[removed, "confirmed_odds"].tolist()
            ],
        }
    return cumulative, rolling, sensitivities


def _market_diagnostics(frame: pd.DataFrame, top1: pd.DataFrame) -> dict[str, Any]:
    work = frame.copy()
    work["model_rank"] = work.groupby("race_id", observed=True)[
        "sigmoid_probability"
    ].rank(method="average", ascending=False)
    work["payout_rank"] = work.groupby("race_id", observed=True)[
        "final_place_odds"
    ].rank(method="average", ascending=True)
    return {
        "spearman_probability_vs_final_place_odds": float(
            work["sigmoid_probability"].corr(work["final_place_odds"], method="spearman")
        ),
        "spearman_model_rank_vs_low_odds_rank": float(
            work["model_rank"].corr(work["payout_rank"], method="spearman")
        ),
        "top1_final_place_odds_mean": float(top1["final_place_odds"].mean()),
        "top1_final_place_odds_median": float(top1["final_place_odds"].median()),
        "top1_hit_final_place_odds_median": float(
            top1.loc[top1[TARGET_COLUMN].astype(bool), "final_place_odds"].median()
        ),
        "top1_miss_final_place_odds_median": float(
            top1.loc[~top1[TARGET_COLUMN].astype(bool), "final_place_odds"].median()
        ),
        "top1_share_final_place_odds_le_1_5": float(
            (top1["final_place_odds"] <= 1.5).mean()
        ),
        "top1_share_final_place_odds_le_2_0": float(
            (top1["final_place_odds"] <= 2.0).mean()
        ),
        "inverse_odds_not_interpreted_as_market_probability": True,
    }


def _write_charts(
    output: Path,
    cumulative: pd.DataFrame,
    thresholds: pd.DataFrame,
    monthly: pd.DataFrame,
    buckets: pd.DataFrame,
) -> list[str]:
    import matplotlib.pyplot as plt

    chart_paths: list[str] = []
    plt.style.use("seaborn-v0_8-whitegrid")
    figure, axis = plt.subplots(figsize=(10, 5))
    axis.plot(cumulative["bet_number"], cumulative["cumulative_profit"])
    axis.set(
        title="Top1 fixed cumulative profit (hindsight settlement)",
        xlabel="Bet",
        ylabel="Units",
    )
    path = output / "top1_cumulative_profit.png"
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)
    chart_paths.append(str(path))

    figure, left = plt.subplots(figsize=(10, 5))
    left.plot(thresholds["threshold"], thresholds["roi"], marker="o", label="ROI")
    left.plot(thresholds["threshold"], thresholds["hit_rate"], marker="o", label="Hit rate")
    left.set(xlabel="Minimum Top1 probability", ylabel="Rate")
    right = left.twinx()
    right.bar(thresholds["threshold"], thresholds["bets"], width=0.025, alpha=0.2)
    right.set_ylabel("Bets")
    left.legend(loc="upper left")
    path = output / "confidence_threshold_sensitivity.png"
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)
    chart_paths.append(str(path))

    figure, axis = plt.subplots(figsize=(11, 5))
    axis.bar(monthly["month"], monthly["roi"])
    axis.axhline(0, color="black", linewidth=0.8)
    axis.tick_params(axis="x", rotation=45)
    axis.set(title="Monthly Top1 hindsight ROI", xlabel="Month", ylabel="ROI")
    path = output / "monthly_top1_roi.png"
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)
    chart_paths.append(str(path))

    figure, left = plt.subplots(figsize=(11, 5))
    x = np.arange(len(buckets))
    left.plot(x, buckets["mean_predicted_probability"], marker="o", label="Predicted")
    left.plot(x, buckets["observed_plc_rate"], marker="o", label="Observed")
    left.set_xticks(x, buckets["probability_bucket"], rotation=45)
    left.set(ylabel="Probability / hit rate", xlabel="Probability bucket")
    right = left.twinx()
    right.plot(x, buckets["median_final_place_odds"], color="tab:green", marker="s")
    right.set_ylabel("Median final PLC odds")
    left.legend(loc="upper left")
    path = output / "probability_calibration_and_payout.png"
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)
    chart_paths.append(str(path))
    return chart_paths


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def run_exploratory_betting_backtest(
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    project = paths or ProjectPaths.from_root()
    contract_payload = load_contract(project)
    databases = resolve_experiment_database_paths(paths=project)
    protected = {
        "source_database": databases.source,
        "experiment_database": databases.experiment,
        "sealed_contract": project.root / CONTRACT_PATH,
        "reference_result": project.root / REFERENCE_RESULT,
    }
    before = {name: _sha256_file(path) for name, path in protected.items()}
    if before["source_database"] != contract_payload["protected_assets"][
        "source_database_sha256"
    ]:
        raise ValueError("Source database hash differs from sealed contract")
    if before["experiment_database"] != contract_payload["protected_assets"][
        "experiment_database_sha256"
    ]:
        raise ValueError("Experiment database hash differs from sealed contract")

    predictions, fold_metrics, reproduction = _restore_oof_predictions(
        project, contract_payload
    )
    runner_odds, payouts = _load_payouts(project)
    evaluation, settlement_audit = _join_and_audit_settlement(
        predictions, runner_odds, payouts
    )
    top1 = select_top1(evaluation)
    top1_summary = summarize_bets(top1)
    thresholds = _threshold_summary(top1)
    buckets = _bucket_summary(evaluation)
    edges = _edge_summary(evaluation)
    monthly = _monthly_summary(top1)
    cumulative, rolling, outlier = _risk_tables(top1)
    market = _market_diagnostics(evaluation, top1)

    output = project.root / OUTPUT_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(output / "row_level_oof_predictions.csv", index=False)
    evaluation.to_csv(output / "row_level_oof_predictions_with_payout.csv", index=False)
    top1.to_csv(output / "top1_fixed_bets.csv", index=False)
    thresholds.to_csv(output / "confidence_threshold_summary.csv", index=False)
    buckets.to_csv(output / "probability_bucket_summary.csv", index=False)
    edges.to_csv(output / "retrospective_ev_summary.csv", index=False)
    monthly.to_csv(output / "monthly_strategy_summary.csv", index=False)
    cumulative.to_csv(output / "cumulative_profit.csv", index=False)
    rolling.to_csv(output / "rolling_100_bet_roi.csv", index=False)
    chart_paths = _write_charts(output, cumulative, thresholds, monthly, buckets)

    after = {name: _sha256_file(path) for name, path in protected.items()}
    if before != after:
        raise ValueError("Protected artifact changed")
    result: dict[str, Any] = {
        "experiment_version": EXPERIMENT_VERSION,
        "contract_sha256": before["sealed_contract"],
        "contract": contract_payload,
        "feature_count": 137,
        "feature_hash": contract_payload["upstream_model"]["feature_hash"],
        "oof_restoration": reproduction,
        "fold_metrics": fold_metrics,
        "settlement_audit": settlement_audit,
        "top1_fixed": top1_summary,
        "confidence_thresholds": thresholds.to_dict(orient="records"),
        "probability_buckets": buckets.to_dict(orient="records"),
        "hindsight_edge": edges.to_dict(orient="records"),
        "monthly": monthly.to_dict(orient="records"),
        "outlier_sensitivity": outlier,
        "market_relationship": market,
        "rolling_100_bet_roi": {
            "available_windows": int(rolling["rolling_100_bet_roi"].notna().sum()),
            "min": float(rolling["rolling_100_bet_roi"].min()),
            "median": float(rolling["rolling_100_bet_roi"].median()),
            "max": float(rolling["rolling_100_bet_roi"].max()),
        },
        "charts": chart_paths,
        "validation_access_count": 0,
        "rows_on_or_after_2024_07_01_loaded": 0,
        "post_2025_07_access_count": 0,
        "source_database_modified": False,
        "experiment_database_modified": False,
        "other_worktree_modified": False,
        "protected_sha256": after,
        "interpretation": (
            "Exploratory historical final-payout diagnostic; not deployable ROI "
            "or strategy selection."
        ),
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_exploratory_betting_backtest(), ensure_ascii=False, indent=2))
