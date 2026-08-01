from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Annotated

import typer

from kra_analytics import __version__
from kra_analytics.collectors.api4_3 import ALLOWED_MEETS, Api43Collector, audit_batch
from kra_analytics.database import initialize_database, missing_required_schemas
from kra_analytics.paths import ProjectPaths

app = typer.Typer(help="KRA racing analytics local pipeline.", no_args_is_help=True)
database_app = typer.Typer(help="Initialize and inspect the local DuckDB warehouse.")
collect_app = typer.Typer(help="Collect immutable KRA OpenAPI Raw responses.")
app.add_typer(database_app, name="database")
app.add_typer(collect_app, name="collect")


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


@collect_app.command("race-results")
def collect_race_results(
    years: Annotated[list[int], typer.Option("--year", help="Request year; repeat as needed.")],
    meets: Annotated[list[int], typer.Option("--meet", help="1=Seoul, 3=Busan-Gyeongnam.")],
    page: Annotated[int, typer.Option(min=1, help="First page to request.")] = 1,
    page_size: Annotated[int, typer.Option(min=1, max=1000, help="Rows per API page.")] = 1000,
    all_pages: Annotated[bool, typer.Option(help="Continue through totalCount.")] = False,
    dry_run: Annotated[
        bool, typer.Option(help="Print the plan without API or database writes.")
    ] = False,
) -> None:
    """Collect API4_3 historical race-result pages."""
    if any(meet not in ALLOWED_MEETS for meet in meets):
        raise typer.BadParameter("--meet must be 1 or 3")
    if dry_run:
        typer.echo("api=API4_3")
        typer.echo(f"years={','.join(map(str, years))}")
        typer.echo(f"meets={','.join(map(str, meets))}")
        typer.echo(f"first_page={page}")
        typer.echo(f"page_size={page_size}")
        typer.echo(f"all_pages={all_pages}")
        typer.echo("writes=NONE")
        return

    outcome = Api43Collector(page_size=page_size).collect(
        years=years,
        meets=meets,
        all_pages=all_pages,
        page=page,
    )
    typer.echo(f"batch_id={outcome.batch_id}")
    typer.echo(f"requests={outcome.request_count}")
    typer.echo(f"successes={outcome.success_count}")
    typer.echo(f"no_data={outcome.no_data_count}")
    typer.echo(f"failures={outcome.failure_count}")
    if outcome.failure_count:
        raise typer.Exit(code=1)


@collect_app.command("audit")
def collect_audit(batch_id: str = typer.Argument(..., help="Collection batch identifier.")) -> None:
    """Verify Manifest counts and recompute every Raw file hash in a batch."""
    issues = audit_batch(batch_id=batch_id)
    typer.echo(f"batch_id={batch_id}")
    typer.echo(f"issues={len(issues)}")
    for issue in issues:
        typer.echo(issue, err=True)
    if issues:
        raise typer.Exit(code=1)
