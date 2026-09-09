"""Execute the one sealed Development experiment. No tuning/calibration/ensemble fitting."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS
from kra_analytics.ranking_oof import (
    JOIN_KEYS,
    build_provenance,
    expected_oof,
    join_oof,
    load_oof,
    make_oof,
    write_oof,
)
from kra_analytics.ranking_research import (
    KEYS,
    VERSION,
    RankingPaths,
    file_hash,
    load_dataset,
    model_config,
    prepare_fold,
    ranking_metrics,
    run_plc_fold,
    run_ranker_fold,
    validate_environment,
)

TOLERANCE = 1e-12
PRIMARY = "macro_ndcg_at_3"
RECALL = "macro_recall_at_3"
EXPECTED_FOLDS = [
    (9224, 854, 4458, 427),
    (13682, 1281, 5229, 494),
    (18911, 1775, 4707, 432),
    (23618, 2207, 4774, 468),
]


def decision(fold_metrics: pd.DataFrame) -> dict[str, Any]:
    """Equal-weight mean of four paired fold deltas, fixed before seeing scores."""
    expected = {(s.fold_id, m) for s in DEVELOPMENT_FOLDS for m in ["L133", "LambdaRank"]}
    if (
        set(zip(fold_metrics.fold_id, fold_metrics.model, strict=True)) != expected
        or len(fold_metrics) != 8
        or not np.isfinite(fold_metrics[[PRIMARY, RECALL]].to_numpy()).all()
    ):
        raise ValueError("INVALID experiment: incomplete/nonfinite paired metrics")
    table = fold_metrics.pivot(index="fold_id", columns="model", values=[PRIMARY, RECALL])
    primary = table[PRIMARY]["LambdaRank"] - table[PRIMARY]["L133"]
    recall = table[RECALL]["LambdaRank"] - table[RECALL]["L133"]
    keep = (
        float(primary.mean()) > TOLERANCE
        and int(primary.gt(TOLERANCE).sum()) >= 3
        and float(recall.mean()) >= -TOLERANCE
    )
    return {
        "decision": "KEEP_RANKING_V1" if keep else "DROP_RANKING_V1",
        "primary_mean_delta": float(primary.mean()),
        "primary_improved_folds": int(primary.gt(TOLERANCE).sum()),
        "recall_mean_delta": float(recall.mean()),
        "tolerance": TOLERANCE,
        "aggregation": "equal-weight mean of four race-macro fold metrics",
    }


def disagreement(joined: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Descriptive diagnostics on a previously validated complete OOF join, never a selector."""
    required = [*JOIN_KEYS, "place_hit", "plc_within_race_rank", "ranking_within_race_rank"]
    if joined[required].isna().any().any() or joined.duplicated(KEYS).any():
        raise ValueError("Invalid joined OOF")
    rows = []
    for race_id, race in joined.groupby("race_id", sort=True):
        plc = race.sort_values("plc_within_race_rank")
        rank = race.sort_values("ranking_within_race_rank")
        for ordered, column in [(plc, "plc_within_race_rank"), (rank, "ranking_within_race_rank")]:
            if ordered[column].tolist() != list(range(1, len(race) + 1)):
                raise ValueError("Incomplete rank continuity")
        if len(race) < 3 or not race.place_hit.isin([0, 1]).all():
            raise ValueError("Invalid race/target")
        pset, rset = set(plc.horse_id.iloc[:3]), set(rank.horse_id.iloc[:3])
        row: dict[str, Any] = {
            "race_id": race_id,
            "race_date": race.race_date.iloc[0],
            "fold_id": race.fold_id.iloc[0],
            "plc_top1": plc.horse_id.iloc[0],
            "ranking_top1": rank.horse_id.iloc[0],
            "plc_top3": json.dumps(plc.horse_id.iloc[:3].tolist()),
            "ranking_top3": json.dumps(rank.horse_id.iloc[:3].tolist()),
            "top1_same_horse": bool(plc.horse_id.iloc[0] == rank.horse_id.iloc[0]),
            "top3_intersection": len(pset & rset),
            "top3_same_set": pset == rset,
            "top3_jaccard": len(pset & rset) / len(pset | rset),
            "rank_spearman": float(
                np.corrcoef(race.plc_within_race_rank, race.ranking_within_race_rank)[0, 1]
            ),
        }
        for metric, p, r in [
            ("top1", bool(plc.place_hit.iloc[0]), bool(rank.place_hit.iloc[0])),
            ("top3_any", bool(plc.place_hit.iloc[:3].any()), bool(rank.place_hit.iloc[:3].any())),
        ]:
            row[metric + "_class"] = (
                "both_correct"
                if p and r
                else "plc_only"
                if p
                else "ranking_only"
                if r
                else "both_wrong"
            )
        rows.append(row)
    result = pd.DataFrame(rows)
    summary: dict[str, Any] = {"races": len(result)}
    for metric in ["top1", "top3_any"]:
        counts = result[metric + "_class"].value_counts()
        summary[metric] = {
            c: {"races": int(counts.get(c, 0)), "rate": float(counts.get(c, 0) / len(result))}
            for c in ["both_correct", "plc_only", "ranking_only", "both_wrong"]
        }
        summary[metric]["oracle_descriptive_upper_bound"] = (
            1 - summary[metric]["both_wrong"]["rate"]
        )
    for column in [
        "top1_same_horse",
        "top3_same_set",
        "top3_intersection",
        "top3_jaccard",
        "rank_spearman",
    ]:
        summary["mean_" + column] = float(result[column].mean())
    summary["correlation_definition"] = "Spearman on deterministic unique within-race ranks"
    summary["oracle_caveat"] = "oracle descriptive upper bound; not attainable ensemble performance"
    return result, summary


def _write_csv(paths: RankingPaths, relative: str, frame: pd.DataFrame) -> Path:
    path = paths.output(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path = paths.output(relative)
    with path.open("x", encoding="utf-8", newline="") as stream:
        frame.to_csv(stream, index=False, float_format="%.17g")
    return path


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), *args],
        text=True,
        encoding="utf-8",
    ).strip()


def worktree_states(root: Path) -> dict[str, Any]:
    result = {}
    for name in [
        "kra-racing-analytics",
        "kra-racing-analytics-plc",
        "kra-racing-analytics-ensemble",
    ]:
        other = root.parent / name
        result[name] = {
            "head": _git(other, "rev-parse", "HEAD"),
            "status": _git(other, "status", "--porcelain=v1"),
        }
    return result


def protected_files(root: Path, source: Path) -> dict[str, str]:
    files = [source, root / "docs/ranking-research-v1-contract.md"]
    for pattern in [
        "*t1*",
        "*ra1*",
        "*h133*",
        "*hgb*",
        "*improvement-validation*",
        "*f1-f3-one-time*",
    ]:
        files += list((root / "docs").glob(pattern))
    # Hash immutable artifacts as bytes only; never load Validation rows or predictions.
    exports = source.parents[1] / "exports/modeling"
    for name in [
        "post_baseline_v2_f1_f3_one_time_validation_v1",
        "post_baseline_v2_t1_development_v1",
        "post_baseline_v2_ra1_development_v1",
        "post_baseline_v2_h133_development_v1",
        "m1_histgradientboosting_development_v1",
        "official_place_logistic_baseline_v2",
    ]:
        directory = exports / name
        files += list(directory.glob("*.json"))
        files += list(directory.glob("*.joblib"))
    return {str(p.resolve()): file_hash(p) for p in sorted(set(files)) if p.is_file()}


def execute(root: Path, source: Path, run_id: str) -> Path:
    paths = RankingPaths(root, source)
    relative = f"data/exports/modeling/{VERSION}/{run_id}"
    output = paths.output(relative)
    if output.exists():
        raise FileExistsError("Run directory exists; never overwrite or silently rerun")
    versions = validate_environment(root)
    protected_before = protected_files(root, source)
    worktrees_before = worktree_states(root)
    frame, contract = load_dataset(paths)
    if (len(frame), frame.race_id.nunique()) != (28392, 2675):
        raise ValueError("Development population changed")
    expected = expected_oof(frame)
    if (len(expected), expected.race_id.nunique()) != (19168, 1821):
        raise ValueError("Expected OOF population changed")
    fold_audits = []
    for spec, counts in zip(DEVELOPMENT_FOLDS, EXPECTED_FOLDS, strict=True):
        train, evaluation, excluded = prepare_fold(frame, spec.fold_id)
        observed = (
            len(train),
            train.race_id.nunique(),
            len(evaluation),
            evaluation.race_id.nunique(),
        )
        if observed != counts or not excluded.empty:
            raise ValueError("Sealed fold population changed")
        fold_audits.append(
            {
                **asdict(spec),
                "train_rows": len(train),
                "train_races": int(train.race_id.nunique()),
                "eval_rows": len(evaluation),
                "eval_races": int(evaluation.race_id.nunique()),
                "actual_train_min": str(train.race_date.min()),
                "actual_train_max": str(train.race_date.max()),
                "actual_eval_min": str(evaluation.race_date.min()),
                "actual_eval_max": str(evaluation.race_date.max()),
                "race_overlap": 0,
            }
        )
    fold_audits = json.loads(json.dumps(fold_audits, default=str))
    rank_prov = build_provenance(paths, frame, run_id, kind="ranking")
    plc_prov = build_provenance(paths, frame, run_id, kind="plc")
    environment_hash = file_hash(root / "ranking-requirements.lock.txt")
    preflight = dict(
        status="SEALED_BEFORE_FIT",
        run_id=run_id,
        code_head=_git(root, "rev-parse", "HEAD"),
        code_status=_git(root, "status", "--porcelain=v1"),
        environment=versions,
        environment_hash=environment_hash,
        config=model_config(),
        feature_order=list(contract.inputs),
        ranking_provenance=rank_prov,
        plc_provenance=plc_prov,
        folds=fold_audits,
        protected_before=protected_before,
        other_worktrees_before=worktrees_before,
        policy="fixed candidate; no tuning/early stopping/calibration/Validation",
    )
    paths.write_json(relative + "/preflight.json", preflight)
    print("Preflight sealed; starting four fixed folds", flush=True)
    ranking_parts, plc_parts, metric_rows, race_metric_parts, warning_rows = [], [], [], [], []
    model_details = []
    # This reference is Development only; no Validation metric/prediction source is opened.
    reference_path = source.parents[1] / (
        "exports/modeling/post_baseline_v2_f1_f3_combination_development_v1/fold_metrics.csv"
    )
    historical = pd.read_csv(reference_path)
    historical = historical.loc[historical.experiment_id.eq("F1+F3")].set_index("fold_id")
    reproduction = []
    for spec in DEVELOPMENT_FOLDS:
        started = time.perf_counter()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            evaluation, scores, model, exclusions = run_ranker_fold(frame, root, spec.fold_id)
            plc_eval, probabilities = run_plc_fold(frame, root, spec.fold_id)
        if not evaluation[KEYS].equals(plc_eval[KEYS]) or not exclusions.empty:
            raise ValueError("Comparator eval mismatch")
        ranking = make_oof(evaluation, scores, rank_prov, kind="ranking")
        plc = make_oof(plc_eval, probabilities, plc_prov, kind="plc")
        for part in [ranking, plc]:
            part["environment_hash"] = environment_hash
        ranking_parts.append(ranking)
        plc_parts.append(plc)
        fold_expected = expected.loc[expected.fold_id.eq(spec.fold_id)]
        write_oof(
            paths,
            relative + f"/folds/{spec.fold_id}/ranking.csv",
            ranking,
            fold_expected,
            kind="ranking",
        )
        write_oof(
            paths, relative + f"/folds/{spec.fold_id}/plc.csv", plc, fold_expected, kind="plc"
        )
        model_path = model.save(paths, relative + f"/models/{spec.fold_id}.joblib")
        model_details.append(
            dict(
                fold_id=spec.fold_id,
                model_sha256=file_hash(model_path),
                resolved_booster_params=model.model.booster_.params,
                num_trees=model.model.booster_.num_trees(),
                transformed_columns=len(model.preprocessor.get_feature_names_out()),
                transformed_feature_names=model.preprocessor.get_feature_names_out().tolist(),
            )
        )
        for label, values in [("L133", probabilities), ("LambdaRank", scores)]:
            race_metrics, macro = ranking_metrics(evaluation, values)
            metric_rows.append(dict(fold_id=spec.fold_id, model=label, **macro))
            race_metrics["fold_id"], race_metrics["model"] = spec.fold_id, label
            race_metric_parts.append(race_metrics)
        # Probability loss is applied ONLY to L133. No calibrator is fitted even for diagnostics.
        y = evaluation.place_hit.to_numpy(dtype=int)
        p = np.clip(probabilities, 1e-15, 1 - 1e-15)
        losses = (
            pd.DataFrame(
                {
                    "race_id": evaluation.race_id,
                    "macro_log_loss": -(y * np.log(p) + (1 - y) * np.log(1 - p)),
                    "macro_brier": (probabilities - y) ** 2,
                }
            )
            .groupby("race_id")
            .mean()
            .mean()
        )
        for metric in ["macro_log_loss", "macro_brier"]:
            old = float(cast(Any, historical.loc[spec.fold_id, metric]))
            new = float(cast(Any, losses[metric]))
            reproduction.append(
                dict(
                    fold_id=spec.fold_id,
                    metric=metric,
                    historical=old,
                    reproduced=new,
                    delta=new - old,
                    within_1e_12=abs(new - old) <= 1e-12,
                )
            )
        warning_rows += [
            dict(fold_id=spec.fold_id, category=w.category.__name__, message=str(w.message))
            for w in caught
        ]
        print(f"{spec.fold_id} complete in {time.perf_counter() - started:.1f}s", flush=True)
    ranking_all = pd.concat(ranking_parts, ignore_index=True)
    plc_all = pd.concat(plc_parts, ignore_index=True)
    ranking_path = write_oof(
        paths, relative + "/ranking_oof.csv", ranking_all, expected, kind="ranking"
    )
    plc_path = write_oof(paths, relative + "/plc_oof.csv", plc_all, expected, kind="plc")
    # Validate serialized artifacts as handed off, not just in-memory values.
    ranking_all = load_oof(ranking_path, expected, kind="ranking")
    plc_all = load_oof(plc_path, expected, kind="plc")
    joined = join_oof(ranking_all, plc_all, expected)
    targets = expected.merge(
        frame[[*KEYS, "place_hit", "official_finish_rank", "result_status", "snapshot_id"]],
        on=KEYS,
        validate="one_to_one",
    )
    targets["race_date"] = pd.to_datetime(targets.race_date).dt.strftime("%Y-%m-%d")
    joined = joined.merge(targets, on=JOIN_KEYS, validate="one_to_one", how="left")
    if len(joined) != len(expected) or joined.place_hit.isna().any():
        raise ValueError("Incomplete OOF/target coverage before disagreement")
    _write_csv(paths, relative + "/oof_targets.csv", targets)
    race_diagnostics, diagnostic_summary = disagreement(joined)
    _write_csv(paths, relative + "/race_diagnostics.csv", race_diagnostics)
    metrics = pd.DataFrame(metric_rows)
    result_decision = decision(metrics)
    _write_csv(paths, relative + "/fold_metrics.csv", metrics)
    _write_csv(
        paths, relative + "/race_metrics.csv", pd.concat(race_metric_parts, ignore_index=True)
    )
    reproduction_frame = pd.DataFrame(reproduction)
    _write_csv(paths, relative + "/l133_reproduction.csv", reproduction_frame)
    means = metrics.groupby("model").mean(numeric_only=True)
    deltas = []
    for spec in DEVELOPMENT_FOLDS:
        f = metrics.loc[metrics.fold_id.eq(spec.fold_id)].set_index("model")
        for metric in [c for c in metrics.columns if c.startswith("macro_")]:
            base = float(cast(Any, f.loc["L133", metric]))
            candidate = float(cast(Any, f.loc["LambdaRank", metric]))
            deltas.append(
                dict(
                    fold_id=spec.fold_id,
                    metric=metric,
                    l133=base,
                    lambdarank=candidate,
                    delta=candidate - base,
                    relative_delta=(candidate - base) / base if base else None,
                )
            )
    _write_csv(paths, relative + "/fold_deltas.csv", pd.DataFrame(deltas))
    protected_after = protected_files(root, source)
    if protected_before != protected_after:
        raise ValueError("Protected source/artifact changed: result is INVALID")
    validate_environment(root)
    artifacts = {
        p.relative_to(output).as_posix(): file_hash(p)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    result = dict(
        status="COMPLETE",
        **result_decision,
        fold_means=means.to_dict(orient="index"),
        fold_deltas=deltas,
        disagreement=diagnostic_summary,
        integrity=dict(
            rows=len(joined),
            races=int(joined.race_id.nunique()),
            join_coverage=1.0,
            duplicate_keys=0,
            missing_predictions=0,
            serialized_oof_validated=True,
            rank_continuity=True,
        ),
        l133_reproduction=reproduction,
        historical_development_reference_sha256=file_hash(reference_path),
        models=model_details,
        warnings=warning_rows,
        source_sha256_before=protected_before[str(source.resolve())],
        source_sha256_after=protected_after[str(source.resolve())],
        protected_unchanged=True,
        other_worktrees_after=worktree_states(root),
        validation_accesses=0,
        artifacts=artifacts,
    )
    paths.write_json(relative + "/result.json", result)
    print(
        json.dumps(
            {
                "decision": result_decision,
                "fold_means": result["fold_means"],
                "disagreement": diagnostic_summary,
                "integrity": result["integrity"],
            },
            indent=2,
        ),
        flush=True,
    )
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
