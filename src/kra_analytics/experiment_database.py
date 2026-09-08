from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb
from duckdb import DuckDBPyConnection

from kra_analytics.paths import ProjectPaths


@dataclass(frozen=True)
class ExperimentDatabasePaths:
    source: Path
    experiment: Path


def resolve_experiment_database_paths(
    *, paths: ProjectPaths | None = None
) -> ExperimentDatabasePaths:
    project_paths = paths or ProjectPaths.from_root()
    source_value = os.getenv("KRA_SOURCE_DATABASE_PATH") or os.getenv("KRA_DATABASE_PATH")
    output_value = os.getenv("KRA_EXPERIMENT_DATABASE_PATH")
    if not source_value:
        raise ValueError("KRA_SOURCE_DATABASE_PATH (or KRA_DATABASE_PATH) is required")
    if not output_value:
        raise ValueError("KRA_EXPERIMENT_DATABASE_PATH is required")
    source = Path(source_value).expanduser().resolve()
    experiment = Path(output_value).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source database does not exist: {source}")
    if source == experiment:
        raise ValueError("Source and experiment databases must be different files")
    if not experiment.is_relative_to(project_paths.root):
        raise ValueError("Experiment database must be inside the active worktree")
    return ExperimentDatabasePaths(source=source, experiment=experiment)


@contextmanager
def connect_source_database(
    *, database_paths: ExperimentDatabasePaths
) -> Iterator[DuckDBPyConnection]:
    connection = duckdb.connect(str(database_paths.source), read_only=True)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def connect_experiment_database(
    *, database_paths: ExperimentDatabasePaths, paths: ProjectPaths | None = None
) -> Iterator[DuckDBPyConnection]:
    project_paths = paths or ProjectPaths.from_root()
    if database_paths.source == database_paths.experiment:
        raise ValueError("Source and experiment databases must be different files")
    if not database_paths.experiment.is_relative_to(project_paths.root):
        raise ValueError("Experiment database must be inside the active worktree")
    database_paths.experiment.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_paths.experiment))
    try:
        yield connection
    finally:
        connection.close()
