from __future__ import annotations

import hashlib
import json
import time
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy import sparse  # type: ignore[import-untyped]
from sklearn.base import clone  # type: ignore[import-untyped]
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from kra_analytics.development_evaluation import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_FOLDS,
    _fold_frames,
    verify_sealed_artifacts,
)
from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.feature_bundle_experiment import _fit_candidate, _load_development_frame
from kra_analytics.improvement_validation_contract import EXPECTED_FEATURE_HASH
from kra_analytics.modeling import evaluate_probabilities, fit_sigmoid_calibrator
from kra_analytics.modeling_v2 import (
    TARGET_COLUMN,
    V2FeatureContract,
    build_v2_pipeline,
    expanding_temporal_oof_v2,
)
from kra_analytics.paths import ProjectPaths

EXPERIMENT_VERSION = "post_baseline_v2_ra1_development_v1"
CONTRACT_PATH = "docs/post-baseline-v2-race-aware-experiment-contract.json"
VALIDATION_LEDGER = (
    "data/exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/validation_access.json"
)
OUTPUT_RELATIVE = f"data/exports/modeling/{EXPERIMENT_VERSION}"
TOLERANCE = 1e-12
PROBABILITY_METRICS = (
    "macro_log_loss",
    "macro_brier",
    "micro_log_loss",
    "micro_brier",
    "calibration_intercept",
    "calibration_slope",
)
RANKING_METRICS = (
    "macro_ndcg_at_3",
    "micro_recall_at_3",
    "top1_plc_hit_rate",
    "race_any_hit_at_2",
    "race_any_hit_at_3",
    "micro_recall_at_1",
    "micro_recall_at_2",
    "macro_recall_at_1",
    "macro_recall_at_2",
    "macro_recall_at_3",
    "mean_positive_rank",
    "mean_positive_percentile_rank",
    "macro_average_precision",
)
RANKER_SETTINGS: dict[str, Any] = {
    "penalty": "l2",
    "C": 1.0,
    "solver": "lbfgs",
    "max_iter": 2000,
    "fit_intercept": False,
    "class_weight": None,
    "random_state": 20260817,
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class ScoreSigmoidCalibrator:
    intercept: float
    slope: float

    def predict(self, scores: np.ndarray) -> np.ndarray:
        linear = np.clip(self.intercept + self.slope * scores, -700.0, 700.0)
        return cast(np.ndarray, 1.0 / (1.0 + np.exp(-linear)))


@dataclass(frozen=True)
class PairAudit:
    races_seen: int
    eligible_races: int
    single_label_races: int
    directed_pairs: int
    cross_race_pairs: int
    positive_positive_pairs: int
    negative_negative_pairs: int
    reverse_pair_violations: int
    race_weight_sum_min: float
    race_weight_sum_max: float
    difference_check_max_abs_error: float


@dataclass
class PairBatch:
    differences: Any
    targets: np.ndarray
    weights: np.ndarray
    race_ids: np.ndarray
    audits_by_race: list[dict[str, Any]]
    audit: PairAudit


@dataclass
class PairwiseRanker:
    preprocessor: ColumnTransformer
    model: LogisticRegression
    pair_audit: PairAudit
    pair_audits_by_race: list[dict[str, Any]]
    fit_seconds: float
    warnings: list[str]

    def score(self, frame: pd.DataFrame, contract: V2FeatureContract) -> np.ndarray:
        transformed = self.preprocessor.transform(frame.loc[:, contract.inputs])
        return np.asarray(self.model.decision_function(transformed), dtype=float)


def _as_csr(matrix: Any) -> Any:
    if sparse.issparse(matrix):
        return matrix.tocsr()
    return sparse.csr_matrix(np.asarray(matrix, dtype=float))


def build_pair_batch(transformed: Any, frame: pd.DataFrame, *, sample_races: int = 5) -> PairBatch:
    matrix = _as_csr(transformed)
    if matrix.shape[0] != len(frame):
        raise ValueError("Transformed runner count does not match frame")
    blocks: list[Any] = []
    targets: list[int] = []
    weights: list[float] = []
    pair_races: list[str] = []
    audits: list[dict[str, Any]] = []
    sample_errors: list[float] = []
    single_label = 0

    positions = pd.Series(np.arange(len(frame)), index=frame.index)
    for race_id, group in frame.groupby("race_id", sort=False, observed=True):
        group_positions = positions.loc[group.index].to_numpy(dtype=int)
        labels = group[TARGET_COLUMN].to_numpy(dtype=int)
        positive = group_positions[labels == 1]
        negative = group_positions[labels == 0]
        if not len(positive) or not len(negative):
            single_label += 1
            audits.append(
                {
                    "race_id": str(race_id),
                    "positive_count": len(positive),
                    "negative_count": len(negative),
                    "directed_pairs": 0,
                    "expected_directed_pairs": 0,
                    "weight_sum": 0.0,
                    "eligible": False,
                }
            )
            continue
        per_pair_weight = 1.0 / (2.0 * len(positive) * len(negative))
        directed_count = 0
        for positive_position in positive:
            for negative_position in negative:
                difference = matrix[positive_position] - matrix[negative_position]
                blocks.extend((difference, -difference))
                targets.extend((1, 0))
                weights.extend((per_pair_weight, per_pair_weight))
                pair_races.extend((str(race_id), str(race_id)))
                directed_count += 2
                if len(sample_errors) < sample_races:
                    reverse = difference + (-difference)
                    sample_errors.append(float(abs(reverse).max()))
        expected = 2 * len(positive) * len(negative)
        audits.append(
            {
                "race_id": str(race_id),
                "positive_count": len(positive),
                "negative_count": len(negative),
                "directed_pairs": directed_count,
                "expected_directed_pairs": expected,
                "weight_sum": directed_count * per_pair_weight,
                "eligible": True,
            }
        )

    if not blocks:
        raise ValueError("No eligible positive-negative race pairs")
    differences = sparse.vstack(blocks, format="csr")
    target_array = np.asarray(targets, dtype=int)
    weight_array = np.asarray(weights, dtype=float)
    eligible = [item for item in audits if item["eligible"]]
    weight_sums = [float(item["weight_sum"]) for item in eligible]
    reverse_violations = sum(
        int(item["directed_pairs"] != item["expected_directed_pairs"]) for item in eligible
    )
    audit = PairAudit(
        races_seen=int(frame["race_id"].nunique()),
        eligible_races=len(eligible),
        single_label_races=single_label,
        directed_pairs=len(target_array),
        cross_race_pairs=0,
        positive_positive_pairs=0,
        negative_negative_pairs=0,
        reverse_pair_violations=reverse_violations,
        race_weight_sum_min=min(weight_sums),
        race_weight_sum_max=max(weight_sums),
        difference_check_max_abs_error=max(sample_errors, default=0.0),
    )
    if set(target_array) != {0, 1} or int(target_array.sum()) * 2 != len(target_array):
        raise ValueError("Directed pair labels are not balanced by reverse pairs")
    if reverse_violations or not np.allclose(weight_sums, 1.0, atol=TOLERANCE):
        raise ValueError("Pair reverse or equal-race-weight contract failed")
    return PairBatch(
        differences=differences,
        targets=target_array,
        weights=weight_array,
        race_ids=np.asarray(pair_races, dtype=object),
        audits_by_race=audits,
        audit=audit,
    )


def fit_pairwise_ranker(frame: pd.DataFrame, contract: V2FeatureContract) -> PairwiseRanker:
    pipeline = build_v2_pipeline(contract)
    preprocessor = clone(pipeline.named_steps["preprocessor"])
    if not isinstance(preprocessor, ColumnTransformer):
        raise TypeError("Expected ColumnTransformer")
    started = time.perf_counter()
    transformed = preprocessor.fit_transform(frame.loc[:, contract.inputs])
    pairs = build_pair_batch(transformed, frame)
    model = LogisticRegression(**RANKER_SETTINGS)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(
            pairs.differences,
            pairs.targets,
            sample_weight=pairs.weights,
        )
    warning_messages = [str(item.message) for item in caught]
    if any(issubclass(item.category, ConvergenceWarning) for item in caught):
        raise RuntimeError("RA1 pairwise Logistic did not converge")
    return PairwiseRanker(
        preprocessor=preprocessor,
        model=model,
        pair_audit=pairs.audit,
        pair_audits_by_race=pairs.audits_by_race,
        fit_seconds=time.perf_counter() - started,
        warnings=warning_messages,
    )


def fit_score_sigmoid(
    targets: np.ndarray | pd.Series, scores: np.ndarray | pd.Series
) -> ScoreSigmoidCalibrator:
    y = np.asarray(targets, dtype=int)
    x = np.asarray(scores, dtype=float).reshape(-1, 1)
    if set(np.unique(y)) != {0, 1} or np.ptp(x) <= np.finfo(float).eps:
        raise ValueError("Score sigmoid requires two target classes and nonconstant scores")
    model = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=2000)
    model.fit(x, y)
    return ScoreSigmoidCalibrator(
        intercept=float(model.intercept_[0]), slope=float(model.coef_[0, 0])
    )


def expanding_pairwise_oof(
    frame: pd.DataFrame, contract: V2FeatureContract
) -> tuple[pd.Series, list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = frame.sort_values(["race_date", "race_id", "horse_id"]).copy()
    dates = pd.to_datetime(ordered["race_date"])
    prediction_start = dates.min().to_period("M") + 3
    last_month = dates.max().to_period("M")
    predictions = pd.Series(index=ordered.index, dtype=float)
    folds: list[dict[str, Any]] = []
    pair_audits: list[dict[str, Any]] = []
    inner_id = 0
    while prediction_start <= last_month:
        prediction_end = prediction_start + 3
        train = ordered.loc[dates < prediction_start.start_time]
        prediction = ordered.loc[
            (dates >= prediction_start.start_time) & (dates < prediction_end.start_time)
        ]
        if prediction.empty:
            prediction_start = prediction_end
            continue
        inner_id += 1
        ranker = fit_pairwise_ranker(train, contract)
        predictions.loc[prediction.index] = ranker.score(prediction, contract)
        if train["race_date"].max() >= prediction["race_date"].min():
            raise ValueError("RA1 inner temporal OOF ordering violation")
        folds.append(
            {
                "inner_fold": inner_id,
                "train_start": str(train["race_date"].min()),
                "train_end": str(train["race_date"].max()),
                "prediction_start": str(prediction["race_date"].min()),
                "prediction_end": str(prediction["race_date"].max()),
                "train_rows": len(train),
                "train_races": int(train["race_id"].nunique()),
                "prediction_rows": len(prediction),
                "prediction_races": int(prediction["race_id"].nunique()),
                "strict_temporal_ordering": True,
                "preprocessing_fit_scope": "inner_fold_train_only",
            }
        )
        pair_audits.append({"inner_fold": inner_id, **asdict(ranker.pair_audit)})
        prediction_start = prediction_end
    return predictions.dropna(), folds, pair_audits


def ranking_metrics(frame: pd.DataFrame, scores: np.ndarray) -> dict[str, float]:
    ranked = frame.loc[:, ["race_id", "horse_id", TARGET_COLUMN]].copy()
    ranked["score"] = np.asarray(scores, dtype=float)
    race_rows: list[dict[str, float]] = []
    total_hits = 0
    selected_hits = {1: 0, 2: 0, 3: 0}
    top1_hits = 0
    any_hits = {2: 0, 3: 0}
    positive_ranks: list[float] = []
    normalized_positive_ranks: list[float] = []
    for _, race in ranked.groupby("race_id", sort=False, observed=True):
        race = race.sort_values(["score", "horse_id"], ascending=[False, True]).copy()
        y = race[TARGET_COLUMN].to_numpy(dtype=int)
        n = len(race)
        positives = int(y.sum())
        if positives <= 0:
            continue
        total_hits += positives
        hit_counts = {k: int(y[: min(k, n)].sum()) for k in (1, 2, 3)}
        for k in (1, 2, 3):
            selected_hits[k] += hit_counts[k]
        top1_hits += int(y[0] == 1)
        any_hits[2] += int(hit_counts[2] > 0)
        any_hits[3] += int(hit_counts[3] > 0)
        discounts = 1.0 / np.log2(np.arange(2, min(3, n) + 2))
        dcg = float((y[: len(discounts)] * discounts).sum())
        idcg = float(discounts[: min(positives, len(discounts))].sum())
        precisions = np.cumsum(y) / np.arange(1, n + 1)
        average_precision = float((precisions * y).sum() / positives)
        ranks = np.flatnonzero(y == 1) + 1
        positive_ranks.extend(ranks.astype(float))
        normalized_positive_ranks.extend(((ranks - 1) / max(n - 1, 1)).astype(float))
        race_rows.append(
            {
                "ndcg_at_3": dcg / idcg,
                "recall_at_1": hit_counts[1] / positives,
                "recall_at_2": hit_counts[2] / positives,
                "recall_at_3": hit_counts[3] / positives,
                "average_precision": average_precision,
            }
        )
    races = pd.DataFrame(race_rows)
    race_count = len(races)
    if not race_count or not total_hits:
        raise ValueError("Ranking metrics require races with positive targets")
    return {
        "macro_ndcg_at_3": float(races["ndcg_at_3"].mean()),
        "micro_recall_at_3": selected_hits[3] / total_hits,
        "top1_plc_hit_rate": top1_hits / race_count,
        "race_any_hit_at_2": any_hits[2] / race_count,
        "race_any_hit_at_3": any_hits[3] / race_count,
        "micro_recall_at_1": selected_hits[1] / total_hits,
        "micro_recall_at_2": selected_hits[2] / total_hits,
        "macro_recall_at_1": float(races["recall_at_1"].mean()),
        "macro_recall_at_2": float(races["recall_at_2"].mean()),
        "macro_recall_at_3": float(races["recall_at_3"].mean()),
        "mean_positive_rank": float(np.mean(positive_ranks)),
        "mean_positive_percentile_rank": float(np.mean(normalized_positive_ranks)),
        "macro_average_precision": float(races["average_precision"].mean()),
    }


def _probability_metrics(frame: pd.DataFrame, values: np.ndarray) -> dict[str, float]:
    payload = asdict(evaluate_probabilities(frame, values))
    return {metric: float(payload[metric]) for metric in PROBABILITY_METRICS}


def _summary(fold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for model_id in ("L133", "RA1"):
        selected = [row for row in fold_rows if row["model_id"] == model_id]
        row: dict[str, Any] = {"model_id": model_id, "folds": len(selected)}
        for metric in (*PROBABILITY_METRICS, *RANKING_METRICS, "fit_seconds"):
            values = np.asarray([item[metric] for item in selected], dtype=float)
            row[f"{metric}_mean"] = float(values.mean())
            row[f"{metric}_std"] = float(values.std(ddof=0))
        result.append(row)
    return result


def _deltas(fold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in DEVELOPMENT_FOLDS:
        reference = next(
            row for row in fold_rows if row["model_id"] == "L133" and row["fold_id"] == spec.fold_id
        )
        candidate = next(
            row for row in fold_rows if row["model_id"] == "RA1" and row["fold_id"] == spec.fold_id
        )
        rows.append(
            {
                "fold_id": spec.fold_id,
                **{
                    f"delta_{metric}": float(candidate[metric]) - float(reference[metric])
                    for metric in (*PROBABILITY_METRICS, *RANKING_METRICS)
                },
            }
        )
    return rows


def decide_ra1(summaries: list[dict[str, Any]], deltas: list[dict[str, Any]]) -> dict[str, Any]:
    reference = next(row for row in summaries if row["model_id"] == "L133")
    candidate = next(row for row in summaries if row["model_id"] == "RA1")
    rank_mean = {
        metric: float(candidate[f"{metric}_mean"]) > float(reference[f"{metric}_mean"]) + TOLERANCE
        for metric in ("macro_ndcg_at_3", "micro_recall_at_3")
    }
    rank_folds = {
        metric: sum(float(row[f"delta_{metric}"]) > TOLERANCE for row in deltas)
        for metric in ("macro_ndcg_at_3", "micro_recall_at_3")
    }
    probability_no_worse = {
        metric: float(candidate[f"{metric}_mean"]) <= float(reference[f"{metric}_mean"]) + TOLERANCE
        for metric in ("macro_log_loss", "macro_brier")
    }
    relative_degradation = {
        metric: (float(candidate[f"{metric}_mean"]) - float(reference[f"{metric}_mean"]))
        / float(reference[f"{metric}_mean"])
        for metric in ("macro_log_loss", "macro_brier")
    }
    both_rank_mean = all(rank_mean.values())
    rank_repetition_passes = {metric: value >= 3 for metric, value in rank_folds.items()}
    both_rank_repetition = all(rank_repetition_passes.values())
    both_probability_no_worse = all(probability_no_worse.values())
    probability_within_one_percent = all(
        value <= 0.01 + TOLERANCE for value in relative_degradation.values()
    )

    if both_rank_mean and both_rank_repetition and both_probability_no_worse:
        judgement = "PROMOTE_RACE_AWARE"
        reason = "both primary ranking metrics repeat and both probability guardrails pass"
    elif (both_rank_mean and both_rank_repetition and probability_within_one_percent) or (
        both_probability_no_worse and sum(rank_repetition_passes.values()) == 1 and both_rank_mean
    ):
        judgement = "CONDITIONAL"
        reason = "the sealed ranking/probability trade-off matches a CONDITIONAL clause"
    else:
        judgement = "DROP_RACE_AWARE"
        reason = "one or more sealed mean, repetition, or probability guardrail conditions failed"
    return {
        "judgement": judgement,
        "reason": reason,
        "conditions": {
            "ranking_mean_improves": rank_mean,
            "ranking_improved_fold_count": rank_folds,
            "ranking_repetition_passes": rank_repetition_passes,
            "probability_mean_no_worse": probability_no_worse,
            "probability_relative_degradation": relative_degradation,
            "probability_within_one_percent": probability_within_one_percent,
        },
        "additional_pairwise_tuning_allowed": False,
    }


def _validate_contract(paths: ProjectPaths, feature_contract: V2FeatureContract) -> dict[str, Any]:
    path = paths.root / CONTRACT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_folds = "existing four quarterly expanding folds"
    checks = {
        "status_sealed": payload["status"] == "SEALED_BEFORE_DEVELOPMENT_EXECUTION",
        "feature_count": payload["candidate"]["feature_count"]
        == len(feature_contract.inputs)
        == 133,
        "feature_hash": payload["candidate"]["feature_hash"]
        == feature_contract.feature_hash
        == EXPECTED_FEATURE_HASH,
        "same_reference_hash": payload["reference"]["feature_hash"] == EXPECTED_FEATURE_HASH,
        "no_new_features": payload["candidate"]["new_features_allowed"] is False,
        "pair_rule": payload["candidate"]["pair_generation"]
        == "all positive-negative pairs plus reversed directed pairs",
        "weight_rule": payload["candidate"]["directed_pair_weight"]
        == "1 / (2 * race_positive_count * race_negative_count)",
        "ranker_settings": all(
            payload["ranker"].get(key) == value for key, value in RANKER_SETTINGS.items()
        ),
        "calibration": payload["calibration"]["method"] == "sigmoid"
        and payload["calibration"]["selection_allowed"] is False,
        "development_dates": payload["development"]["start_inclusive"] == "2023-01-01"
        and payload["development"]["end_exclusive"] == "2024-07-01",
        "fold_contract": payload["development"]["fold_contract"] == expected_folds
        and len(DEVELOPMENT_FOLDS) == 4,
        "decision_rule_immutable": payload["decision_rule"]["rules_mutable_after_execution"]
        is False,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise ValueError(f"RA1 sealed contract preflight failed: {failed}")
    return {
        "contract_path": CONTRACT_PATH,
        "contract_sha256": _sha256_file(path),
        "checks": checks,
        "feature_count": len(feature_contract.inputs),
        "feature_hash": feature_contract.feature_hash,
        "feature_order_verified": True,
    }


def _protected_paths(paths: ProjectPaths) -> dict[str, Path]:
    return {
        "validation_ledger": paths.root / VALIDATION_LEDGER,
        "validation_result": paths.root
        / "docs/post-baseline-v2-f1-f3-one-time-validation-result.md",
        "improvement_contract": paths.root
        / "docs/post-baseline-v2-improvement-validation-contract.json",
        "feature_bundles": paths.root / "src/kra_analytics/feature_bundles.py",
        "m1_result": paths.exports / "modeling/m1_histgradientboosting_development_v1/result.json",
        "h133_result": paths.exports / "modeling/post_baseline_v2_h133_development_v1/result.json",
    }


def run_ra1_development_experiment(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contracts = _combined_contract(project_paths)
    contract = contracts["F1+F3"]
    contract_audit = _validate_contract(project_paths, contract)

    protection = json.loads(
        (project_paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    sealed_before = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_paths = _protected_paths(project_paths)
    protected_before = {name: _sha256_file(path) for name, path in protected_paths.items()}
    ledger_before = json.loads(protected_paths["validation_ledger"].read_text(encoding="utf-8"))
    if (
        ledger_before.get("access_count") != 1
        or ledger_before.get("descriptive_diagnostic_reaccess_count") != 1
    ):
        raise ValueError("Validation access ledger differs from the protected preflight state")

    frame = _load_development_frame(project_paths, contracts)
    if frame["race_date"].max() >= DEVELOPMENT_END_EXCLUSIVE:
        raise ValueError("RA1 development loader crossed 2024-07-01")

    fold_rows: list[dict[str, Any]] = []
    fold_context: list[dict[str, Any]] = []
    pair_audit_rows: list[dict[str, Any]] = []
    pair_race_rows: list[dict[str, Any]] = []
    inner_rows: list[dict[str, Any]] = []
    for spec in DEVELOPMENT_FOLDS:
        train, evaluation = _fold_frames(frame, spec)
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
                "race_overlap": len(set(train["race_id"]) & set(evaluation["race_id"])),
            }
        )

        l_started = time.perf_counter()
        _, l_raw, _, l_warnings = _fit_candidate(
            train=train, evaluation=evaluation, contract=contract
        )
        l_oof, l_inner_folds = expanding_temporal_oof_v2(train, contract)
        l_calibrator = fit_sigmoid_calibrator(train.loc[l_oof.index, TARGET_COLUMN], l_oof)
        l_probability = l_calibrator.predict(l_raw)
        l_seconds = time.perf_counter() - l_started
        for row in l_inner_folds:
            inner_rows.append({"model_id": "L133", "outer_fold": spec.fold_id, **row})

        r_started = time.perf_counter()
        r_oof, r_inner_folds, r_inner_pair_audits = expanding_pairwise_oof(train, contract)
        r_calibrator = fit_score_sigmoid(train.loc[r_oof.index, TARGET_COLUMN], r_oof)
        ranker = fit_pairwise_ranker(train, contract)
        r_score = ranker.score(evaluation, contract)
        r_probability = r_calibrator.predict(r_score)
        r_seconds = time.perf_counter() - r_started
        for row in r_inner_folds:
            inner_rows.append({"model_id": "RA1", "outer_fold": spec.fold_id, **row})
        for row in r_inner_pair_audits:
            pair_audit_rows.append({"scope": "inner", "outer_fold": spec.fold_id, **row})
        pair_audit_rows.append(
            {"scope": "outer_full_train", "outer_fold": spec.fold_id, **asdict(ranker.pair_audit)}
        )
        pair_race_rows.extend(
            {"outer_fold": spec.fold_id, **row} for row in ranker.pair_audits_by_race
        )

        for model_id, probability, score, seconds, warning_messages in (
            ("L133", l_probability, l_raw, l_seconds, l_warnings),
            ("RA1", r_probability, r_score, r_seconds, ranker.warnings),
        ):
            fold_rows.append(
                {
                    "model_id": model_id,
                    "fold_id": spec.fold_id,
                    **_probability_metrics(evaluation, probability),
                    **ranking_metrics(evaluation, score),
                    "fit_seconds": seconds,
                    "warning_count": len(warning_messages),
                    "warning_messages": warning_messages,
                }
            )

    summaries = _summary(fold_rows)
    deltas = _deltas(fold_rows)
    decision = decide_ra1(summaries, deltas)

    sealed_after = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_after = {name: _sha256_file(path) for name, path in protected_paths.items()}
    ledger_after = json.loads(protected_paths["validation_ledger"].read_text(encoding="utf-8"))
    if (
        sealed_before != sealed_after
        or protected_before != protected_after
        or ledger_before != ledger_after
    ):
        raise ValueError("A sealed artifact or Validation ledger changed during RA1")

    output = project_paths.root / OUTPUT_RELATIVE
    if output.exists() and (output / "result.json").exists():
        raise FileExistsError(
            "RA1 result already exists; sealed single execution will not overwrite it"
        )
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(fold_rows).drop(columns="warning_messages").to_csv(
        output / "fold_metrics.csv", index=False
    )
    pd.DataFrame(summaries).to_csv(output / "summary_metrics.csv", index=False)
    pd.DataFrame(deltas).to_csv(output / "fold_deltas.csv", index=False)
    pd.DataFrame(pair_audit_rows).to_csv(output / "pair_audit.csv", index=False)
    pd.DataFrame(pair_race_rows).to_csv(output / "pair_by_race_audit.csv", index=False)
    pd.DataFrame(inner_rows).to_csv(output / "nested_oof_folds.csv", index=False)
    registry = {
        "experiment_version": EXPERIMENT_VERSION,
        "status": "DEVELOPMENT_COMPLETE",
        "contract": contract_audit,
        "development_window": ["2023-01-01", "2024-06-30"],
        "models": {
            "L133": "same 133 + fold-train temporal OOF sigmoid",
            "RA1": {"candidate_id": "RA1_LINEAR_PAIRWISE_LOGISTIC_SIGMOID", **RANKER_SETTINGS},
        },
        "fold_metrics": fold_rows,
        "summary_metrics": summaries,
        "decision": decision,
        "validation_access_count": ledger_after["access_count"],
        "descriptive_diagnostic_reaccess_count": ledger_after[
            "descriptive_diagnostic_reaccess_count"
        ],
    }
    (output / "experiment_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = {
        **registry,
        "development_rows": len(frame),
        "development_races": int(frame["race_id"].nunique()),
        "max_loaded_race_date": str(frame["race_date"].max()),
        "fold_context": fold_context,
        "fold_deltas": deltas,
        "pair_generation_audits": pair_audit_rows,
        "nested_oof_folds": inner_rows,
        "validation_or_later_rows_loaded": False,
        "post_selection_rows_loaded": False,
        "sealed_artifacts_unchanged": True,
        "protected_artifacts_unchanged": True,
        "sealed_artifact_hashes": sealed_after,
        "protected_artifact_hashes": protected_after,
    }
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
