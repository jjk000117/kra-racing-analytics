from pathlib import Path

from pytest import MonkeyPatch

from kra_analytics.paths import ProjectPaths, find_project_root


def test_find_project_root_from_nested_directory(tmp_path: Path) -> None:
    (tmp_path / "PROJECT_CHARTER.md").write_text("test", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == tmp_path.resolve()


def test_project_paths_use_root_relative_database(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("KRA_DATABASE_PATH", "data/warehouse/test.duckdb")
    paths = ProjectPaths.from_root(tmp_path)

    assert paths.database == (tmp_path / "data" / "warehouse" / "test.duckdb").resolve()
