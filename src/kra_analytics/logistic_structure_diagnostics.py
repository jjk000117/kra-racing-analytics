from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_FOLDS,
    DEVELOPMENT_START,
    _fold_frames,
    verify_sealed_artifacts,
)
from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.feature_bundle_experiment import _fit_candidate, _load_development_frame
from kra_analytics.improvement_validation_contract import EXPECTED_FEATURE_HASH
from kra_analytics.paths import ProjectPaths

DIAGNOSTIC_VERSION = "post_baseline_v2_logistic_structure_diagnostic_v1"
VALIDATION_ACCESS_LEDGER = (
    "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/"
    "validation_access.json"
)

ONE_DIMENSIONAL_FEATURES = (
    "rating",
    "rating_field_percentile",
    "carried_weight",
    "carried_weight_vs_field_median_kg",
    "horse_prior_plc_hit_rate",
    "horse_recent5_plc_hit_rate",
    "horse_same_distance_plc_hit_rate",
    "jockey_recent10_plc_hit_rate",
    "trainer_recent10_plc_hit_rate",
    "horse_recent5_s1f_median",
    "horse_recent5_g3f_median",
    "horse_recent5_g1f_median",
    "horse_recent5_race_relative_time_advantage_median",
    "horse_recent5_race_time_percentile_median",
)

PAIR_DIAGNOSTICS = (
    ("rating", "rating_field_percentile", "absolute_x_field"),
    (
        "horse_prior_plc_hit_rate",
        "horse_prior_plc_hit_rate_field_percentile",
        "absolute_x_field",
    ),
    (
        "horse_recent5_plc_hit_rate",
        "horse_recent5_plc_hit_rate_field_percentile",
        "absolute_x_field",
    ),
    (
        "horse_recent5_s1f_median",
        "horse_recent5_s1f_field_percentile",
        "absolute_x_field",
    ),
    (
        "horse_recent5_g3f_median",
        "horse_recent5_g3f_field_percentile",
        "absolute_x_field",
    ),
    (
        "horse_recent5_g1f_median",
        "horse_recent5_g1f_field_percentile",
        "absolute_x_field",
    ),
    (
        "jockey_recent10_plc_hit_rate",
        "jockey_recent10_plc_hit_rate_field_percentile",
        "absolute_x_field",
    ),
    (
        "trainer_recent10_plc_hit_rate",
        "trainer_recent10_plc_hit_rate_field_percentile",
        "absolute_x_field",
    ),
    ("horse_prior_plc_hit_rate", "horse_prior_start_count", "rate_x_count"),
    ("horse_recent5_plc_hit_rate", "horse_recent5_start_count", "rate_x_count"),
    (
        "horse_same_distance_plc_hit_rate",
        "horse_same_distance_start_count",
        "rate_x_count",
    ),
    ("jockey_recent10_plc_hit_rate", "jockey_recent10_start_count", "rate_x_count"),
    ("trainer_recent10_plc_hit_rate", "trainer_recent10_start_count", "rate_x_count"),
    ("gate_no", "registered_runner_count", "conditional"),
    ("horse_recent5_s1f_median", "distance_m", "conditional"),
    ("horse_recent5_g3f_median", "distance_m", "conditional"),
    ("horse_recent5_g1f_median", "distance_m", "conditional"),
    ("horse_recent5_g3f_median", "meet_code", "conditional"),
    ("horse_recent5_plc_hit_rate", "horse_prior_plc_hit_rate", "conditional"),
    ("horse_same_distance_plc_hit_rate", "distance_m", "conditional"),
    (
        "horse_recent5_race_time_percentile_median",
        "rating_field_percentile",
        "conditional",
    ),
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_quantile_bin(series: pd.Series, bins: int = 5) -> pd.Series:
    result = pd.Series(pd.NA, index=series.index, dtype="Int64")
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.nunique() < 2:
        return result
    ranked = valid.rank(method="average", pct=True)
    result.loc[valid.index] = np.minimum(np.ceil(ranked * bins), bins).astype(int)
    return result


def _group_summary(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    grouped = frame.groupby(groups, observed=True, dropna=False)
    result = grouped.agg(
        rows=("target", "size"),
        races=("race_id", "nunique"),
        actual_rate=("target", "mean"),
        predicted_mean=("prediction", "mean"),
        mean_residual=("residual", "mean"),
        mean_brier=("squared_error", "mean"),
    ).reset_index()
    return result


def _one_dimensional(oof: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for feature in ONE_DIMENSIONAL_FEATURES:
        work = oof.loc[oof[feature].notna()].copy()
        work["bin"] = work.groupby("fold_id", observed=True)[feature].transform(
            _safe_quantile_bin
        )
        work = work.loc[work["bin"].notna()]
        if work.empty:
            continue
        summary = _group_summary(work, ["fold_id", "bin"])
        values = work.groupby(["fold_id", "bin"], observed=True)[feature].agg(
            feature_min="min", feature_median="median", feature_max="max"
        ).reset_index()
        summary = summary.merge(values, on=["fold_id", "bin"], validate="one_to_one")
        summary.insert(0, "feature", feature)
        rows.append(summary)
    return pd.concat(rows, ignore_index=True)


def _two_dimensional(oof: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for left, right, family in PAIR_DIAGNOSTICS:
        work = oof.loc[oof[left].notna() & oof[right].notna()].copy()
        work["left_bin"] = work.groupby("fold_id", observed=True)[left].transform(
            lambda value: _safe_quantile_bin(value, bins=3)
        )
        if right in {"meet_code"}:
            work["right_bin"] = work[right].astype("Int64")
        elif right in {"distance_m", "registered_runner_count"}:
            work["right_bin"] = work.groupby("fold_id", observed=True)[right].transform(
                lambda value: _safe_quantile_bin(value, bins=3)
            )
        else:
            work["right_bin"] = work.groupby("fold_id", observed=True)[right].transform(
                lambda value: _safe_quantile_bin(value, bins=3)
            )
        work = work.loc[work["left_bin"].notna() & work["right_bin"].notna()]
        summary = _group_summary(work, ["fold_id", "left_bin", "right_bin"])
        left_marginal = work.groupby(["fold_id", "left_bin"], observed=True)[
            "residual"
        ].mean()
        right_marginal = work.groupby(["fold_id", "right_bin"], observed=True)[
            "residual"
        ].mean()
        fold_mean = work.groupby("fold_id", observed=True)["residual"].mean()
        summary["additive_expected_residual"] = [
            float(left_marginal.loc[(row.fold_id, row.left_bin)])
            + float(right_marginal.loc[(row.fold_id, row.right_bin)])
            - float(fold_mean.loc[row.fold_id])
            for row in summary.itertuples(index=False)
        ]
        summary["interaction_residual"] = (
            summary["mean_residual"] - summary["additive_expected_residual"]
        )
        summary.insert(0, "pair_family", family)
        summary.insert(1, "left_feature", left)
        summary.insert(2, "right_feature", right)
        rows.append(summary)
    return pd.concat(rows, ignore_index=True)


def _race_structure(oof: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = oof.copy()
    work["within_race_rank"] = work.groupby("race_id")["prediction"].rank(
        method="average", ascending=False
    )
    work["within_race_percentile"] = work.groupby("race_id")["prediction"].rank(
        method="average", pct=True, ascending=True
    )
    work["rank_group"] = pd.cut(
        work["within_race_percentile"],
        bins=[0.0, 0.25, 0.5, 0.75, 1.0],
        labels=["bottom", "lower_middle", "upper_middle", "top"],
        include_lowest=True,
    )
    rank_summary = _group_summary(work, ["fold_id", "rank_group"])

    races = work.groupby(["fold_id", "race_id"], observed=True).agg(
        registered_runner_count=("registered_runner_count", "first"),
        predicted_probability_sum=("prediction", "sum"),
        actual_place_hits=("target", "sum"),
        probability_gap=("prediction", lambda value: float(value.max() - value.min())),
        race_brier=("squared_error", "mean"),
        race_mean_residual=("residual", "mean"),
    ).reset_index()
    races["probability_gap_bin"] = races.groupby("fold_id", observed=True)[
        "probability_gap"
    ].transform(lambda value: _safe_quantile_bin(value, bins=4))
    runner_summary = races.groupby(
        ["fold_id", "registered_runner_count"], observed=True
    ).agg(
        races=("race_id", "size"),
        predicted_sum_mean=("predicted_probability_sum", "mean"),
        predicted_sum_median=("predicted_probability_sum", "median"),
        actual_hits_mean=("actual_place_hits", "mean"),
        actual_hits_median=("actual_place_hits", "median"),
        race_brier_mean=("race_brier", "mean"),
        race_mean_residual=("race_mean_residual", "mean"),
    ).reset_index()
    gap_summary = races.groupby(["fold_id", "probability_gap_bin"], observed=True).agg(
        races=("race_id", "size"),
        probability_gap_median=("probability_gap", "median"),
        predicted_sum_mean=("predicted_probability_sum", "mean"),
        actual_hits_mean=("actual_place_hits", "mean"),
        race_brier_mean=("race_brier", "mean"),
        race_mean_residual=("race_mean_residual", "mean"),
    ).reset_index()
    return races, rank_summary, pd.concat(
        [
            runner_summary.assign(summary_type="runner_count"),
            gap_summary.assign(summary_type="probability_gap"),
        ],
        ignore_index=True,
    )


def _pattern_summary(one_d: pd.DataFrame, two_d: pd.DataFrame) -> dict[str, Any]:
    one_rows: list[dict[str, Any]] = []
    for feature, group in one_d.groupby("feature", observed=True):
        fold_ranges = []
        fold_directions = []
        for _, fold in group.groupby("fold_id", observed=True):
            ordered = fold.sort_values("bin")
            fold_ranges.append(
                float(ordered["mean_residual"].max() - ordered["mean_residual"].min())
            )
            fold_directions.append(
                int(
                    np.sign(
                        float(
                            ordered.iloc[-1]["mean_residual"]
                            - ordered.iloc[0]["mean_residual"]
                        )
                    )
                )
            )
        nonzero = [value for value in fold_directions if value != 0]
        repeated = max(nonzero.count(1), nonzero.count(-1)) if nonzero else 0
        pivot = group.pivot(index="bin", columns="fold_id", values="mean_residual")
        correlation_matrix = pivot.corr().to_numpy()
        fold_shape_correlations = correlation_matrix[
            np.triu_indices(correlation_matrix.shape[0], k=1)
        ]
        one_rows.append(
            {
                "feature": feature,
                "median_within_fold_residual_range": float(np.median(fold_ranges)),
                "same_direction_folds": repeated,
                "direction_signs": fold_directions,
                "median_fold_shape_correlation": float(
                    np.nanmedian(fold_shape_correlations)
                ),
            }
        )

    pair_rows: list[dict[str, Any]] = []
    keys = ["pair_family", "left_feature", "right_feature"]
    for values, group in two_d.groupby(keys, observed=True):
        fold_spreads = []
        for _, fold in group.groupby("fold_id", observed=True):
            eligible = fold.loc[fold["rows"] >= 100]
            if not eligible.empty:
                fold_spreads.append(
                    float(
                        eligible["interaction_residual"].max()
                        - eligible["interaction_residual"].min()
                    )
                )
        pivot = group.loc[group["rows"] >= 100].pivot_table(
            index=["left_bin", "right_bin"],
            columns="fold_id",
            values="interaction_residual",
            observed=True,
        )
        correlation_matrix = pivot.corr(min_periods=3).to_numpy()
        correlations = correlation_matrix[
            np.triu_indices(correlation_matrix.shape[0], k=1)
        ]
        common = pivot.dropna()
        same_sign_cells = int(
            (
                (common.gt(0).all(axis=1))
                | (common.lt(0).all(axis=1))
            ).sum()
        )
        pair_rows.append(
            {
                **dict(zip(keys, values, strict=True)),
                "folds_with_cells_ge_100": len(fold_spreads),
                "median_interaction_residual_spread": (
                    float(np.median(fold_spreads)) if fold_spreads else None
                ),
                "median_fold_pattern_correlation": (
                    float(np.nanmedian(correlations))
                    if np.isfinite(correlations).any()
                    else None
                ),
                "common_cells_all_four_folds": len(common),
                "same_sign_common_cells": same_sign_cells,
            }
        )
    return {"one_dimensional": one_rows, "two_dimensional": pair_rows}


def run_logistic_structure_diagnostic(
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contracts = _combined_contract(project_paths)
    contract = contracts["F1+F3"]
    if len(contract.inputs) != 133 or contract.feature_hash != EXPECTED_FEATURE_HASH:
        raise ValueError("Promoted 133-Feature contract mismatch")

    frame = _load_development_frame(project_paths, contracts)
    if frame["race_date"].max() >= DEVELOPMENT_END_EXCLUSIVE:
        raise ValueError("Development diagnostic crossed the Validation boundary")

    protection = json.loads(
        (project_paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    sealed_before = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_paths = {
        "validation_result": project_paths.root
        / "docs/post-baseline-v2-f1-f3-one-time-validation-result.md",
        "validation_contract": project_paths.root
        / "docs/post-baseline-v2-improvement-validation-contract.json",
        "validation_access": project_paths.root / VALIDATION_ACCESS_LEDGER,
    }
    protected_before = {name: _sha256_file(path) for name, path in protected_paths.items()}
    access_before = json.loads(protected_paths["validation_access"].read_text(encoding="utf-8"))
    if access_before.get("access_count") != 1:
        raise ValueError("Validation access count is not the expected consumed value of 1")

    oof_parts: list[pd.DataFrame] = []
    fold_context: list[dict[str, Any]] = []
    warning_messages: set[str] = set()
    for spec in DEVELOPMENT_FOLDS:
        train, evaluation = _fold_frames(frame, spec)
        metrics, probabilities, fit_seconds, warnings = _fit_candidate(
            train=train, evaluation=evaluation, contract=contract
        )
        warning_messages.update(warnings)
        part = evaluation.copy()
        part["fold_id"] = spec.fold_id
        part["prediction"] = probabilities
        part["target"] = part["place_hit"].astype(int)
        part["residual"] = part["target"] - part["prediction"]
        part["squared_error"] = part["residual"] ** 2
        oof_parts.append(part)
        fold_context.append(
            {
                "fold_id": spec.fold_id,
                "train_start": str(train["race_date"].min()),
                "train_end": str(train["race_date"].max()),
                "evaluation_start": str(evaluation["race_date"].min()),
                "evaluation_end": str(evaluation["race_date"].max()),
                "train_rows": len(train),
                "train_races": int(train["race_id"].nunique()),
                "evaluation_rows": len(evaluation),
                "evaluation_races": int(evaluation["race_id"].nunique()),
                "strict_temporal_ordering": bool(
                    train["race_date"].max() < evaluation["race_date"].min()
                ),
                "preprocessing_fit_scope": "fold_train_only",
                "fit_seconds": fit_seconds,
                "warning_count": len(warnings),
                "metrics": metrics,
            }
        )
    oof = pd.concat(oof_parts, ignore_index=True)
    if oof.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("OOF evaluation rows overlap across folds")

    one_d = _one_dimensional(oof)
    two_d = _two_dimensional(oof)
    race_level, race_rank, race_summaries = _race_structure(oof)
    patterns = _pattern_summary(one_d, two_d)
    gap_rows = race_summaries.loc[race_summaries["summary_type"] == "probability_gap"]
    gap_contrasts: list[dict[str, Any]] = []
    for fold_id, fold in gap_rows.groupby("fold_id", observed=True):
        ordered = fold.sort_values("probability_gap_bin")
        low = ordered.iloc[0]
        high = ordered.iloc[-1]
        gap_contrasts.append(
            {
                "fold_id": fold_id,
                "low_gap_races": int(low["races"]),
                "high_gap_races": int(high["races"]),
                "low_minus_high_race_brier": float(
                    low["race_brier_mean"] - high["race_brier_mean"]
                ),
                "low_gap_mean_residual": float(low["race_mean_residual"]),
                "high_gap_mean_residual": float(high["race_mean_residual"]),
                "low_minus_high_predicted_sum": float(
                    low["predicted_sum_mean"] - high["predicted_sum_mean"]
                ),
            }
        )

    sealed_after = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_after = {name: _sha256_file(path) for name, path in protected_paths.items()}
    access_after = json.loads(protected_paths["validation_access"].read_text(encoding="utf-8"))
    if sealed_before != sealed_after or protected_before != protected_after:
        raise ValueError("A protected baseline or Validation artifact changed")
    if access_after.get("access_count") != 1:
        raise ValueError("Validation access count changed during development diagnostic")

    output = project_paths.exports / f"modeling/{DIAGNOSTIC_VERSION}"
    output.mkdir(parents=True, exist_ok=True)
    one_d.to_csv(output / "one_dimensional_residual_bins.csv", index=False)
    two_d.to_csv(output / "two_dimensional_residual_cells.csv", index=False)
    race_level.to_csv(output / "race_level_competition_structure.csv", index=False)
    race_rank.to_csv(output / "within_race_rank_calibration.csv", index=False)
    race_summaries.to_csv(output / "race_structure_summaries.csv", index=False)
    pd.DataFrame(gap_contrasts).to_csv(output / "race_gap_contrasts.csv", index=False)
    pd.DataFrame(patterns["one_dimensional"]).to_csv(
        output / "one_dimensional_pattern_summary.csv", index=False
    )
    pd.DataFrame(patterns["two_dimensional"]).to_csv(
        output / "two_dimensional_pattern_summary.csv", index=False
    )

    result = {
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "development_window": [str(DEVELOPMENT_START), "2024-06-30"],
        "development_rows": len(frame),
        "development_races": int(frame["race_id"].nunique()),
        "oof_diagnostic_rows": len(oof),
        "oof_diagnostic_races": int(oof["race_id"].nunique()),
        "feature_count": len(contract.inputs),
        "feature_hash": contract.feature_hash,
        "probability_procedure": "raw fold-specific Logistic probability",
        "fold_context": fold_context,
        "pattern_summary": patterns,
        "race_gap_contrasts": gap_contrasts,
        "fit_warning_messages": sorted(warning_messages),
        "validation_access_count_before": 1,
        "validation_access_count_after": 1,
        "validation_or_later_rows_loaded": False,
        "max_loaded_race_date": str(frame["race_date"].max()),
        "sealed_artifacts_unchanged": True,
        "protected_validation_artifacts_unchanged": True,
        "sealed_artifact_hashes": sealed_after,
        "protected_validation_hashes": protected_after,
        "output_files": [
            "one_dimensional_residual_bins.csv",
            "two_dimensional_residual_cells.csv",
            "race_level_competition_structure.csv",
            "within_race_rank_calibration.csv",
            "race_structure_summaries.csv",
            "race_gap_contrasts.csv",
            "one_dimensional_pattern_summary.csv",
            "two_dimensional_pattern_summary.csv",
        ],
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
