"""Development-only OOF interchange; no probability interpretation of ranking scores."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS
from kra_analytics.ranking_research import (
    FEATURE_HASH,
    KEYS,
    VERSION,
    RankingPaths,
    file_hash,
    validate_rows,
)

JOIN_KEYS = [*KEYS, "fold_id"]
PROVENANCE = [
    "contract_version",
    "feature_hash",
    "source_db_hash",
    "code_hash",
    "config_hash",
    "snapshot_hash",
    "contract_hash",
    "run_id",
    "candidate_id",
]
HASHES = [c for c in PROVENANCE if c.endswith("hash")]
RANK_COLUMNS = ["ranking_raw_score", "ranking_within_race_rank", "ranking_normalized_score"]


def expected_oof(frame: pd.DataFrame) -> pd.DataFrame:
    """Select only existing outer evaluation windows; first H1 has no OOF."""
    validate_rows(frame)
    pieces = []
    dates = pd.to_datetime(frame.race_date).dt.date
    for spec in DEVELOPMENT_FOLDS:
        part = frame.loc[
            (dates >= spec.evaluation_start) & (dates < spec.evaluation_end_exclusive), KEYS
        ].copy()
        part["fold_id"] = spec.fold_id
        pieces.append(part)
    result = pd.concat(pieces, ignore_index=True)
    if result.empty:
        raise ValueError("No outer-evaluation rows")
    return result


def normalize_scores(frame: pd.DataFrame, scores: np.ndarray) -> pd.DataFrame:
    validate_rows(frame, labels=False)
    if np.asarray(scores).shape != (len(frame),) or not np.isfinite(scores).all():
        raise ValueError("Invalid scores")
    result = frame.loc[:, KEYS].copy().reset_index(drop=True)
    result["ranking_raw_score"] = scores
    result = result.sort_values(
        ["race_id", "ranking_raw_score", "horse_id"], ascending=[True, False, True], kind="stable"
    )
    groups = result.groupby("race_id")["ranking_raw_score"]
    mean, std = groups.transform("mean"), groups.transform(lambda x: x.std(ddof=0))
    result["ranking_normalized_score"] = (
        (result.ranking_raw_score - mean) / std.replace(0, np.nan)
    ).fillna(0)
    result["ranking_within_race_rank"] = result.groupby("race_id").cumcount() + 1
    result["runner_count"] = groups.transform("size")
    return result.sort_index().reset_index(drop=True)


def make_oof(
    frame: pd.DataFrame,
    values: np.ndarray,
    provenance: dict[str, str],
    *,
    kind: Literal["ranking", "plc"],
    expected_feature_hash: str = FEATURE_HASH,
    expected_contract_version: str = VERSION,
) -> pd.DataFrame:
    if kind == "ranking":
        result = normalize_scores(frame, values)
    else:
        result = frame.loc[:, KEYS].copy().reset_index(drop=True)
        result["plc_probability"] = values
        result["plc_within_race_rank"] = normalize_scores(frame, values)[
            "ranking_within_race_rank"
        ].to_numpy()
    expected = expected_oof(frame)
    result = result.merge(expected, on=KEYS, how="left", validate="one_to_one")
    for key in PROVENANCE:
        result[key] = provenance[key]
    validate_oof(
        result,
        expected,
        kind=kind,
        expected_feature_hash=expected_feature_hash,
        expected_contract_version=expected_contract_version,
    )
    return result


def validate_oof(
    frame: pd.DataFrame,
    expected: pd.DataFrame,
    *,
    kind: Literal["ranking", "plc"],
    expected_feature_hash: str = FEATURE_HASH,
    expected_contract_version: str = VERSION,
) -> None:
    columns = (
        JOIN_KEYS
        + PROVENANCE
        + (
            RANK_COLUMNS + ["runner_count"]
            if kind == "ranking"
            else ["plc_probability", "plc_within_race_rank"]
        )
    )
    if not set(columns) <= set(frame.columns) or frame[columns].isna().any().any():
        raise ValueError("Incomplete OOF schema")
    validate_rows(frame, labels=False)
    validate_rows(expected, labels=False)
    dates = pd.to_datetime(frame.race_date).dt.date
    for fold_id, group in frame.groupby("fold_id"):
        spec = next((s for s in DEVELOPMENT_FOLDS if s.fold_id == fold_id), None)
        if (
            spec is None
            or not (
                (dates.loc[group.index] >= spec.evaluation_start)
                & (dates.loc[group.index] < spec.evaluation_end_exclusive)
            ).all()
        ):
            raise ValueError("OOF fold/date mismatch or in-sample rows")
    # String canonical dates make date objects and serialized ISO dates interoperable.
    left, right = frame[JOIN_KEYS].copy(), expected[JOIN_KEYS].copy()
    left["race_date"] = pd.to_datetime(left.race_date).dt.strftime("%Y-%m-%d")
    right["race_date"] = pd.to_datetime(right.race_date).dt.strftime("%Y-%m-%d")
    joined = left.merge(right, on=JOIN_KEYS, how="outer", indicator=True, validate="one_to_one")
    if not joined._merge.eq("both").all():
        raise ValueError("OOF coverage/key mismatch")
    for name in PROVENANCE:
        if frame[name].nunique() != 1 or not isinstance(frame[name].iloc[0], str):
            raise ValueError("Inconsistent provenance")
    if not frame.feature_hash.eq(expected_feature_hash).all():
        raise ValueError("OOF Feature hash mismatch")
    if not frame.contract_version.eq(expected_contract_version).all():
        raise ValueError("OOF contract version mismatch")
    for name in HASHES:
        if not re.fullmatch(r"[0-9a-f]{64}", frame[name].iloc[0]):
            raise ValueError("Malformed provenance hash")
    if kind == "plc":
        if not frame.plc_probability.between(0, 1).all():
            raise ValueError("Invalid PLC probability")
        ranks = normalize_scores(frame, frame.plc_probability.to_numpy(dtype=float))
        if not np.array_equal(frame.plc_within_race_rank, ranks.ranking_within_race_rank):
            raise ValueError("PLC rank mismatch")
    else:
        check = normalize_scores(frame, frame.ranking_raw_score.to_numpy(dtype=float))
        if not np.isfinite(frame[RANK_COLUMNS].to_numpy(dtype=float)).all():
            raise ValueError("Nonfinite OOF scores")
        for name in ["ranking_within_race_rank", "runner_count"]:
            if not np.array_equal(frame[name].to_numpy(), check[name].to_numpy()):
                raise ValueError("OOF rank/group mismatch")
        if not np.allclose(
            frame.ranking_normalized_score, check.ranking_normalized_score, rtol=0, atol=1e-12
        ):
            raise ValueError("OOF normalized score mismatch")
        if frame.runner_count.lt(3).any():
            raise ValueError("Incomplete race")


def join_oof(ranking: pd.DataFrame, plc: pd.DataFrame, expected: pd.DataFrame) -> pd.DataFrame:
    """Full coverage join for future Top1/Top3 disagreement; no hit metrics computed."""
    validate_oof(ranking, expected, kind="ranking")
    validate_oof(plc, expected, kind="plc")
    for name in ["feature_hash", "source_db_hash", "snapshot_hash"]:
        if ranking[name].iloc[0] != plc[name].iloc[0]:
            raise ValueError("Comparator source/Feature provenance mismatch")
    left, right = ranking.copy(), plc.copy()
    for part in [left, right]:
        part["race_date"] = pd.to_datetime(part.race_date).dt.strftime("%Y-%m-%d")
    return left.merge(
        right, on=JOIN_KEYS, how="outer", validate="one_to_one", suffixes=("_ranking", "_plc")
    )


def write_oof(
    paths: RankingPaths,
    relative: str,
    frame: pd.DataFrame,
    expected: pd.DataFrame,
    *,
    kind: Literal["ranking", "plc"],
    expected_feature_hash: str = FEATURE_HASH,
    expected_contract_version: str = VERSION,
) -> Path:
    validate_oof(
        frame,
        expected,
        kind=kind,
        expected_feature_hash=expected_feature_hash,
        expected_contract_version=expected_contract_version,
    )
    path = paths.output(relative)
    manifest = paths.output(relative + ".json")
    if path.exists() or manifest.exists():
        raise FileExistsError("Do not overwrite an OOF run")
    path.parent.mkdir(parents=True, exist_ok=True)
    path = paths.output(relative)
    serialized = frame.copy()
    serialized["race_date"] = pd.to_datetime(frame.race_date).dt.strftime("%Y-%m-%d")
    with path.open("x", encoding="utf-8", newline="") as stream:
        serialized.to_csv(stream, index=False, float_format="%.17g")
    payload: dict[str, Any] = {
        "schema_version": expected_contract_version,
        "kind": kind,
        "start": serialized.race_date.min(),
        "end": serialized.race_date.max(),
        "sha256": file_hash(path),
    }
    paths.write_json(relative + ".json", payload)
    return path


def load_oof(
    path: Path,
    expected: pd.DataFrame,
    *,
    kind: Literal["ranking", "plc"],
    expected_feature_hash: str = FEATURE_HASH,
    expected_contract_version: str = VERSION,
) -> pd.DataFrame:
    """Read only a declared Development artifact; reject later windows before opening CSV."""
    meta = json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))
    if (
        meta["schema_version"] != expected_contract_version
        or meta["kind"] != kind
        or not ("2023-07-01" <= meta["start"] <= meta["end"] < "2024-07-01")
    ):
        raise ValueError("Not a Development OOF artifact")
    if file_hash(path) != meta["sha256"]:
        raise ValueError("OOF artifact hash mismatch")
    frame = pd.read_csv(
        path,
        dtype=dict.fromkeys(JOIN_KEYS + PROVENANCE, "string"),
        float_precision="round_trip",
        keep_default_na=False,
    )
    validate_oof(
        frame,
        expected,
        kind=kind,
        expected_feature_hash=expected_feature_hash,
        expected_contract_version=expected_contract_version,
    )
    return frame


def build_provenance(
    paths: RankingPaths,
    frame: pd.DataFrame,
    run_id: str,
    *,
    kind: Literal["ranking", "plc"],
) -> dict[str, str]:
    """Hash exact source inputs/targets and code, including uncommitted implementation."""
    import hashlib

    from kra_analytics.ranking_research import l133_contract, model_config, validate_environment

    validate_environment(paths.root)
    contract = l133_contract(paths.root)
    validate_rows(frame)
    columns = [*KEYS, *contract.inputs, "place_hit", "snapshot_id"]
    canonical = frame.loc[:, columns].sort_values(KEYS).copy()
    canonical["race_date"] = pd.to_datetime(canonical.race_date).dt.strftime("%Y-%m-%d")
    snapshot_hash = hashlib.sha256(
        canonical.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode()
    ).hexdigest()
    code_files = sorted((paths.root / "src/kra_analytics").glob("*.py"))
    code_files += [paths.root / "pyproject.toml", paths.root / "ranking-requirements.lock.txt"]
    code_hash = hashlib.sha256(
        "\n".join(
            f"{p.relative_to(paths.root).as_posix()}:{file_hash(p)}" for p in code_files
        ).encode()
    ).hexdigest()
    config = (
        model_config()
        if kind == "ranking"
        else {
            "procedure": "raw_L133_build_v2_pipeline",
            "calibration": False,
            "model": "LogisticRegression",
            "C": 1,
            "solver": "lbfgs",
            "max_iter": 2000,
            "random_state": 20260817,
        }
    )
    config["preprocessor"] = "sealed_l133_ohe_median_count0_standardscaler"
    config["folds"] = [str(spec) for spec in DEVELOPMENT_FOLDS]
    return {
        "contract_version": VERSION,
        "feature_hash": FEATURE_HASH,
        "source_db_hash": file_hash(paths.source),
        "snapshot_hash": snapshot_hash,
        "code_hash": code_hash,
        "config_hash": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "contract_hash": file_hash(paths.root / "docs/ranking-research-v1-contract.md"),
        "run_id": run_id,
        "candidate_id": "RANK_L133_PLC_LGBM_V1" if kind == "ranking" else "L133_RAW",
    }
