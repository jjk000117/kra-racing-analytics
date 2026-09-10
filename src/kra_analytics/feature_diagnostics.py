from __future__ import annotations

import hashlib
import json
import math
import time
import warnings
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS, _fold_frames
from kra_analytics.experiment_database import resolve_experiment_database_paths
from kra_analytics.feature_bundles import F1_FEATURES, F3_FEATURES
from kra_analytics.modeling_v2 import V2FeatureContract, build_v2_pipeline
from kra_analytics.paths import ProjectPaths
from kra_analytics.relative_experiment import _contracts, _load_frame
from kra_analytics.relative_features import RELATIVE_FEATURES, SOURCE_BY_FEATURE
from kra_analytics.trend_features import TREND_FEATURES

DIAGNOSTIC_VERSION = "plc_final_feature_diagnostic_v1"
EXPECTED_FEATURE_COUNT = 144
EXPECTED_FEATURE_HASH = "7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a"
DOMINANT_THRESHOLD = 0.99
RARE_THRESHOLD = 0.01
HIGH_PEARSON = 0.80
HIGH_SPEARMAN = 0.80
CLUSTER_SPEARMAN = 0.90


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def numeric_profile(frame: pd.DataFrame, features: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    quantiles = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)
    for feature in features:
        values = pd.to_numeric(frame[feature], errors="coerce")
        valid = values.dropna()
        counts = valid.value_counts(dropna=False)
        dominant_rate = float(counts.iloc[0] / len(valid)) if len(valid) else math.nan
        summary = valid.quantile(quantiles) if len(valid) else pd.Series(dtype=float)
        rows.append(
            {
                "feature_name": feature,
                "row_count": len(frame),
                "non_null_count": int(valid.size),
                "missing_count": int(values.isna().sum()),
                "missing_rate": float(values.isna().mean()),
                "zero_count": int((valid == 0).sum()),
                "zero_rate_non_null": float((valid == 0).mean()) if len(valid) else math.nan,
                "unique_count": int(valid.nunique()),
                "mean": float(valid.mean()) if len(valid) else math.nan,
                "std": float(valid.std(ddof=0)) if len(valid) else math.nan,
                "min": float(valid.min()) if len(valid) else math.nan,
                "p01": float(summary.get(0.01, math.nan)),
                "p05": float(summary.get(0.05, math.nan)),
                "p25": float(summary.get(0.25, math.nan)),
                "median": float(summary.get(0.50, math.nan)),
                "p75": float(summary.get(0.75, math.nan)),
                "p95": float(summary.get(0.95, math.nan)),
                "p99": float(summary.get(0.99, math.nan)),
                "max": float(valid.max()) if len(valid) else math.nan,
                "dominant_value_rate_non_null": dominant_rate,
                "constant_flag": bool(valid.nunique() <= 1),
                "near_constant_99pct_flag": bool(dominant_rate >= DOMINANT_THRESHOLD),
            }
        )
    return pd.DataFrame(rows)


def categorical_profile(frame: pd.DataFrame, features: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for feature in features:
        values = frame[feature]
        valid = values.dropna().astype(str)
        counts = valid.value_counts()
        dominant_rate = float(counts.iloc[0] / len(valid)) if len(valid) else math.nan
        rare = counts[counts / max(len(valid), 1) < RARE_THRESHOLD]
        rows.append(
            {
                "feature_name": feature,
                "row_count": len(frame),
                "non_null_count": int(valid.size),
                "missing_count": int(values.isna().sum()),
                "missing_rate": float(values.isna().mean()),
                "unique_count": int(valid.nunique()),
                "dominant_value": str(counts.index[0]) if len(counts) else "",
                "dominant_value_rate_non_null": dominant_rate,
                "rare_category_count_lt_1pct": int(len(rare)),
                "rare_row_rate_lt_1pct": float(rare.sum() / len(valid)) if len(valid) else math.nan,
                "top_categories_json": json.dumps(
                    {str(key): int(value) for key, value in counts.head(10).items()},
                    ensure_ascii=False,
                ),
                "single_category_flag": bool(valid.nunique() <= 1),
                "dominant_99pct_flag": bool(dominant_rate >= DOMINANT_THRESHOLD),
            }
        )
    return pd.DataFrame(rows)


def high_correlation_pairs(
    pearson: pd.DataFrame, spearman: pd.DataFrame, min_abs: float = 0.80
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    columns = list(pearson.columns)
    for left_index, left in enumerate(columns):
        for right in columns[left_index + 1 :]:
            p_value = float(cast(float, pearson.at[left, right]))
            s_value = float(cast(float, spearman.at[left, right]))
            if max(abs(p_value), abs(s_value)) >= min_abs:
                rows.append(
                    {
                        "feature_left": left,
                        "feature_right": right,
                        "pearson": p_value,
                        "spearman": s_value,
                        "abs_pearson_ge_0_8": abs(p_value) >= HIGH_PEARSON,
                        "abs_spearman_ge_0_8": abs(s_value) >= HIGH_SPEARMAN,
                        "abs_spearman_ge_0_9": abs(s_value) >= CLUSTER_SPEARMAN,
                    }
                )
    return pd.DataFrame(rows).sort_values(
        ["abs_spearman_ge_0_9", "spearman"], ascending=[False, False]
    ) if rows else pd.DataFrame(columns=["feature_left", "feature_right", "pearson", "spearman"])


def correlation_components(pairs: pd.DataFrame, threshold: float = 0.90) -> pd.DataFrame:
    graph: dict[str, set[str]] = defaultdict(set)
    if not pairs.empty:
        for row in pairs.itertuples(index=False):
            if abs(float(cast(float, row.spearman))) >= threshold:
                graph[str(row.feature_left)].add(str(row.feature_right))
                graph[str(row.feature_right)].add(str(row.feature_left))
    rows: list[dict[str, Any]] = []
    visited: set[str] = set()
    component_id = 0
    for start in sorted(graph):
        if start in visited:
            continue
        component_id += 1
        queue = deque([start])
        members: list[str] = []
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            members.append(node)
            queue.extend(sorted(graph[node] - visited))
        for member in sorted(members):
            rows.append(
                {
                    "component_id": component_id,
                    "feature_name": member,
                    "component_size": len(members),
                    "abs_spearman_threshold": threshold,
                }
            )
    return pd.DataFrame(rows)


def corrected_cramers_v(left: pd.Series, right: pd.Series) -> tuple[float, int]:
    valid = left.notna() & right.notna()
    table = pd.crosstab(left[valid].astype(str), right[valid].astype(str))
    n = int(table.to_numpy().sum())
    if n <= 1 or min(table.shape) <= 1:
        return 0.0, n
    observed = table.to_numpy(dtype=float)
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / n
    chi2 = float(np.where(expected > 0, (observed - expected) ** 2 / expected, 0).sum())
    phi2 = chi2 / n
    rows, columns = table.shape
    phi2_corrected = max(0.0, phi2 - ((columns - 1) * (rows - 1)) / (n - 1))
    rows_corrected = rows - ((rows - 1) ** 2) / (n - 1)
    columns_corrected = columns - ((columns - 1) ** 2) / (n - 1)
    denominator = min(columns_corrected - 1, rows_corrected - 1)
    return (math.sqrt(phi2_corrected / denominator) if denominator > 0 else 0.0), n


def categorical_associations(frame: pd.DataFrame, features: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, left in enumerate(features):
        for right in features[index + 1 :]:
            value, observations = corrected_cramers_v(frame[left], frame[right])
            valid = frame[[left, right]].dropna().astype(str)
            left_to_right = int(valid.groupby(left)[right].nunique().max()) <= 1
            right_to_left = int(valid.groupby(right)[left].nunique().max()) <= 1
            rows.append(
                {
                    "feature_left": left,
                    "feature_right": right,
                    "corrected_cramers_v": value,
                    "complete_observations": observations,
                    "strong_ge_0_8_flag": value >= 0.80,
                    "left_determines_right": left_to_right,
                    "right_determines_left": right_to_left,
                    "one_to_one_observed_flag": left_to_right and right_to_left,
                }
            )
    return pd.DataFrame(rows).sort_values("corrected_cramers_v", ascending=False)


def numeric_categorical_summary(frame: pd.DataFrame) -> pd.DataFrame:
    combinations = {
        "race_grade": (
            "rating",
            "carried_weight",
            "registered_runner_count",
            "horse_prior_plc_hit_rate",
            "horse_recent5_plc_hit_rate",
            "horse_same_distance_plc_hit_rate",
        ),
        "meet_code": (
            "rating",
            "horse_recent5_s1f_median",
            "horse_recent5_g3f_median",
            "horse_recent5_g1f_median",
        ),
    }
    rows: list[dict[str, Any]] = []
    for category, features in combinations.items():
        for feature in features:
            for group, values in frame.groupby(category, dropna=False)[feature]:
                numeric = pd.to_numeric(values, errors="coerce").dropna()
                rows.append(
                    {
                        "category_feature": category,
                        "category_value": str(group),
                        "numeric_feature": feature,
                        "row_count": int(len(values)),
                        "non_null_count": int(len(numeric)),
                        "mean": float(numeric.mean()) if len(numeric) else math.nan,
                        "std": float(numeric.std(ddof=0)) if len(numeric) else math.nan,
                        "p25": float(numeric.quantile(0.25)) if len(numeric) else math.nan,
                        "median": float(numeric.median()) if len(numeric) else math.nan,
                        "p75": float(numeric.quantile(0.75)) if len(numeric) else math.nan,
                    }
                )
    return pd.DataFrame(rows)


def _special_pairs(contract: V2FeatureContract) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = [
        ("rating", "rating_field_percentile", "absolute_vs_field_relative"),
        (
            "carried_weight",
            "carried_weight_vs_field_median_kg",
            "absolute_vs_field_relative",
        ),
        (
            "horse_prior_plc_hit_rate",
            "horse_prior_plc_hit_rate_field_percentile",
            "absolute_vs_field_relative",
        ),
        (
            "horse_recent5_plc_hit_rate",
            "horse_recent5_plc_hit_rate_field_percentile",
            "absolute_vs_field_relative",
        ),
        (
            "horse_same_distance_plc_hit_rate",
            "horse_same_distance_plc_hit_rate_field_percentile",
            "absolute_vs_field_relative",
        ),
        (
            "jockey_recent10_plc_hit_rate",
            "jockey_recent10_plc_hit_rate_field_percentile",
            "absolute_vs_field_relative",
        ),
        (
            "trainer_recent10_plc_hit_rate",
            "trainer_recent10_plc_hit_rate_field_percentile",
            "absolute_vs_field_relative",
        ),
        (
            "horse_recent5_s1f_median",
            "horse_recent5_s1f_field_percentile",
            "absolute_vs_field_relative",
        ),
        (
            "horse_recent5_g3f_median",
            "horse_recent5_g3f_field_percentile",
            "absolute_vs_field_relative",
        ),
        (
            "horse_recent5_g1f_median",
            "horse_recent5_g1f_field_percentile",
            "absolute_vs_field_relative",
        ),
        ("horse_prior_plc_hit_rate", "horse_recent5_plc_hit_rate", "prior_vs_recent"),
        ("horse_recent3_finish_rate", "horse_recent5_finish_rate", "recent3_vs_recent5"),
        ("horse_recent3_win_rate", "horse_recent5_win_rate", "recent3_vs_recent5"),
        ("horse_recent3_top3_rate", "horse_recent5_top3_rate", "recent3_vs_recent5"),
        ("horse_recent3_avg_rating", "horse_recent5_avg_rating", "recent3_vs_recent5"),
        ("horse_recent3_plc_hit_rate", "horse_recent5_plc_hit_rate", "recent3_vs_recent5"),
        ("horse_recent3_s1f_median", "horse_recent5_s1f_median", "recent3_vs_recent5"),
        ("horse_recent3_g3f_median", "horse_recent5_g3f_median", "recent3_vs_recent5"),
        ("horse_recent3_g1f_median", "horse_recent5_g1f_median", "recent3_vs_recent5"),
        (
            "horse_recent3_race_relative_time_advantage_median",
            "horse_recent5_race_relative_time_advantage_median",
            "recent3_vs_recent5",
        ),
        (
            "horse_recent3_race_time_percentile_median",
            "horse_recent5_race_time_percentile_median",
            "recent3_vs_recent5",
        ),
        ("horse_prior_start_count", "horse_prior_plc_hit_rate", "count_vs_rate"),
        ("horse_recent5_start_count", "horse_recent5_plc_hit_rate", "count_vs_rate"),
        ("horse_same_distance_start_count", "horse_same_distance_plc_hit_rate", "count_vs_rate"),
        ("jockey_prior_start_count", "jockey_prior_plc_hit_rate", "count_vs_rate"),
        ("trainer_prior_start_count", "trainer_prior_plc_hit_rate", "count_vs_rate"),
        (
            "horse_recent5_race_time_percentile_median",
            "horse_recent5_race_time_percentile_trend_per_start",
            "trend_vs_level",
        ),
        (
            "horse_recent5_s1f_median",
            "horse_recent5_s1f_improvement_trend_seconds_per_start",
            "trend_vs_level",
        ),
        (
            "horse_recent5_g3f_median",
            "horse_recent5_g3f_improvement_trend_seconds_per_start",
            "trend_vs_level",
        ),
        (
            "horse_recent5_g1f_median",
            "horse_recent5_g1f_improvement_trend_seconds_per_start",
            "trend_vs_level",
        ),
    ]
    candidates.extend(
        (source, feature, "r1_absolute_vs_field_relative")
        for feature, source in SOURCE_BY_FEATURE.items()
    )
    available = set(contract.inputs)
    return [item for item in candidates if item[0] in available and item[1] in available]


def special_family_diagnostic(frame: pd.DataFrame, contract: V2FeatureContract) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for left, right, family in _special_pairs(contract):
        valid = frame[[left, right]].dropna()
        rows.append(
            {
                "family": family,
                "feature_left": left,
                "feature_right": right,
                "complete_observations": len(valid),
                "overlap_rate": float(len(valid) / len(frame)),
                "pearson": (
                    float(valid[left].corr(valid[right], method="pearson"))
                    if len(valid) > 1
                    else math.nan
                ),
                "spearman": (
                    float(valid[left].corr(valid[right], method="spearman"))
                    if len(valid) > 1
                    else math.nan
                ),
                "left_only_rate": float((frame[left].notna() & frame[right].isna()).mean()),
                "right_only_rate": float((frame[left].isna() & frame[right].notna()).mean()),
            }
        )
    return pd.DataFrame(rows)


def _coefficient_rows(
    frame: pd.DataFrame, contract: V2FeatureContract
) -> tuple[pd.DataFrame, pd.DataFrame]:
    numeric_rows: list[dict[str, Any]] = []
    categorical_rows: list[dict[str, Any]] = []
    for fold in DEVELOPMENT_FOLDS:
        train, _ = _fold_frames(frame, fold)
        pipeline = build_v2_pipeline(contract)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pipeline.fit(train[list(contract.inputs)], train["place_hit"].astype(int))
        preprocessor = pipeline.named_steps["preprocessor"]
        names = preprocessor.get_feature_names_out()
        coefficients = pipeline.named_steps["model"].coef_[0]
        mapping = dict(zip(names, coefficients, strict=True))
        for feature in contract.numeric:
            prefix = "zero_count" if feature in contract.zero_count else "numeric"
            value = float(mapping[f"{prefix}__{feature}"])
            numeric_rows.append(
                {
                    "fold_id": fold.fold_id,
                    "feature_name": feature,
                    "standardized_coefficient": value,
                    "sign": "positive" if value > 0 else "negative" if value < 0 else "zero",
                }
            )
        for name, value in mapping.items():
            if name.startswith("categorical__"):
                categorical_rows.append(
                    {
                        "fold_id": fold.fold_id,
                        "encoded_feature_name": name.removeprefix("categorical__"),
                        "coefficient": float(value),
                    }
                )
    return pd.DataFrame(numeric_rows), pd.DataFrame(categorical_rows)


def coefficient_summary(rows: pd.DataFrame) -> pd.DataFrame:
    grouped = rows.groupby("feature_name")["standardized_coefficient"]
    summary = grouped.agg(["mean", "std", "min", "max"]).reset_index()
    sign_counts = rows.assign(
        positive=rows["standardized_coefficient"] > 0,
        negative=rows["standardized_coefficient"] < 0,
    ).groupby("feature_name")[["positive", "negative"]].sum().reset_index()
    result = summary.merge(sign_counts, on="feature_name")
    result["sign_consistent_4_of_4"] = (result["positive"] == 4) | (result["negative"] == 4)
    result["mean_abs_coefficient"] = result["mean"].abs()
    return result.sort_values("mean_abs_coefficient", ascending=False)


def categorical_coefficient_summary(
    rows: pd.DataFrame, categorical: tuple[str, ...]
) -> pd.DataFrame:
    mapped = rows.copy()
    mapped["feature_name"] = mapped["encoded_feature_name"].map(
        lambda value: next(
            feature for feature in categorical if str(value).startswith(f"{feature}_")
        )
    )
    by_fold = (
        mapped.assign(squared=mapped["coefficient"] ** 2, absolute=mapped["coefficient"].abs())
        .groupby(["fold_id", "feature_name"])
        .agg(
            encoded_category_count=("coefficient", "size"),
            coefficient_l2=("squared", lambda values: float(np.sqrt(values.sum()))),
            maximum_abs_coefficient=("absolute", "max"),
        )
        .reset_index()
    )
    return (
        by_fold.groupby("feature_name")
        .agg(
            encoded_category_count_min=("encoded_category_count", "min"),
            encoded_category_count_max=("encoded_category_count", "max"),
            coefficient_l2_mean=("coefficient_l2", "mean"),
            coefficient_l2_std=("coefficient_l2", "std"),
            maximum_abs_coefficient_across_folds=("maximum_abs_coefficient", "max"),
        )
        .reset_index()
        .sort_values("coefficient_l2_mean", ascending=False)
    )


def exact_numeric_pairs(frame: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pair in pairs.itertuples(index=False):
        left = str(pair.feature_left)
        right = str(pair.feature_right)
        left_values = pd.to_numeric(frame[left], errors="coerce")
        right_values = pd.to_numeric(frame[right], errors="coerce")
        exact = bool(
            (
                (left_values == right_values)
                | (left_values.isna() & right_values.isna())
            ).all()
        )
        if exact or math.isclose(abs(float(cast(float, pair.pearson))), 1.0, abs_tol=1e-12):
            rows.append(
                {
                    "feature_left": left,
                    "feature_right": right,
                    "pearson": float(cast(float, pair.pearson)),
                    "spearman": float(cast(float, pair.spearman)),
                    "exact_value_and_null_pattern": exact,
                    "perfect_linear_relationship": math.isclose(
                        abs(float(cast(float, pair.pearson))), 1.0, abs_tol=1e-12
                    ),
                }
            )
    return pd.DataFrame(rows)


def _write_chart_data(frame: pd.DataFrame, output: Path) -> None:
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    output.mkdir(parents=True, exist_ok=True)
    grades = sorted(frame["race_grade"].dropna().astype(str).unique())
    rating_groups = [
        pd.to_numeric(
            frame.loc[frame["race_grade"].astype(str) == grade, "rating"],
            errors="coerce",
        ).dropna()
        for grade in grades
    ]
    figure, axis = plt.subplots(figsize=(12, 6))
    axis.boxplot(rating_groups, tick_labels=grades, showfliers=False)
    axis.set(
        title="Development rating distribution by race grade",
        xlabel="race_grade",
        ylabel="rating",
    )
    axis.tick_params(axis="x", rotation=45)
    figure.tight_layout()
    figure.savefig(output / "rating_by_race_grade.png", dpi=160)
    plt.close(figure)


def _write_heatmap(spearman: pd.DataFrame, pairs: pd.DataFrame, output: Path) -> list[str]:
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    if pairs.empty:
        return []
    output.mkdir(parents=True, exist_ok=True)
    frequency = pd.concat([pairs["feature_left"], pairs["feature_right"]]).value_counts()
    selected = list(frequency.head(24).index)
    matrix = spearman.loc[selected, selected]
    figure, axis = plt.subplots(figsize=(15, 13))
    image = axis.imshow(matrix, vmin=-1, vmax=1, cmap="coolwarm")
    axis.set_xticks(range(len(selected)), selected, rotation=90, fontsize=7)
    axis.set_yticks(range(len(selected)), selected, fontsize=7)
    figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04, label="Spearman correlation")
    axis.set_title("High-correlation feature subset (top 24 by pair frequency)")
    figure.tight_layout()
    figure.savefig(output / "high_correlation_spearman_heatmap.png", dpi=180)
    plt.close(figure)
    return selected


def run_feature_diagnostic(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project = paths or ProjectPaths.from_root()
    databases = resolve_experiment_database_paths(paths=project)
    contract = _contracts(project)["LR1"]
    if (
        len(contract.inputs) != EXPECTED_FEATURE_COUNT
        or contract.feature_hash != EXPECTED_FEATURE_HASH
    ):
        raise ValueError("LR1 contract count/hash mismatch")
    protected_before = {
        "source_database": _file_sha256(databases.source),
        "experiment_database": _file_sha256(databases.experiment),
    }
    frame = _load_frame(project, contract)
    if frame["race_date"].max().isoformat() >= "2024-07-01":
        raise ValueError("Development boundary violation")
    output = project.exports / f"diagnostics/{DIAGNOSTIC_VERSION}"
    charts = project.root / "docs/assets/plc-final-feature-diagnostic"
    output.mkdir(parents=True, exist_ok=True)
    numeric = numeric_profile(frame, contract.numeric)
    categorical = categorical_profile(frame, contract.categorical)
    numeric_values = frame[list(contract.numeric)].apply(pd.to_numeric, errors="coerce")
    pearson = numeric_values.corr(method="pearson", min_periods=30)
    spearman = numeric_values.corr(method="spearman", min_periods=30)
    pairs = high_correlation_pairs(pearson, spearman)
    exact_pairs = exact_numeric_pairs(numeric_values, pairs)
    components = correlation_components(pairs)
    associations = categorical_associations(frame, contract.categorical)
    group_summary = numeric_categorical_summary(frame)
    special = special_family_diagnostic(frame, contract)
    started = time.perf_counter()
    coefficients, categorical_coefficients = _coefficient_rows(frame, contract)
    coefficient_stability = coefficient_summary(coefficients)
    categorical_coefficient_stability = categorical_coefficient_summary(
        categorical_coefficients, contract.categorical
    )
    fit_seconds = time.perf_counter() - started
    selected_heatmap = _write_heatmap(spearman, pairs, charts)
    _write_chart_data(frame, charts)
    feature_contract = pd.DataFrame(
        [
            {
                "position": index,
                "feature_name": feature,
                "feature_type": "categorical" if feature in contract.categorical else "numeric",
                "bundle": (
                    "F1"
                    if feature in F1_FEATURES
                    else "F3"
                    if feature in F3_FEATURES
                    else "T1"
                    if feature in TREND_FEATURES
                    else "R1"
                    if feature in RELATIVE_FEATURES
                    else "baseline_v2_117"
                ),
            }
            for index, feature in enumerate(contract.inputs, start=1)
        ]
    )
    artifacts: dict[str, pd.DataFrame] = {
        "feature_contract.csv": feature_contract,
        "numeric_profile.csv": numeric,
        "categorical_profile.csv": categorical,
        "pearson_matrix.csv": pearson.reset_index(names="feature_name"),
        "spearman_matrix.csv": spearman.reset_index(names="feature_name"),
        "high_correlation_pairs.csv": pairs,
        "exact_or_perfect_linear_numeric_pairs.csv": exact_pairs,
        "spearman_components.csv": components,
        "categorical_associations.csv": associations,
        "numeric_categorical_group_summary.csv": group_summary,
        "special_family_relationships.csv": special,
        "numeric_standardized_coefficients_by_fold.csv": coefficients,
        "numeric_coefficient_stability.csv": coefficient_stability,
        "categorical_onehot_coefficients_by_fold.csv": categorical_coefficients,
        "categorical_coefficient_stability.csv": categorical_coefficient_stability,
    }
    for filename, artifact in artifacts.items():
        artifact.to_csv(output / filename, index=False)
    protected_after = {
        "source_database": _file_sha256(databases.source),
        "experiment_database": _file_sha256(databases.experiment),
    }
    if protected_before != protected_after:
        raise ValueError("Protected database changed during read-only diagnostic")
    result = {
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "development_only": True,
        "date_min": str(frame["race_date"].min()),
        "date_max": str(frame["race_date"].max()),
        "rows": len(frame),
        "races": int(frame["race_id"].nunique()),
        "feature_count": len(contract.inputs),
        "numeric_feature_count": len(contract.numeric),
        "categorical_feature_count": len(contract.categorical),
        "feature_hash": contract.feature_hash,
        "numeric_constant_count": int(numeric["constant_flag"].sum()),
        "numeric_near_constant_99pct_count": int(numeric["near_constant_99pct_flag"].sum()),
        "categorical_single_category_count": int(categorical["single_category_flag"].sum()),
        "categorical_dominant_99pct_count": int(categorical["dominant_99pct_flag"].sum()),
        "high_correlation_pair_count": len(pairs),
        "abs_pearson_ge_0_8_count": int(
            pairs.get("abs_pearson_ge_0_8", pd.Series(dtype=bool)).sum()
        ),
        "abs_spearman_ge_0_8_count": int(
            pairs.get("abs_spearman_ge_0_8", pd.Series(dtype=bool)).sum()
        ),
        "abs_spearman_ge_0_9_count": int(
            pairs.get("abs_spearman_ge_0_9", pd.Series(dtype=bool)).sum()
        ),
        "spearman_component_count": (
            int(components["component_id"].nunique()) if not components.empty else 0
        ),
        "strong_categorical_association_count": int(associations["strong_ge_0_8_flag"].sum()),
        "exact_numeric_pair_count": int(
            exact_pairs["exact_value_and_null_pattern"].sum()
        ) if not exact_pairs.empty else 0,
        "perfect_linear_numeric_pair_count": int(
            exact_pairs["perfect_linear_relationship"].sum()
        ) if not exact_pairs.empty else 0,
        "numeric_sign_consistent_4_of_4_count": int(
            coefficient_stability["sign_consistent_4_of_4"].sum()
        ),
        "coefficient_refit_seconds": fit_seconds,
        "existing_tree_importance_available": False,
        "tree_model_retrained": False,
        "heatmap_features": selected_heatmap,
        "validation_accessed": False,
        "post_2024_07_accessed": False,
        "protected_databases_unchanged": True,
        "protected_sha256": protected_after,
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_feature_diagnostic(), ensure_ascii=False, indent=2))
