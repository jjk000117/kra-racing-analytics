from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
from duckdb import DuckDBPyConnection

from kra_analytics.paths import ProjectPaths

REQUIRED_SCHEMAS = (
    "raw",
    "staging",
    "canonical",
    "quality",
    "analytics",
    "mart",
    "semantic",
)


@contextmanager
def connect_database(
    *, paths: ProjectPaths | None = None, read_only: bool = False
) -> Iterator[DuckDBPyConnection]:
    """Open and always close the project database connection."""
    project_paths = paths or ProjectPaths.from_root()
    if not read_only:
        project_paths.warehouse.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(project_paths.database), read_only=read_only)
    try:
        yield connection
    finally:
        connection.close()


def initialize_database(*, paths: ProjectPaths | None = None) -> Path:
    """Create the DuckDB file and apply ordered, idempotent DDL scripts."""
    project_paths = paths or ProjectPaths.from_root()
    project_paths.ensure_runtime_directories()
    ddl_directory = project_paths.sql / "ddl"
    scripts = sorted(ddl_directory.glob("*.sql"))
    if not scripts:
        raise FileNotFoundError(f"No DDL scripts found in {ddl_directory}")

    with connect_database(paths=project_paths) as connection:
        for script in scripts:
            connection.execute(script.read_text(encoding="utf-8"))
    return project_paths.database


def list_schemas(*, paths: ProjectPaths | None = None) -> set[str]:
    project_paths = paths or ProjectPaths.from_root()
    with connect_database(paths=project_paths, read_only=True) as connection:
        rows = connection.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
    return {str(row[0]) for row in rows}


def missing_required_schemas(*, paths: ProjectPaths | None = None) -> set[str]:
    return set(REQUIRED_SCHEMAS) - list_schemas(paths=paths)
