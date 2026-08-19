from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Annotated

import typer

from kra_analytics import __version__
from kra_analytics.bootstrap_stability import run_bootstrap_stability_diagnostic
from kra_analytics.canonical import audit_canonical, build_canonical
from kra_analytics.collectors.api4_3 import (
    ALLOWED_MEETS,
    Api43Collector,
    audit_batch,
    get_api_key,
)
from kra_analytics.collectors.api179_1 import Api179Collector
from kra_analytics.database import initialize_database, missing_required_schemas
from kra_analytics.descriptive_validation_diagnostic import (
    run_descriptive_validation_diagnostic,
)
from kra_analytics.development_evaluation import prepare_development_infrastructure
from kra_analytics.drift_diagnostics import run_feature_drift_diagnostic
from kra_analytics.feature_bundle_combination_experiment import run_f1_f3_combination_experiment
from kra_analytics.feature_bundle_experiment import run_feature_bundle_development_experiment
from kra_analytics.feature_bundles import audit_feature_bundles, build_feature_bundles
from kra_analytics.feature_snapshot import audit_feature_snapshot, build_feature_snapshot
from kra_analytics.h133_experiment import run_h133_development_experiment
from kra_analytics.improvement_validation import run_one_time_improvement_validation
from kra_analytics.improvement_validation_contract import (
    build_improvement_validation_contract,
)
from kra_analytics.logistic_structure_diagnostics import run_logistic_structure_diagnostic
from kra_analytics.m1_experiment import run_m1_development_experiment
from kra_analytics.modeling import run_final_test_once, run_validation_and_refit
from kra_analytics.modeling_v2 import run_official_baseline_v2_validation
from kra_analytics.paths import ProjectPaths
from kra_analytics.race_aware_experiment import run_ra1_development_experiment
from kra_analytics.runner_count_diagnostics import run_runner_count_loss_diagnostic
from kra_analytics.staging import audit_staging_batch, load_staging_batch
from kra_analytics.star import audit_star, build_star
from kra_analytics.walk_forward import run_walk_forward_stability

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


@feature_app.command("build-post-baseline-bundles")
def feature_build_post_baseline_bundles() -> None:
    """Build and audit the sealed F1/F2/F3 candidate Feature bundles."""
    outcome = build_feature_bundles()
    typer.echo(f"rows={outcome.row_count}")
    typer.echo(f"races={outcome.race_count}")
    typer.echo(f"bundle_features={outcome.feature_count}")
    typer.echo(f"audit_issues={outcome.audit_issue_count}")
    typer.echo(f"output_directory={outcome.output_directory}")


@feature_app.command("check-post-baseline-bundles")
def feature_check_post_baseline_bundles() -> None:
    """Audit the built F1/F2/F3 candidate Feature bundles."""
    issues = audit_feature_bundles()
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


@model_app.command("official-v2-validation")
def model_official_v2_validation() -> None:
    """Select and seal official baseline v2 without reading the later evaluation period."""
    outcome = run_official_baseline_v2_validation()
    typer.echo(f"model_version={outcome.model_version}")
    typer.echo(f"selected_procedure={outcome.selected_procedure}")
    typer.echo(f"train_rows={outcome.train_rows}")
    typer.echo(f"train_races={outcome.train_races}")
    typer.echo(f"validation_rows={outcome.validation_rows}")
    typer.echo(f"validation_races={outcome.validation_races}")
    typer.echo(f"refit_rows={outcome.refit_rows}")
    typer.echo(f"contract_path={outcome.contract_path}")
    typer.echo(f"contract_payload_sha256={outcome.contract_payload_sha256}")
    typer.echo(
        "post_selection_predictions_created="
        f"{outcome.post_selection_predictions_created}"
    )


@model_app.command("walk-forward-stability")
def model_walk_forward_stability() -> None:
    """Run the fixed monthly expanding-window time-stability diagnostic."""
    outcome = run_walk_forward_stability()
    typer.echo(f"analysis_version={outcome.analysis_version}")
    typer.echo(f"folds={outcome.fold_count}")
    typer.echo(f"first_evaluation_month={outcome.first_evaluation_month}")
    typer.echo(f"last_evaluation_month={outcome.last_evaluation_month}")
    typer.echo(f"result_path={outcome.result_path}")


@model_app.command("prepare-development-evaluation")
def model_prepare_development_evaluation() -> None:
    """Audit the development loader and folds without fitting a classifier."""
    result = prepare_development_infrastructure()
    typer.echo(f"development_rows={result['rows']}")
    typer.echo(f"development_races={result['races']}")
    typer.echo(f"folds={len(result['folds'])}")
    typer.echo(f"validation_access_count={result['validation_access_count']}")
    typer.echo(f"classifier_fitted={result['classifier_fitted']}")
    typer.echo(f"predictions_created={result['predictions_created']}")


@model_app.command("run-m1-development")
def model_run_m1_development() -> None:
    """Run the sealed B0/M1 comparison inside the development period only."""
    result = run_m1_development_experiment()
    typer.echo(f"experiment_version={result['experiment_version']}")
    typer.echo(f"feature_count={result['feature_count']}")
    typer.echo(f"folds={len(result['fold_context'])}")
    typer.echo(f"validation_access_count={result['validation_access_count']}")
    typer.echo(f"sealed_artifacts_unchanged={result['sealed_artifacts_unchanged']}")


@model_app.command("run-feature-bundle-development")
def model_run_feature_bundle_development() -> None:
    """Compare sealed B0/F1/F2/F3 candidates inside the development period."""
    result = run_feature_bundle_development_experiment()
    typer.echo(f"experiment_version={result['experiment_version']}")
    typer.echo(f"development_rows={result['development_rows']}")
    typer.echo(f"development_races={result['development_races']}")
    typer.echo(f"validation_access_count={result['validation_access_count']}")
    for judgement in result["judgements"]:
        typer.echo(f"{judgement['experiment_id']}={judgement['judgement']}")


@model_app.command("run-f1-f3-combination-development")
def model_run_f1_f3_combination_development() -> None:
    """Compare the sole F1+F3 combination with its development references."""
    result = run_f1_f3_combination_experiment()
    typer.echo(f"experiment_version={result['experiment_version']}")
    typer.echo(f"development_rows={result['development_rows']}")
    typer.echo(f"development_races={result['development_races']}")
    typer.echo(f"validation_access_count={result['validation_access_count']}")
    typer.echo(f"judgement={result['decision']['judgement']}")
    typer.echo(
        "selected_development_candidate="
        f"{result['decision']['selected_development_candidate']}"
    )


@model_app.command("seal-improvement-validation-contract")
def model_seal_improvement_validation_contract() -> None:
    """Seal the 133-Feature candidate before any Validation access."""
    contract = build_improvement_validation_contract()
    typer.echo(f"status={contract['status']}")
    typer.echo(f"feature_count={contract['candidate']['total_feature_count']}")
    typer.echo(f"feature_hash={contract['candidate']['feature_hash']}")
    typer.echo(
        "validation_access_count="
        f"{contract['validation_access_budget']['current_access_count']}"
    )


@model_app.command("run-improvement-validation-once")
def model_run_improvement_validation_once() -> None:
    """Consume the sole Validation access for the sealed F1+F3 candidate."""
    result = run_one_time_improvement_validation()
    typer.echo(f"experiment_version={result['experiment_version']}")
    typer.echo(f"access_count={result['access_count_after']}")
    typer.echo(f"train_rows={result['train']['rows']}")
    typer.echo(f"validation_rows={result['validation']['rows']}")
    typer.echo(f"selected={result['raw_vs_sigmoid']['selected']}")
    typer.echo(f"promotion={result['promotion']['decision']}")


@model_app.command("diagnose-l133-validation-descriptively")
def model_diagnose_l133_validation_descriptively() -> None:
    """Reproduce sealed L133 predictions for descriptive Validation diagnostics."""
    result = run_descriptive_validation_diagnostic()
    typer.echo(f"diagnostic_version={result['diagnostic_version']}")
    typer.echo(f"validation_rows={result['validation']['rows']}")
    typer.echo(f"roc_auc={result['discrimination']['roc_auc']}")
    typer.echo(f"pr_auc={result['discrimination']['pr_auc_average_precision']}")


@model_app.command("diagnose-logistic-structure")
def model_diagnose_logistic_structure() -> None:
    """Diagnose 133-Feature Logistic residual structure in development folds only."""
    result = run_logistic_structure_diagnostic()
    typer.echo(f"development_rows={result['development_rows']}")
    typer.echo(f"oof_diagnostic_rows={result['oof_diagnostic_rows']}")
    typer.echo(f"feature_hash={result['feature_hash']}")
    typer.echo(
        "validation_access_count="
        f"{result['validation_access_count_before']}->"
        f"{result['validation_access_count_after']}"
    )


@model_app.command("run-h133-development")
def model_run_h133_development() -> None:
    """Compare the single conservative H133 candidate with L133 in development only."""
    result = run_h133_development_experiment()
    typer.echo(f"development_rows={result['development_rows']}")
    typer.echo(f"feature_hash={result['feature_contract']['feature_hash']}")
    typer.echo(f"judgement={result['decision']['judgement']}")
    typer.echo(
        "validation_access_count="
        f"{result['validation_access_count_before']}->"
        f"{result['validation_access_count_after']}"
    )


@model_app.command("run-ra1-development")
def model_run_ra1_development() -> None:
    """Run the single sealed RA1 pairwise experiment in development only."""
    result = run_ra1_development_experiment()
    typer.echo(f"development_rows={result['development_rows']}")
    typer.echo(f"development_races={result['development_races']}")
    typer.echo(f"feature_hash={result['contract']['feature_hash']}")
    typer.echo(f"judgement={result['decision']['judgement']}")
    typer.echo(f"validation_access_count={result['validation_access_count']}")


@model_app.command("diagnose-time-drift")
def model_diagnose_time_drift() -> None:
    """Compare stable and degraded periods without training or changing a model."""
    outcome = run_feature_drift_diagnostic()
    typer.echo(f"analysis_version={outcome.analysis_version}")
    typer.echo(f"stable_rows={outcome.stable_rows}")
    typer.echo(f"degraded_rows={outcome.degraded_rows}")
    typer.echo(f"result_path={outcome.result_path}")


@model_app.command("bootstrap-stability")
def model_bootstrap_stability() -> None:
    """Compare degraded monthly macro losses with stable-period race sampling variation."""
    outcome = run_bootstrap_stability_diagnostic()
    typer.echo(f"analysis_version={outcome.analysis_version}")
    typer.echo(f"stable_races={outcome.stable_races}")
    typer.echo(f"repetitions={outcome.repetitions}")
    typer.echo(f"result_path={outcome.result_path}")


@model_app.command("diagnose-runner-count-loss")
def model_diagnose_runner_count_loss() -> None:
    """Separate runner-count composition from within-segment loss movement."""
    outcome = run_runner_count_loss_diagnostic()
    typer.echo(f"analysis_version={outcome.analysis_version}")
    typer.echo(f"stable_races={outcome.stable_races}")
    typer.echo(f"degraded_races={outcome.degraded_races}")
    typer.echo(f"result_path={outcome.result_path}")
