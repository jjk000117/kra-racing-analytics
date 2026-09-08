from pathlib import Path

import duckdb
import pytest

from kra_analytics.experiment_database import (
    ExperimentDatabasePaths,
    connect_source_database,
    resolve_experiment_database_paths,
)
from kra_analytics.paths import ProjectPaths


def test_source_connection_is_read_only(tmp_path: Path) -> None:
    source = tmp_path / "source.duckdb"
    connection = duckdb.connect(str(source))
    connection.execute("CREATE TABLE evidence(value INTEGER)")
    connection.close()
    paths = ExperimentDatabasePaths(source=source, experiment=tmp_path / "out.duckdb")
    with connect_source_database(database_paths=paths) as read_only:
        with pytest.raises(duckdb.Error):
            read_only.execute("CREATE TABLE forbidden(value INTEGER)")


def test_rejects_same_source_and_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.duckdb"
    source.touch()
    project = ProjectPaths.from_root(Path(__file__).parents[1])
    monkeypatch.setenv("KRA_SOURCE_DATABASE_PATH", str(source))
    monkeypatch.setenv("KRA_EXPERIMENT_DATABASE_PATH", str(source))
    with pytest.raises(ValueError, match="different"):
        resolve_experiment_database_paths(paths=project)


def test_rejects_output_outside_worktree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.duckdb"
    source.touch()
    project = ProjectPaths.from_root(Path(__file__).parents[1])
    monkeypatch.setenv("KRA_SOURCE_DATABASE_PATH", str(source))
    monkeypatch.setenv(
        "KRA_EXPERIMENT_DATABASE_PATH", str(project.root.parent / "outside.duckdb")
    )
    with pytest.raises(ValueError, match="active worktree"):
        resolve_experiment_database_paths(paths=project)


def test_requires_explicit_experiment_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.duckdb"
    source.touch()
    project = ProjectPaths.from_root(Path(__file__).parents[1])
    monkeypatch.setenv("KRA_SOURCE_DATABASE_PATH", str(source))
    monkeypatch.delenv("KRA_EXPERIMENT_DATABASE_PATH", raising=False)
    with pytest.raises(ValueError, match="KRA_EXPERIMENT_DATABASE_PATH"):
        resolve_experiment_database_paths(paths=project)
