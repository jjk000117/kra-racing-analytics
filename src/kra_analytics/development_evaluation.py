from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.base import clone  # type: ignore[import-untyped]
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]

from kra_analytics.database import connect_database
from kra_analytics.modeling_v2 import (
    SNAPSHOT_TABLE,
    TARGET_COLUMN,
    V2FeatureContract,
    build_v2_pipeline,
    load_feature_contract,
)
from kra_analytics.paths import ProjectPaths

DEVELOPMENT_START = date(2023, 1, 1)
DEVELOPMENT_END_EXCLUSIVE = date(2024, 7, 1)
REGISTRY_SCHEMA_VERSION = "1.0"
DEFAULT_REGISTRY = "data/exports/modeling/post_baseline_v2/development_registry.json"


class DevelopmentAccessError(ValueError):
    """Raised before a development query can cross the sealed date boundary."""


@dataclass(frozen=True)
class TemporalFoldSpec:
    fold_id: str
    train_start: date
    train_end_exclusive: date
    evaluation_start: date
    evaluation_end_exclusive: date


@dataclass(frozen=True)
class TemporalFoldAudit:
    fold_id: str
    train_start: str
    train_end: str
    evaluation_start: str
    evaluation_end: str
    train_races: int
    train_rows: int
    evaluation_races: int
    evaluation_rows: int
    transformed_columns: int
    preprocessing_fit_scope: str
    strict_temporal_ordering: bool


DEVELOPMENT_FOLDS = (
    TemporalFoldSpec(
        "fold_1", date(2023, 1, 1), date(2023, 7, 1), date(2023, 7, 1), date(2023, 10, 1)
    ),
    TemporalFoldSpec(
        "fold_2", date(2023, 1, 1), date(2023, 10, 1), date(2023, 10, 1), date(2024, 1, 1)
    ),
    TemporalFoldSpec(
        "fold_3", date(2023, 1, 1), date(2024, 1, 1), date(2024, 1, 1), date(2024, 4, 1)
    ),
    TemporalFoldSpec(
        "fold_4", date(2023, 1, 1), date(2024, 4, 1), date(2024, 4, 1), date(2024, 7, 1)
    ),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def enforce_development_window(*, start: date, end_exclusive: date) -> None:
    if start < DEVELOPMENT_START:
        raise DevelopmentAccessError("Development access cannot start before 2023-01-01")
    if end_exclusive > DEVELOPMENT_END_EXCLUSIVE:
        raise DevelopmentAccessError("Development access cannot read 2024-07-01 or later")
    if start >= end_exclusive:
        raise DevelopmentAccessError("Development start must precede end_exclusive")


def load_development_frame(
    *, paths: ProjectPaths, contract: V2FeatureContract | None = None
) -> pd.DataFrame:
    """Load only the sealed inner-development period; no caller-supplied dates allowed."""
    feature_contract = contract or load_feature_contract(paths)
    enforce_development_window(
        start=DEVELOPMENT_START, end_exclusive=DEVELOPMENT_END_EXCLUSIVE
    )
    columns = ("race_id", "horse_id", "race_date", *feature_contract.inputs, TARGET_COLUMN)
    query = f"""
        SELECT {", ".join(columns)}
        FROM {SNAPSHOT_TABLE}
        WHERE race_date >= ? AND race_date < ?
        ORDER BY race_date, race_id, horse_id
    """
    with connect_database(paths=paths, read_only=True) as connection:
        frame = connection.execute(
            query, [DEVELOPMENT_START, DEVELOPMENT_END_EXCLUSIVE]
        ).fetchdf()
    if frame.empty:
        raise ValueError("Development loader returned no rows")
    frame["race_date"] = pd.to_datetime(frame["race_date"]).dt.date
    if frame["race_date"].min() < DEVELOPMENT_START:
        raise DevelopmentAccessError("Loaded rows before the development boundary")
    if frame["race_date"].max() >= DEVELOPMENT_END_EXCLUSIVE:
        raise DevelopmentAccessError("Loaded rows at or after the Validation boundary")
    if frame.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("Duplicate race_id/horse_id rows in development data")
    if set(frame[TARGET_COLUMN].dropna().unique()) - {0, 1}:
        raise ValueError("Development target is not binary")
    frame.attrs["feature_hash"] = feature_contract.feature_hash
    frame.attrs["access_window"] = "2023-01-01/2024-06-30"
    return frame


def _fold_frames(frame: pd.DataFrame, spec: TemporalFoldSpec) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = frame[
        (frame["race_date"] >= spec.train_start)
        & (frame["race_date"] < spec.train_end_exclusive)
    ].copy()
    evaluation = frame[
        (frame["race_date"] >= spec.evaluation_start)
        & (frame["race_date"] < spec.evaluation_end_exclusive)
    ].copy()
    if train.empty or evaluation.empty:
        raise ValueError(f"{spec.fold_id} has an empty train or evaluation partition")
    if train["race_date"].max() >= evaluation["race_date"].min():
        raise ValueError(f"{spec.fold_id} violates strict temporal ordering")
    if set(train["race_id"]) & set(evaluation["race_id"]):
        raise ValueError(f"{spec.fold_id} shares races across partitions")
    return train, evaluation


def audit_temporal_folds(
    frame: pd.DataFrame, contract: V2FeatureContract
) -> list[TemporalFoldAudit]:
    """Fit only each fold preprocessor; never fit a classifier or create predictions."""
    audits: list[TemporalFoldAudit] = []
    for spec in DEVELOPMENT_FOLDS:
        train, evaluation = _fold_frames(frame, spec)
        pipeline = build_v2_pipeline(contract)
        preprocessor = clone(pipeline.named_steps["preprocessor"])
        if not isinstance(preprocessor, ColumnTransformer):
            raise TypeError("Expected a ColumnTransformer preprocessor")
        transformed_train = preprocessor.fit_transform(train.loc[:, contract.inputs])
        transformed_evaluation = preprocessor.transform(
            evaluation.loc[:, contract.inputs]
        )
        if transformed_train.shape[1] != transformed_evaluation.shape[1]:
            raise ValueError(f"{spec.fold_id} preprocessing column mismatch")
        audits.append(
            TemporalFoldAudit(
                fold_id=spec.fold_id,
                train_start=str(train["race_date"].min()),
                train_end=str(train["race_date"].max()),
                evaluation_start=str(evaluation["race_date"].min()),
                evaluation_end=str(evaluation["race_date"].max()),
                train_races=int(train["race_id"].nunique()),
                train_rows=len(train),
                evaluation_races=int(evaluation["race_id"].nunique()),
                evaluation_rows=len(evaluation),
                transformed_columns=int(transformed_train.shape[1]),
                preprocessing_fit_scope="fold_train_only",
                strict_temporal_ordering=True,
            )
        )
    return audits


class ExperimentRegistry:
    """Small append-oriented registry with explicit Validation-access accounting."""

    def __init__(self, path: Path, *, feature_hash: str) -> None:
        self.path = path
        self.feature_hash = feature_hash
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write(
                {
                    "schema_version": REGISTRY_SCHEMA_VERSION,
                    "development_window": ["2023-01-01", "2024-06-30"],
                    "validation_window": ["2024-07-01", "2025-06-30"],
                    "validation_access_policy": (
                        "explicit, counted, maximum once per frozen candidate"
                    ),
                    "experiments": [],
                }
            )

    def _read(self) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def register(
        self,
        *,
        experiment_id: str,
        model_config: dict[str, Any],
        feature_config: dict[str, Any],
    ) -> None:
        payload = self._read()
        if any(item["experiment_id"] == experiment_id for item in payload["experiments"]):
            raise ValueError(f"Duplicate experiment_id: {experiment_id}")
        payload["experiments"].append(
            {
                "experiment_id": experiment_id,
                "created_at_utc": datetime.now(UTC).isoformat(),
                "status": "REGISTERED",
                "model_config": model_config,
                "feature_config": feature_config,
                "feature_hash": self.feature_hash,
                "fold_metrics": {},
                "validation_access_count": 0,
                "validation_access_events": [],
            }
        )
        self._write(payload)

    def record_fold_metrics(
        self, *, experiment_id: str, fold_id: str, metrics: dict[str, float]
    ) -> None:
        if fold_id not in {spec.fold_id for spec in DEVELOPMENT_FOLDS}:
            raise ValueError(f"Unknown fold_id: {fold_id}")
        experiment = self._experiment(experiment_id)
        experiment["fold_metrics"][fold_id] = metrics
        self._persist_experiment(experiment)

    def record_validation_access(self, *, experiment_id: str, reason: str) -> None:
        experiment = self._experiment(experiment_id)
        if experiment["status"] != "FROZEN_FOR_VALIDATION":
            raise ValueError("Candidate must be frozen before Validation access")
        if experiment["validation_access_count"] >= 1:
            raise ValueError("Validation access budget already exhausted")
        experiment["validation_access_count"] += 1
        experiment["validation_access_events"].append(
            {"accessed_at_utc": datetime.now(UTC).isoformat(), "reason": reason}
        )
        self._persist_experiment(experiment)

    def freeze_for_validation(self, *, experiment_id: str) -> None:
        experiment = self._experiment(experiment_id)
        if set(experiment["fold_metrics"]) != {spec.fold_id for spec in DEVELOPMENT_FOLDS}:
            raise ValueError("All four development-fold metrics are required before freezing")
        experiment["status"] = "FROZEN_FOR_VALIDATION"
        self._persist_experiment(experiment)

    def complete_development(self, *, experiment_id: str) -> None:
        experiment = self._experiment(experiment_id)
        if set(experiment["fold_metrics"]) != {spec.fold_id for spec in DEVELOPMENT_FOLDS}:
            raise ValueError("All four development-fold metrics are required before completion")
        experiment["status"] = "DEVELOPMENT_COMPLETE"
        self._persist_experiment(experiment)

    def _experiment(self, experiment_id: str) -> dict[str, Any]:
        payload = self._read()
        for item in payload["experiments"]:
            if item["experiment_id"] == experiment_id:
                return dict(item)
        raise KeyError(experiment_id)

    def _persist_experiment(self, experiment: dict[str, Any]) -> None:
        payload = self._read()
        payload["experiments"] = [
            experiment if item["experiment_id"] == experiment["experiment_id"] else item
            for item in payload["experiments"]
        ]
        self._write(payload)


def verify_sealed_artifacts(paths: ProjectPaths, expected: dict[str, str]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative_path, expected_hash in expected.items():
        path = paths.root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Missing sealed artifact: {relative_path}")
        observed_hash = _sha256_file(path)
        if observed_hash != expected_hash:
            raise ValueError(f"Sealed artifact hash mismatch: {relative_path}")
        observed[relative_path] = observed_hash
    return observed


def prepare_development_infrastructure(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contract = load_feature_contract(project_paths)
    frame = load_development_frame(paths=project_paths, contract=contract)
    fold_audits = audit_temporal_folds(frame, contract)
    protection_path = project_paths.root / "docs/official-place-baseline-v2-protection.json"
    protection = json.loads(protection_path.read_text(encoding="utf-8"))
    sealed_hashes = verify_sealed_artifacts(project_paths, protection["artifacts"])
    registry = ExperimentRegistry(
        project_paths.root / DEFAULT_REGISTRY, feature_hash=contract.feature_hash
    )
    result = {
        "development_window": ["2023-01-01", "2024-06-30"],
        "rows": len(frame),
        "races": int(frame["race_id"].nunique()),
        "feature_count": len(contract.inputs),
        "feature_hash": contract.feature_hash,
        "folds": [asdict(item) for item in fold_audits],
        "registry_path": str(registry.path.relative_to(project_paths.root)),
        "sealed_artifact_hashes": sealed_hashes,
        "classifier_fitted": False,
        "predictions_created": False,
        "validation_access_count": 0,
    }
    output = project_paths.exports / "validation/post_baseline_v2_development_infrastructure"
    output.mkdir(parents=True, exist_ok=True)
    (output / "infrastructure_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
