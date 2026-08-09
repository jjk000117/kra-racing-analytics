from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Annotated

import typer

from kra_analytics import __version__
from kra_analytics.canonical import audit_canonical, build_canonical
from kra_analytics.collectors.api4_3 import (
    ALLOWED_MEETS,
    Api43Collector,
    audit_batch,
    get_api_key,
)
from kra_analytics.collectors.api179_1 import Api179Collector
from kra_analytics.database import initialize_database, missing_required_schemas
from kra_analytics.feature_snapshot import audit_feature_snapshot, build_feature_snapshot
from kra_analytics.modeling import run_final_test_once, run_validation_and_refit
from kra_analytics.paths import ProjectPaths
from kra_analytics.staging import audit_staging_batch, load_staging_batch
from kra_analytics.star import audit_star, build_star

app = typer.Typer(help="KRA racing analytics local pipeline.", no_args_is_help=True)
database_app = typer.Typer(help="Initialize and inspect the local DuckDB warehouse.")
collect_app = typer.Typer(help="Collect immutable KRA OpenAPI Raw responses.")
staging_app = typer.Typer(help="Load immutable Raw items into DuckDB Staging.")
canonical_app = typer.Typer(help="Build and audit standardized Canonical tables.")
star_app = typer.Typer(help="Build and audit the analytics Star Schema and marts.")
feature_app = typer.Typer(help="Build and audit Point-in-Time model Feature Snapshots.")
model_app = typer.Typer(help="Run sealed chronological baseline-model workflows.")
app.add_typer(database_app, name="database")
app.add_typer(collect_app, name="collect")
app.add_typer(staging_app, name="staging")
app.add_typer(canonical_app, name="canonical")
app.add_typer(star_app, name="star")
app.add_typer(feature_app, name="feature")
app.add_typer(model_app, name="model")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """Check the local project environment without exposing secrets."""
    paths = ProjectPaths.from_root()
    try:
        get_api_key(paths)
        api_key_configured = True
    except RuntimeError:
        api_key_configured = False
    checks = {
        "project_root": paths.root.is_dir(),
        "project_charter": (paths.root / "PROJECT_CHARTER.md").is_file(),
        "python_3_12": sys.version_info[:2] == (3, 12),
        "sql_directory": paths.sql.is_dir(),
        "api_key_configured": api_key_configured,
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


@collect_app.command("sales")
def collect_sales(
    years: Annotated[list[int], typer.Option("--year", help="Request year; repeat as needed.")],
    meets: Annotated[list[int], typer.Option("--meet", help="1=Seoul, 3=Busan-Gyeongnam.")],
    page: Annotated[int, typer.Option(min=1, help="First page to request.")] = 1,
    page_size: Annotated[int, typer.Option(min=1, max=1000, help="Rows per API page.")] = 1000,
    all_pages: Annotated[bool, typer.Option(help="Continue through totalCount.")] = False,
    dry_run: Annotated[bool, typer.Option(help="Print the plan without writes.")] = False,
) -> None:
    """Collect API179_1 historical sales and confirmed-dividend pages."""
    if any(meet not in ALLOWED_MEETS for meet in meets):
        raise typer.BadParameter("--meet must be 1 or 3")
    if dry_run:
        typer.echo("api=API179_1")
        typer.echo(f"years={','.join(map(str, years))}")
        typer.echo(f"meets={','.join(map(str, meets))}")
        typer.echo(f"first_page={page}")
        typer.echo(f"page_size={page_size}")
        typer.echo(f"all_pages={all_pages}")
        typer.echo("writes=NONE")
        return
    outcome = Api179Collector(page_size=page_size).collect(
        years=years, meets=meets, all_pages=all_pages, page=page
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


@staging_app.command("load")
def staging_load(
    batch_id: str = typer.Argument(..., help="Completed collection batch identifier."),
) -> None:
    """Load one completed Raw batch; safe to run repeatedly."""
    outcome = load_staging_batch(batch_id)
    typer.echo(f"batch_id={outcome.batch_id}")
    typer.echo(f"api={outcome.api_name}")
    typer.echo(f"expected_rows={outcome.expected_rows}")
    typer.echo(f"staged_rows={outcome.staged_rows}")
    typer.echo(f"inserted_rows={outcome.inserted_rows}")


@staging_app.command("check")
def staging_check(
    batch_id: str = typer.Argument(..., help="Staged collection batch identifier."),
) -> None:
    """Reconcile Staging rows, Raw lineage, ordering, and parse flags."""
    issues = audit_staging_batch(batch_id)
    typer.echo(f"batch_id={batch_id}")
    typer.echo(f"issues={len(issues)}")
    for issue in issues:
        typer.echo(issue, err=True)
    if issues:
        raise typer.Exit(code=1)


@canonical_app.command("build")
def canonical_build(
    race_batch_id: Annotated[str, typer.Option(help="Staged API4_3 batch identifier.")],
    sales_batch_id: Annotated[str, typer.Option(help="Staged API179_1 batch identifier.")],
) -> None:
    """Rebuild Canonical and Quality tables in one transaction."""
    outcome = build_canonical(
        race_batch_id=race_batch_id,
        sales_batch_id=sales_batch_id,
    )
    typer.echo(f"transform_version={outcome.transform_version}")
    typer.echo(f"races={outcome.race_count}")
    typer.echo(f"runners={outcome.runner_count}")
    typer.echo(f"sales={outcome.sales_count}")
    typer.echo(f"winning_payouts={outcome.winning_payout_count}")
    typer.echo(f"issues={outcome.issue_count}")


@canonical_app.command("check")
def canonical_check() -> None:
    """Audit Canonical counts, finish policy, and source lineage."""
    issues = audit_canonical()
    typer.echo(f"issues={len(issues)}")
    for issue in issues:
        typer.echo(issue, err=True)
    if issues:
        raise typer.Exit(code=1)


@star_app.command("build")
def star_build() -> None:
    """Rebuild analytics dimensions, facts, and market marts."""
    outcome = build_star()
    typer.echo(f"transform_version={outcome.transform_version}")
    typer.echo(f"races={outcome.race_count}")
    typer.echo(f"sales={outcome.sales_count}")
    typer.echo(f"eligible_races={outcome.eligible_race_count}")
    typer.echo(f"market_sales={outcome.market_sales_count}")


@star_app.command("check")
def star_check() -> None:
    """Audit Star counts, mappings, relationships, and sales reconciliation."""
    issues = audit_star()
    typer.echo(f"issues={len(issues)}")
    for issue in issues:
        typer.echo(issue, err=True)
    if issues:
        raise typer.Exit(code=1)


@feature_app.command("build")
def feature_build() -> None:
    """Rebuild the approved 29-column place Feature Snapshot."""
    outcome = build_feature_snapshot()
    typer.echo(f"snapshot_version={outcome.snapshot_version}")
    typer.echo(f"rows={outcome.row_count}")
    typer.echo(f"races={outcome.race_count}")
    typer.echo(f"positives={outcome.positive_count}")
    typer.echo(f"no_horse_history={outcome.no_horse_history_count}")


@feature_app.command("check")
def feature_check() -> None:
    """Audit Snapshot grain, source agreement, state rules, and PIT boundaries."""
    issues = audit_feature_snapshot()
    typer.echo(f"issues={len(issues)}")
    for issue in issues:
        typer.echo(issue, err=True)
    if issues:
        raise typer.Exit(code=1)


@model_app.command("baseline-validation")
def model_baseline_validation() -> None:
    """Select on Validation and refit without reading or evaluating Final Test."""
    outcome = run_validation_and_refit()
    typer.echo(f"model_version={outcome.model_version}")
    typer.echo(f"snapshot_version={outcome.snapshot_version}")
    typer.echo(f"selected_procedure={outcome.selected_procedure}")
    typer.echo(f"train_rows={outcome.train_rows}")
    typer.echo(f"validation_rows={outcome.validation_rows}")
    typer.echo(f"refit_rows={outcome.refit_rows}")
    typer.echo(f"final_test_predictions_created={outcome.final_test_predictions_created}")
    typer.echo(f"output_directory={outcome.output_directory}")


@model_app.command("final-test-once")
def model_final_test_once() -> None:
    """Evaluate the exact sealed Pipeline on Final Test once without refitting."""
    outcome = run_final_test_once()
    typer.echo(f"model_version={outcome.model_version}")
    typer.echo(f"rows={outcome.row_count}")
    typer.echo(f"races={outcome.race_count}")
    typer.echo(f"macro_log_loss={outcome.model_macro_log_loss:.9f}")
    typer.echo(f"macro_brier={outcome.model_macro_brier:.9f}")
    typer.echo(f"result_path={outcome.result_path}")
