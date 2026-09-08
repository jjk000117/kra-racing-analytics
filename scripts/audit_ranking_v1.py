"""Run structural audits only: never calls a model fit/predict or a performance metric."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from kra_analytics.development_evaluation import DEVELOPMENT_FOLDS
from kra_analytics.modeling_v2 import build_v2_pipeline
from kra_analytics.ranking_research import (
    VERSION,
    RankingPaths,
    file_hash,
    grouped,
    load_dataset,
    model_config,
    prepare_fold,
    validate_environment,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--output", default=f"data/exports/modeling/{VERSION}/structural/audit.json"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    paths = RankingPaths(root, args.source)
    paths.output(args.output)
    before = file_hash(paths.source)
    protected = [
        root / "docs/ranking-research-v1-contract.md",
        root / "docs/post-baseline-v2-improvement-validation-contract.json",
    ]
    protected += sorted(root.glob("docs/*t1*"))
    protected += sorted(root.glob("docs/*h133*"))
    protected += sorted(root.glob("docs/*ra1*"))
    protected += sorted(root.glob("docs/*hgb*"))
    ledger = (
        paths.source.parents[1]
        / "exports/modeling/post_baseline_v2_f1_f3_one_time_validation_v1/validation_access.json"
    )
    if ledger.is_file():
        protected.append(ledger)
    protected_before = {str(p): file_hash(p) for p in protected if p.is_file()}
    versions = validate_environment(root)
    frame, contract = load_dataset(paths)
    ordered, sizes = grouped(frame)
    counts = ordered.groupby("race_id").place_hit.agg(["sum", "count"])
    if len(frame) != 28392 or frame.race_id.nunique() != 2675:
        raise ValueError("Development population changed; investigate before any experiment")
    folds = []
    for spec in DEVELOPMENT_FOLDS:
        train, evaluation, exclusions = prepare_fold(frame, spec.fold_id)
        _, train_sizes = grouped(train)
        _, eval_sizes = grouped(evaluation)
        transformer = build_v2_pipeline(contract).named_steps["preprocessor"]
        x_train = transformer.fit_transform(train.loc[:, contract.inputs])
        x_eval = transformer.transform(evaluation.loc[:, contract.inputs])
        # Validate numeric train medians directly; no labels or evaluation statistics used.
        median_names = [n for n in contract.numeric if n not in contract.zero_count]
        medians = np.nanmedian(
            train.loc[:, median_names].to_numpy(dtype=float, na_value=np.nan), axis=0
        )
        observed = transformer.named_transformers_["numeric"].named_steps["imputer"].statistics_
        if not np.allclose(medians, observed, equal_nan=True):
            raise ValueError("Preprocessing train median mismatch")
        for matrix in (x_train, x_eval):
            numeric = matrix.data if hasattr(matrix, "toarray") else np.asarray(matrix)
            if not np.isfinite(numeric).all():
                raise ValueError("Nonfinite model input")
        folds.append(
            dict(
                fold_id=spec.fold_id,
                train_rows=len(train),
                train_races=len(train_sizes),
                eval_rows=len(evaluation),
                eval_races=len(eval_sizes),
                train_min=str(train.race_date.min()),
                train_max=str(train.race_date.max()),
                eval_min=str(evaluation.race_date.min()),
                eval_max=str(evaluation.race_date.max()),
                temporal_order=bool(train.race_date.max() < evaluation.race_date.min()),
                overlap=len(set(train.race_id) & set(evaluation.race_id)),
                exclusions=len(exclusions),
                transformed_columns=x_train.shape[1],
                matrix_type=type(x_train).__name__,
                train_only_medians_verified=True,
            )
        )
    after = file_hash(paths.source)
    if before != after:
        raise ValueError("Shared DB changed during structural audit")
    if protected_before != {str(p): file_hash(p) for p in protected if p.is_file()}:
        raise ValueError("Protected artifact changed")
    payload = dict(
        status="STRUCTURAL_ONLY_NO_MODEL_FIT",
        source=str(paths.source.resolve()),
        source_sha256_before=before,
        source_sha256_after=after,
        protected_sha256=protected_before,
        protected_unchanged=True,
        versions=versions,
        feature_hash=contract.feature_hash,
        feature_count=len(contract.inputs),
        categorical_count=len(contract.categorical),
        rows=len(frame),
        races=len(sizes),
        min_runner=int(sizes.min()),
        max_runner=int(sizes.max()),
        status_counts=frame.result_status.value_counts().to_dict(),
        positive_distribution={
            str(k): int(v) for k, v in counts["sum"].value_counts().sort_index().items()
        },
        no_positive=int(counts["sum"].eq(0).sum()),
        all_positive=int(counts["sum"].eq(counts["count"]).sum()),
        group_sum=int(sizes.sum()),
        folds=folds,
        config=model_config(),
        validation_rows_read=0,
        model_fits=0,
        predictions=0,
        performance_metrics=0,
    )
    path = paths.write_json(args.output, payload)
    print(
        json.dumps(
            {
                k: v
                for k, v in payload.items()
                if k not in ["versions", "protected_sha256", "config"]
            },
            indent=2,
        )
    )
    print(path)


if __name__ == "__main__":
    main()
