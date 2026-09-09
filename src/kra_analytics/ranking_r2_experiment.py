"""Execute the sealed Development-only R2 F3 ablation."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS
from kra_analytics.feature_bundles import F1_FEATURES, F3_FEATURES
from kra_analytics.modeling_v2 import V2FeatureContract
from kra_analytics.ranking_experiment import EXPECTED_FOLDS, TOLERANCE, protected_files
from kra_analytics.ranking_oof import (
    JOIN_KEYS,
    expected_oof,
    load_oof,
    make_oof,
    write_oof,
)
from kra_analytics.ranking_research import (
    KEYS,
    RankingPaths,
    file_hash,
    fit_ranker,
    l133_contract,
    load_dataset,
    model_config,
    prepare_fold,
    ranking_metrics,
    validate_environment,
)

VERSION = "ranking_r2_f3_ablation_v1"
CANDIDATE = "RANK_L123_NO_F3_PLC_LGBM_R2"
FEATURE_HASH = "0b0c545fb5a2135cbd4b8362e3c7bd72231f05b43dbfdfaccec64198dc3469cc"
R1_RUN = "data/exports/modeling/ranking_research_v1/ranking_v1_development_20260909"
CONTRACT_PATH = "docs/ranking-r2-f3-ablation-contract.json"
PRIMARY = "macro_ndcg_at_3"
RECALL = "macro_recall_at_3"


def r2_contract(root: Path) -> V2FeatureContract:
    base = l133_contract(root)
    sealed = json.loads((root / CONTRACT_PATH).read_text(encoding="utf-8"))
    removed = tuple(sealed["candidate"]["removed_f3"])
    inputs = tuple(name for name in base.inputs if name not in set(removed))
    computed = hashlib.sha256(("\n".join(inputs) + "\n").encode()).hexdigest()
    if (
        removed != F3_FEATURES
        or len(removed) != 10
        or len(inputs) != len(set(inputs)) != 123
        or any(name not in inputs for name in F1_FEATURES)
        or any(name in inputs for name in F3_FEATURES)
        or set(base.inputs) - set(inputs) != set(F3_FEATURES)
        or computed != FEATURE_HASH
        or sealed["candidate"]["feature_hash"] != FEATURE_HASH
    ):
        raise ValueError("R2 Feature removal/name/order/hash contract mismatch")
    return V2FeatureContract(
        inputs=inputs,
        categorical=tuple(name for name in base.categorical if name in inputs),
        numeric=tuple(name for name in base.numeric if name in inputs),
        zero_count=tuple(name for name in base.zero_count if name in inputs),
        feature_hash=FEATURE_HASH,
    )


def _selection(frame: pd.DataFrame, left: str, right: str) -> dict[str, float]:
    rows: list[dict[str, float]] = []
    for _, race in frame.groupby("race_id", sort=True):
        a = race.sort_values([left, "horse_id"])
        b = race.sort_values([right, "horse_id"])
        aset, bset = set(a.horse_id.iloc[:3]), set(b.horse_id.iloc[:3])
        rows.append(
            {
                "top1_same_horse": float(a.horse_id.iloc[0] == b.horse_id.iloc[0]),
                "top3_jaccard": len(aset & bset) / len(aset | bset),
                "rank_spearman": float(np.corrcoef(a[left], a[right])[0, 1]),
            }
        )
    return cast(dict[str, float], pd.DataFrame(rows).mean().to_dict())


def _disagreement(frame: pd.DataFrame, ranking_column: str) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for label, cutoff in [("top1", 1), ("top3_any", 3)]:
        classes = []
        for _, race in frame.groupby("race_id", sort=True):
            plc = bool(race.nsmallest(cutoff, "plc_within_race_rank").place_hit.any())
            rank = bool(race.nsmallest(cutoff, ranking_column).place_hit.any())
            value = (
                "both_correct"
                if plc and rank
                else "plc_only"
                if plc
                else "ranking_only"
                if rank
                else "both_wrong"
            )
            classes.append(value)
        counts = pd.Series(classes).value_counts()
        summary[label] = {
            name: {
                "races": int(counts.get(name, 0)),
                "rate": float(counts.get(name, 0) / len(classes)),
            }
            for name in ["both_correct", "plc_only", "ranking_only", "both_wrong"]
        }
        summary[label]["oracle_descriptive_upper_bound"] = 1 - summary[label]["both_wrong"]["rate"]
    return summary


def _write_csv(paths: RankingPaths, relative: str, frame: pd.DataFrame) -> Path:
    path = paths.output(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        frame.to_csv(stream, index=False, float_format="%.17g")
    return path


def execute(root: Path, source: Path, run_id: str) -> Path:
    paths = RankingPaths(root, source)
    relative = f"data/exports/modeling/ranking_research_v1/{run_id}"
    output = paths.output(relative)
    if output.exists():
        raise FileExistsError("Run directory exists; never overwrite")
    environment = validate_environment(root)
    protected_before = protected_files(root, source)
    r1_result_path = root / R1_RUN / "result.json"
    r1_oof_path = root / R1_RUN / "ranking_oof.csv"
    plc_oof_path = root / R1_RUN / "plc_oof.csv"
    sealed = json.loads((root / CONTRACT_PATH).read_text(encoding="utf-8"))
    if file_hash(r1_result_path) != sealed["reference"]["result_json_sha256"]:
        raise ValueError("R1 result artifact hash mismatch")
    if file_hash(r1_oof_path) != sealed["reference"]["oof_sha256"]:
        raise ValueError("R1 OOF artifact hash mismatch")
    frame, _ = load_dataset(paths)
    contract = r2_contract(root)
    if (len(frame), frame.race_id.nunique()) != (28392, 2675):
        raise ValueError("Development population changed")
    expected = expected_oof(frame)
    if (len(expected), expected.race_id.nunique()) != (19168, 1821):
        raise ValueError("OOF population changed")
    r1_oof = load_oof(r1_oof_path, expected, kind="ranking")
    plc_oof = load_oof(plc_oof_path, expected, kind="plc")
    source_hash = file_hash(source)
    serialized_config = json.dumps(model_config(), sort_keys=True).encode()
    model_config_hash = hashlib.sha256(serialized_config).hexdigest()
    if model_config_hash != sealed["controlled_constants"]["model_config_sha256"]:
        raise ValueError("Model configuration hash mismatch")
    fold_audits = []
    for spec, counts in zip(DEVELOPMENT_FOLDS, EXPECTED_FOLDS, strict=True):
        train, evaluation, exclusions = prepare_fold(frame, spec.fold_id)
        observed = (
            len(train),
            train.race_id.nunique(),
            len(evaluation),
            evaluation.race_id.nunique(),
        )
        if (
            observed != counts
            or not exclusions.empty
            or train.race_date.max() >= evaluation.race_date.min()
        ):
            raise ValueError("Sealed fold changed")
        fold_audits.append({**asdict(spec), "counts": observed, "race_overlap": 0})
    fold_audits = json.loads(json.dumps(fold_audits, default=str))
    provenance = {
        "contract_version": VERSION,
        "feature_hash": FEATURE_HASH,
        "source_db_hash": source_hash,
        "code_hash": hashlib.sha256(
            (root / "src/kra_analytics/ranking_r2_experiment.py").read_bytes()
        ).hexdigest(),
        "config_hash": model_config_hash,
        "snapshot_hash": r1_oof.snapshot_hash.iloc[0],
        "contract_hash": file_hash(root / CONTRACT_PATH),
        "run_id": run_id,
        "candidate_id": CANDIDATE,
    }
    paths.write_json(
        relative + "/preflight.json",
        {
            "status": "SEALED_BEFORE_FIT",
            "contract": sealed,
            "feature_order": list(contract.inputs),
            "environment": environment,
            "source_sha256": source_hash,
            "r1_result_sha256": file_hash(r1_result_path),
            "r1_oof_sha256": file_hash(r1_oof_path),
            "folds": fold_audits,
            "provenance": provenance,
        },
    )
    metric_rows, race_parts, oof_parts, model_rows, importance_rows = [], [], [], [], []
    for spec in DEVELOPMENT_FOLDS:
        started = time.perf_counter()
        train, evaluation, exclusions = prepare_fold(frame, spec.fold_id)
        if not exclusions.empty:
            raise ValueError("Unexpected exclusions")
        model = fit_ranker(train, contract)
        scores = model.predict(evaluation)
        r2_oof = make_oof(
            evaluation,
            scores,
            provenance,
            kind="ranking",
            expected_feature_hash=FEATURE_HASH,
            expected_contract_version=VERSION,
        )
        fold_expected = expected.loc[expected.fold_id.eq(spec.fold_id)]
        write_oof(
            paths,
            relative + f"/folds/{spec.fold_id}/ranking.csv",
            r2_oof,
            fold_expected,
            kind="ranking",
            expected_feature_hash=FEATURE_HASH,
            expected_contract_version=VERSION,
        )
        oof_parts.append(r2_oof)
        target = evaluation[[*KEYS, "place_hit"]].copy()
        target["race_date"] = pd.to_datetime(target.race_date).dt.strftime("%Y-%m-%d")
        r1_fold = target.merge(
            r1_oof.loc[r1_oof.fold_id.eq(spec.fold_id), [*KEYS, "ranking_raw_score"]],
            on=KEYS,
            validate="one_to_one",
        )
        for label, values in [
            ("R1", r1_fold.ranking_raw_score.to_numpy(dtype=float)),
            ("R2", scores),
        ]:
            per_race, macro = ranking_metrics(evaluation, values)
            metric_rows.append({"fold_id": spec.fold_id, "model": label, **macro})
            per_race["fold_id"], per_race["model"] = spec.fold_id, label
            race_parts.append(per_race)
        names = model.preprocessor.get_feature_names_out()
        r1_models = json.loads(r1_result_path.read_text(encoding="utf-8"))["models"]
        r1_width = next(
            x["transformed_columns"] for x in r1_models if x["fold_id"] == spec.fold_id
        )
        if len(names) != r1_width - 10:
            raise ValueError("R2 transformed width is not R1 minus ten")
        booster = model.model.booster_
        for name, gain, split in zip(
            names,
            booster.feature_importance("gain"),
            booster.feature_importance("split"),
            strict=True,
        ):
            importance_rows.append(
                {"fold_id": spec.fold_id, "feature": name, "gain": gain, "split": int(split)}
            )
        model_path = model.save(paths, relative + f"/models/{spec.fold_id}.joblib")
        model_rows.append(
            {
                "fold_id": spec.fold_id,
                "model_sha256": file_hash(model_path),
                "trees": booster.num_trees(),
                "transformed_columns": len(names),
            }
        )
        print(f"{spec.fold_id} complete in {time.perf_counter()-started:.1f}s", flush=True)
    metrics = pd.DataFrame(metric_rows)
    table = metrics.pivot(index="fold_id", columns="model")
    primary = table[PRIMARY]["R2"] - table[PRIMARY]["R1"]
    recall = table[RECALL]["R2"] - table[RECALL]["R1"]
    keep = (
        float(primary.mean()) > TOLERANCE
        and int(primary.gt(TOLERANCE).sum()) >= 3
        and float(recall.mean()) >= -TOLERANCE
    )
    decision = "KEEP_F3_REMOVAL" if keep else "DROP_F3_REMOVAL"
    r2_all = pd.concat(oof_parts, ignore_index=True)
    r2_path = write_oof(
        paths,
        relative + "/ranking_oof.csv",
        r2_all,
        expected,
        kind="ranking",
        expected_feature_hash=FEATURE_HASH,
        expected_contract_version=VERSION,
    )
    r2_all = load_oof(
        r2_path,
        expected,
        kind="ranking",
        expected_feature_hash=FEATURE_HASH,
        expected_contract_version=VERSION,
    )
    targets = frame[[*KEYS, "place_hit"]].copy()
    targets["race_date"] = pd.to_datetime(targets.race_date).dt.strftime("%Y-%m-%d")
    joined = r2_all.merge(
        r1_oof[[*JOIN_KEYS, "ranking_within_race_rank"]],
        on=JOIN_KEYS,
        validate="one_to_one",
        suffixes=("_r2", "_r1"),
    )
    joined = joined.merge(
        plc_oof[[*JOIN_KEYS, "plc_within_race_rank"]],
        on=JOIN_KEYS,
        validate="one_to_one",
    )
    joined = joined.merge(targets, on=KEYS, validate="one_to_one")
    if len(joined) != len(expected) or joined.isna().any().any():
        raise ValueError("R1/R2/PLC OOF coverage mismatch")
    selection = _selection(joined, "ranking_within_race_rank_r1", "ranking_within_race_rank_r2")
    disagreement = _disagreement(joined, "ranking_within_race_rank_r2")
    _write_csv(paths, relative + "/fold_metrics.csv", metrics)
    _write_csv(paths, relative + "/race_metrics.csv", pd.concat(race_parts, ignore_index=True))
    importance = pd.DataFrame(importance_rows)
    _write_csv(paths, relative + "/feature_importance.csv", importance)
    protected_after = protected_files(root, source)
    if protected_before != protected_after or file_hash(source) != source_hash:
        raise ValueError("Protected artifact changed")
    result = {
        "status": "COMPLETE",
        "decision": decision,
        "primary_mean_delta": float(primary.mean()),
        "primary_improved_folds": int(primary.gt(TOLERANCE).sum()),
        "recall_mean_delta": float(recall.mean()),
        "fold_means": metrics.groupby("model").mean(numeric_only=True).to_dict(orient="index"),
        "fold_metrics": metrics.to_dict(orient="records"),
        "selection_r1_r2": selection,
        "r2_plc_disagreement": disagreement,
        "integrity": {
            "rows": len(joined),
            "races": int(joined.race_id.nunique()),
            "join_coverage": 1.0,
            "duplicate_keys": 0,
            "missing_predictions": 0,
            "rank_continuity": True,
        },
        "models": model_rows,
        "top_feature_importance": (
            importance.groupby("feature")[["gain", "split"]]
            .mean()
            .sort_values("gain", ascending=False)
            .head(20)
            .reset_index()
            .to_dict(orient="records")
        ),
        "source_sha256_before": source_hash,
        "source_sha256_after": file_hash(source),
        "protected_unchanged": True,
        "validation_accesses": 0,
    }
    paths.write_json(relative + "/result.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not args.run_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Use a simple run ID")
    print(execute(Path(__file__).resolve().parents[2], args.source, args.run_id))


if __name__ == "__main__":
    main()
