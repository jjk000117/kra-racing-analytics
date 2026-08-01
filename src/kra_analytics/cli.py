from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

import typer

from kra_analytics import __version__
from kra_analytics.database import initialize_database, missing_required_schemas
from kra_analytics.paths import ProjectPaths

app = typer.Typer(help="KRA racing analytics local pipeline.", no_args_is_help=True)
database_app = typer.Typer(help="Initialize and inspect the local DuckDB warehouse.")
app.add_typer(database_app, name="database")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """Check the local project environment without exposing secrets."""
    paths = ProjectPaths.from_root()
    checks = {
        "project_root": paths.root.is_dir(),
        "project_charter": (paths.root / "PROJECT_CHARTER.md").is_file(),
        "python_3_12": sys.version_info[:2] == (3, 12),
        "sql_directory": paths.sql.is_dir(),
        "api_key_configured": bool(os.getenv("KRA_API_KEY")),
    }
    typer.echo(f"platform={platform.system()} {platform.release()}")
    typer.echo(f"python={platform.python_version()}")
    typer.echo(f"python_executable={Path(sys.executable).resolve()}")
    typer.echo(f"project_root={paths.root}")
    typer.echo(f"database={paths.database}")
    for name, passed in checks.items():
        status = "OK" if passed else ("OPTIONAL" if name == "api_key_configured" else "FAIL")
        typer.echo(f"{name}={status}")
    required_failures = [
        name for name, passed in checks.items() if not passed and name != "api_key_configured"
    ]
    if required_failures:
        raise typer.Exit(code=1)


@database_app.command("init")
def database_init() -> None:
    """Create DuckDB and the required schemas; safe to run repeatedly."""
    path = initialize_database()
    typer.echo(f"database_initialized={path}")


@database_app.command("check")
def database_check() -> None:
    """Verify that all required schemas exist."""
    missing = missing_required_schemas()
    if missing:
        typer.echo(f"missing_schemas={','.join(sorted(missing))}", err=True)
        raise typer.Exit(code=1)
    typer.echo("database_status=OK")
