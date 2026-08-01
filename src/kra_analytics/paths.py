from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_MARKER = "PROJECT_CHARTER.md"


def find_project_root(start: Path | None = None) -> Path:
    """Find the repository root without depending on the current shell directory."""
    configured = os.getenv("KRA_PROJECT_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not (root / PROJECT_MARKER).is_file():
            raise FileNotFoundError(f"KRA_PROJECT_ROOT does not contain {PROJECT_MARKER}: {root}")
        return root

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / PROJECT_MARKER).is_file():
            return candidate
    raise FileNotFoundError(f"Could not find {PROJECT_MARKER} from {current}")


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    raw: Path
    quarantine: Path
    warehouse: Path
    exports: Path
    logs: Path
    sql: Path
    database: Path

    @classmethod
    def from_root(cls, root: Path | None = None) -> ProjectPaths:
        resolved_root = (root or find_project_root()).resolve()
        configured_database = os.getenv("KRA_DATABASE_PATH", "data/warehouse/kra.duckdb")
        database = Path(configured_database).expanduser()
        if not database.is_absolute():
            database = resolved_root / database
        return cls(
            root=resolved_root,
            raw=resolved_root / "data" / "raw",
            quarantine=resolved_root / "data" / "quarantine",
            warehouse=resolved_root / "data" / "warehouse",
            exports=resolved_root / "data" / "exports",
            logs=resolved_root / "logs",
            sql=resolved_root / "sql",
            database=database.resolve(),
        )

    def ensure_runtime_directories(self) -> None:
        for path in (self.raw, self.quarantine, self.warehouse, self.exports, self.logs):
            path.mkdir(parents=True, exist_ok=True)
