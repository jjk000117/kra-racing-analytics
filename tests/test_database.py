from pathlib import Path

from kra_analytics.database import (
    REQUIRED_SCHEMAS,
    initialize_database,
    missing_required_schemas,
)
from kra_analytics.paths import ProjectPaths


def make_paths(tmp_path: Path) -> ProjectPaths:
    sql = tmp_path / "sql"
    ddl = sql / "ddl"
    ddl.mkdir(parents=True)
    (ddl / "001_create_schemas.sql").write_text(
        "\n".join(f"CREATE SCHEMA IF NOT EXISTS {schema};" for schema in REQUIRED_SCHEMAS),
        encoding="utf-8",
    )
    return ProjectPaths(
        root=tmp_path,
        raw=tmp_path / "data" / "raw",
        quarantine=tmp_path / "data" / "quarantine",
        warehouse=tmp_path / "data" / "warehouse",
        exports=tmp_path / "data" / "exports",
        logs=tmp_path / "logs",
        sql=sql,
        database=tmp_path / "data" / "warehouse" / "test.duckdb",
    )


def test_initialize_database_creates_required_schemas(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)

    initialize_database(paths=paths)

    assert paths.database.is_file()
    assert missing_required_schemas(paths=paths) == set()


def test_initialize_database_is_idempotent(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)

    first = initialize_database(paths=paths)
    second = initialize_database(paths=paths)

    assert first == second
    assert missing_required_schemas(paths=paths) == set()
