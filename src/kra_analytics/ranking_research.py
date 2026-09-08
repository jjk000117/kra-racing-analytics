"""Sealed ranking v1 infrastructure. No automatic model fitting or performance experiment."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]

from kra_analytics.development_evaluation import (
    DEVELOPMENT_END_EXCLUSIVE,
    DEVELOPMENT_FOLDS,
    DEVELOPMENT_START,
    _fold_frames,
    enforce_development_window,
)
from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.modeling_v2 import V2FeatureContract, build_v2_pipeline
from kra_analytics.paths import ProjectPaths

VERSION = "ranking_research_v1"
CANDIDATE = "RANK_L133_PLC_LGBM_V1"
FEATURE_HASH = "18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182"
KEYS = ["race_id", "horse_id", "race_date"]
SORT = ["race_date", "race_id", "horse_id"]
TABLE = "mart.place_feature_snapshot_v2_engineered_candidate"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class RankingPaths:
    """Explicit source; never consult process-wide KRA_DATABASE_PATH for writes."""

    root: Path
    source: Path

    def output(self, relative: str) -> Path:
        root, source = self.root.resolve(strict=True), self.source.resolve(strict=True)
        target = (root / relative).resolve()
        allowed = (root / "data/exports/modeling" / VERSION).resolve()
        # Check the nominal boundary too: an allowed directory may itself be a junction.
        if not allowed.is_relative_to(root) or not target.is_relative_to(allowed):
            raise ValueError("Output must stay inside branch-local ranking exports")
        if target == source or (target.exists() and target.samefile(source)):
            raise ValueError("Source/output collision")
        if source.is_relative_to(target):
            raise ValueError("Output contains source database")
        return target

    @contextmanager
    def connect_source(self) -> Iterator[duckdb.DuckDBPyConnection]:
        source = self.source.resolve(strict=True)
        connection = duckdb.connect(str(source), read_only=True)
        try:
            yield connection
        finally:
            connection.close()

    def write_json(self, relative: str, payload: dict[str, Any]) -> Path:
        path = self.output(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path = self.output(relative)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        return path


def l133_contract(root: Path) -> V2FeatureContract:
    contract = _combined_contract(ProjectPaths.from_root(root))["F1+F3"]
    frozen = json.loads(
        (root / "docs/post-baseline-v2-improvement-validation-contract.json").read_text(
            encoding="utf-8-sig"
        )
    )["candidate"]
    computed = hashlib.sha256(("\n".join(contract.inputs) + "\n").encode()).hexdigest()
    if (
        len(contract.inputs) != 133
        or len(set(contract.inputs)) != 133
        or list(contract.inputs) != frozen["feature_order"]
        or computed != FEATURE_HASH
        or contract.feature_hash != FEATURE_HASH
        or frozen["feature_hash"] != FEATURE_HASH
    ):
        raise ValueError("L133 Feature name/order/hash mismatch")
    return contract


def validate_rows(frame: pd.DataFrame, *, labels: bool = True) -> None:
    if frame.empty or frame[KEYS].isna().any().any():
        raise ValueError("Empty population or missing keys")
    for column in ["race_id", "horse_id"]:
        if not frame[column].map(lambda x: isinstance(x, str) and bool(x)).all():
            raise ValueError("IDs must be nonempty strings; preserve leading zeros")
    dates = pd.to_datetime(frame.race_date, errors="raise")
    if dates.isna().any() or (dates != dates.dt.normalize()).any():
        raise ValueError("Invalid race date")
    enforce_development_window(
        start=dates.min().date(), end_exclusive=dates.max().date() + timedelta(days=1)
    )
    if frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate race/horse key")
    if frame.groupby("race_id").race_date.nunique().ne(1).any():
        raise ValueError("Race split across dates")
    if labels and (frame.place_hit.isna().any() or not frame.place_hit.isin([0, 1]).all()):
        raise ValueError("Relevance must be binary official PLC")


def load_dataset(paths: RankingPaths) -> tuple[pd.DataFrame, V2FeatureContract]:
    contract = l133_contract(paths.root)
    enforce_development_window(start=DEVELOPMENT_START, end_exclusive=DEVELOPMENT_END_EXCLUSIVE)
    features = ", ".join(f's."{name}"' for name in contract.inputs)
    query = f"""
        SELECT s.race_id, s.horse_id, s.race_date, {features}, s.place_hit,
               s.snapshot_id, s.result_status, s.is_valid_start, s.is_valid_finish,
               s.feature_as_of, s.source_max_event_date, s.population_exclusion_reason,
               r.runner_result_id, r.official_finish_rank,
               r.result_status AS canonical_status, r.is_valid_start AS canonical_start,
               r.is_valid_finish AS canonical_finish, a.f1_source_max_event_date,
               a.horse_id AS audit_horse_id
        FROM {TABLE} s
        LEFT JOIN canonical.runner_result r USING (race_id, horse_id)
        LEFT JOIN quality.post_baseline_v2_feature_source_audit a
          ON s.race_id=a.race_id AND s.horse_id=a.horse_id
        WHERE s.race_date >= ? AND s.race_date < ?
        ORDER BY s.race_date, s.race_id, s.horse_id
    """
    with paths.connect_source() as connection:
        frame = connection.execute(query, [DEVELOPMENT_START, DEVELOPMENT_END_EXCLUSIVE]).fetchdf()
    frame["race_date"] = pd.to_datetime(frame.race_date).dt.date
    validate_rows(frame)
    if frame[["runner_result_id", "audit_horse_id", "snapshot_id"]].isna().any().any():
        raise ValueError("Missing target/lineage join")
    if not frame.result_status.isin(["FINISHED", "RACE_STOPPED", "DISQUALIFIED"]).all():
        raise ValueError("Unresolved/DNS status entered inherited population")
    if (
        not frame.is_valid_start.eq(True).all()
        or not frame.result_status.eq(frame.canonical_status).all()
        or not frame.is_valid_start.eq(frame.canonical_start).all()
        or not frame.is_valid_finish.eq(frame.canonical_finish).all()
        or frame.population_exclusion_reason.notna().any()
    ):
        raise ValueError("Population/status contract mismatch")
    if (
        frame[["is_valid_start", "is_valid_finish", "canonical_start", "canonical_finish"]]
        .isna()
        .any()
        .any()
    ):
        raise ValueError("Missing status flags")
    finished = frame.result_status.eq("FINISHED")
    if frame.loc[finished, "official_finish_rank"].isna().any():
        raise ValueError("Missing official finish")
    if (
        not frame.loc[finished, "is_valid_finish"].eq(True).all()
        or not frame.loc[finished, "official_finish_rank"].between(1, 16).all()
        or frame.loc[~finished, "is_valid_finish"].ne(False).any()
    ):
        raise ValueError("Invalid official finish")
    as_of = pd.to_datetime(frame.feature_as_of)
    if not as_of.eq(pd.to_datetime(frame.race_date)).all():
        raise ValueError("feature_as_of mismatch")
    for name in ["source_max_event_date", "f1_source_max_event_date"]:
        if (pd.to_datetime(frame[name]) >= as_of).any():
            raise ValueError("PIT source must precede race date")
    return frame, contract


def grouped(frame: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    validate_rows(frame)
    ordered = frame.sort_values(SORT, kind="stable").reset_index(drop=True)
    sizes = ordered.groupby("race_id", sort=False).size().to_numpy(dtype=np.int32)
    validate_groups(ordered, sizes)
    return ordered, sizes


def validate_groups(frame: pd.DataFrame, sizes: np.ndarray) -> None:
    validate_rows(frame)
    if sizes.ndim != 1 or not np.issubdtype(sizes.dtype, np.integer):
        raise ValueError("Invalid group array")
    if (sizes < 3).any() or int(sizes.sum()) != len(frame):
        raise ValueError("Group size/sum mismatch")
    start, seen = 0, set()
    for size in sizes:
        block = frame.iloc[start : start + int(size)]
        race = block.race_id.iloc[0]
        if block.race_id.nunique() != 1 or race in seen:
            raise ValueError("Noncontiguous or repeated race group")
        seen.add(race)
        start += int(size)


def prepare_fold(
    frame: pd.DataFrame, fold_id: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    validate_rows(frame)
    spec = next((s for s in DEVELOPMENT_FOLDS if s.fold_id == fold_id), None)
    if spec is None:
        raise ValueError("Unknown sealed fold")
    small = frame.groupby("race_id").size().loc[lambda x: x < 3].index
    exclusions = [{"race_id": r, "reason": "MIN_RUNNERS", "scope": "both"} for r in small]
    train, evaluation = _fold_frames(frame.loc[~frame.race_id.isin(small)], spec)
    single = train.groupby("race_id").place_hit.nunique().loc[lambda x: x == 1].index
    exclusions += [{"race_id": r, "reason": "SINGLE_RELEVANCE", "scope": "train"} for r in single]
    train = train.loc[~train.race_id.isin(single)]
    return grouped(train)[0], grouped(evaluation)[0], pd.DataFrame(exclusions)


def validate_environment(root: Path) -> dict[str, str]:
    """Fail closed if the recorded environment drifts, including inherited packages."""
    import sys

    if sys.version_info[:3] != (3, 12, 13):
        raise ValueError("Ranking v1 requires the recorded Python 3.12.13")
    versions = {}
    for line in (root / "ranking-requirements.lock.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==")
        actual = importlib.metadata.version(name)
        if actual != expected:
            raise ValueError(f"Environment drift: {name} {actual} != {expected}")
        versions[name] = actual
    return versions


def model_config() -> dict[str, Any]:
    return dict(
        objective="lambdarank",
        boosting_type="gbdt",
        n_estimators=200,
        learning_rate=0.03,
        num_leaves=15,
        max_depth=4,
        min_child_samples=50,
        min_child_weight=0.001,
        min_split_gain=0,
        reg_alpha=0,
        reg_lambda=1,
        subsample=1,
        subsample_freq=0,
        colsample_bytree=1,
        max_bin=255,
        random_state=20260908,
        data_random_seed=20260908,
        feature_fraction_seed=20260908,
        bagging_seed=20260908,
        n_jobs=1,
        deterministic=True,
        force_col_wise=True,
        device_type="cpu",
        label_gain=[0, 1],
        lambdarank_truncation_level=6,
        lambdarank_norm=True,
        sigmoid=1,
        metric="ndcg",
        zero_as_missing=False,
        use_missing=True,
        verbosity=-1,
    )


@dataclass
class Ranker:
    preprocessor: ColumnTransformer
    model: Any
    contract: V2FeatureContract

    def save(self, paths: RankingPaths, relative: str) -> Path:
        """Save a trusted local model only under the guarded branch artifact directory."""
        import joblib  # type: ignore[import-untyped]

        path = paths.output(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path = paths.output(relative)
        with path.open("xb") as stream:
            joblib.dump(self, stream)
        return path

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        validate_rows(frame, labels=False)
        values = self.preprocessor.transform(frame.loc[:, self.contract.inputs])
        scores = np.asarray(self.model.booster_.predict(values), dtype=float)
        if scores.shape != (len(frame),) or not np.isfinite(scores).all():
            raise ValueError("Invalid rank score")
        return scores


def fit_ranker(train: pd.DataFrame, contract: V2FeatureContract) -> Ranker:
    """Explicit single fit; never early-stop or select using evaluation rows.

    Preserve sealed L133 OHE/imputation/scaling representation, not because trees need scaling.
    No native category/missing experiment. Unknown categories are all-zero OHE vectors.
    """
    from lightgbm import LGBMRanker

    validate_environment(Path(__file__).resolve().parents[2])

    if importlib.metadata.version("lightgbm") != "4.6.0":
        raise ValueError("Expected LightGBM 4.6.0")
    ordered, sizes = grouped(train)
    if ordered.groupby("race_id").place_hit.nunique().ne(2).any():
        raise ValueError("Remove/report single-relevance training races first")
    preprocessor = build_v2_pipeline(contract).named_steps["preprocessor"]
    values = preprocessor.fit_transform(ordered.loc[:, contract.inputs])
    model = LGBMRanker(**model_config())
    model.fit(
        values,
        ordered.place_hit.astype(int).to_numpy(),
        group=sizes,
        categorical_feature=[],
        eval_at=[3],
    )
    return Ranker(preprocessor, model, contract)


def run_ranker_fold(
    frame: pd.DataFrame, root: Path, fold_id: str
) -> tuple[pd.DataFrame, np.ndarray, Ranker, pd.DataFrame]:
    """Prepared for a later authorized experiment; this phase only tests synthetic fitting."""
    validate_environment(root)
    train, evaluation, exclusions = prepare_fold(frame, fold_id)
    model = fit_ranker(train, l133_contract(root))
    return evaluation, model.predict(evaluation), model, exclusions


def run_plc_fold(frame: pd.DataFrame, root: Path, fold_id: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Minimal raw L133 comparator adapter; no calibration or full-OOF orchestration."""
    validate_environment(root)
    validate_rows(frame)
    spec = next((s for s in DEVELOPMENT_FOLDS if s.fold_id == fold_id), None)
    if spec is None:
        raise ValueError("Unknown sealed fold")
    small = frame.groupby("race_id").size().loc[lambda x: x < 3].index
    train, evaluation = _fold_frames(frame.loc[~frame.race_id.isin(small)], spec)
    train, evaluation = grouped(train)[0], grouped(evaluation)[0]
    contract = l133_contract(root)
    pipeline = build_v2_pipeline(contract)
    pipeline.fit(train.loc[:, contract.inputs], train.place_hit.astype(int))
    probability = np.asarray(pipeline.predict_proba(evaluation.loc[:, contract.inputs])[:, 1])
    return evaluation, probability


def ranking_metrics(
    frame: pd.DataFrame, scores: np.ndarray
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Binary NDCG concentrates official PLC hits, not finish 1/2/3 ordering.

    Race-macro aggregation; zero-positive queries retain NA, invalidating comparison.
    """
    validate_rows(frame)
    if len(scores) != len(frame) or not np.isfinite(scores).all():
        raise ValueError("Invalid scores")
    ranked = frame.assign(score=scores).sort_values(
        ["race_id", "score", "horse_id"], ascending=[True, False, True], kind="stable"
    )
    rows: list[dict[str, Any]] = []
    discount = 1 / np.log2(np.arange(2, 5))
    for race_id, race in ranked.groupby("race_id", sort=False):
        if len(race) < 3:
            raise ValueError("Metric requires at least 3 runners")
        y = race.place_hit.to_numpy(dtype=int)
        positives, hits = int(y.sum()), int(y[:3].sum())
        row = dict(
            race_id=race_id,
            ndcg_at_3=float(np.dot(y[:3], discount) / discount[: min(3, positives)].sum())
            if positives
            else float("nan"),
            recall_at_3=hits / positives if positives else float("nan"),
            ndcg_at_1=float(y[0]) if positives else float("nan"),
            top1_plc_hit=float(y[0]),
            top3_any_plc_hit=float(hits > 0),
            plc_hits_in_top3=float(hits),
        )
        rows.append(row)
    per_race = pd.DataFrame(rows)
    macro = {
        f"macro_{c}": float(per_race[c].mean(skipna=False))
        for c in per_race.columns
        if c != "race_id"
    }
    return per_race, macro
