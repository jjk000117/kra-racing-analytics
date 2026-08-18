from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from kra_analytics.development_evaluation import verify_sealed_artifacts
from kra_analytics.feature_bundle_combination_experiment import _combined_contract
from kra_analytics.feature_bundles import BUNDLE_FEATURES
from kra_analytics.modeling_v2 import RANDOM_SEED
from kra_analytics.paths import ProjectPaths

CONTRACT_PATH = "docs/post-baseline-v2-improvement-validation-contract.json"
REGISTRY_PATH = "docs/post-baseline-v2-feature-bundle-registry.csv"
EXPECTED_FEATURE_HASH = "18297f138f759944995bb59bc9cf36f3cde55d81ceb52b45a42c43372b4da182"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_definitions(paths: ProjectPaths) -> list[dict[str, str]]:
    with (paths.root / REGISTRY_PATH).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected_names = set(BUNDLE_FEATURES["F1"] + BUNDLE_FEATURES["F3"])
    selected = [row for row in rows if row["feature_name"] in selected_names]
    if tuple(row["feature_name"] for row in selected) != (
        BUNDLE_FEATURES["F1"] + BUNDLE_FEATURES["F3"]
    ):
        raise ValueError("F1/F3 registry order differs from the sealed implementation")
    return selected


def build_improvement_validation_contract(paths: ProjectPaths | None = None) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    contracts = _combined_contract(project_paths)
    candidate = contracts["F1+F3"]
    if len(candidate.inputs) != 133 or candidate.feature_hash != EXPECTED_FEATURE_HASH:
        raise ValueError("The selected 133-Feature contract differs from development")
    definitions = _bundle_definitions(project_paths)
    base = contracts["B0"]
    bundle_registry = json.loads(
        (
            project_paths.exports
            / "modeling/post_baseline_v2_f1_f3_combination_development_v1/experiment_registry.json"
        ).read_text(encoding="utf-8")
    )
    if int(bundle_registry["validation_access_count"]) != 0:
        raise ValueError("Validation access budget is not unused")
    protection = json.loads(
        (project_paths.root / "docs/official-place-baseline-v2-protection.json").read_text(
            encoding="utf-8"
        )
    )
    baseline_hashes = verify_sealed_artifacts(project_paths, protection["artifacts"])
    protected_paths = {
        "feature_bundle_registry": project_paths.root / REGISTRY_PATH,
        "feature_bundle_implementation": project_paths.root
        / "src/kra_analytics/feature_bundles.py",
        "m1_result": project_paths.exports
        / "modeling/m1_histgradientboosting_development_v1/result.json",
        "independent_bundle_development_result": project_paths.exports
        / "modeling/post_baseline_v2_feature_bundle_development_v1/result.json",
        "f1_f3_development_result": project_paths.exports
        / "modeling/post_baseline_v2_f1_f3_combination_development_v1/result.json",
    }
    protected_hashes = {
        name: _sha256_file(path) for name, path in protected_paths.items()
    }
    contract: dict[str, Any] = {
        "contract_version": "post_baseline_v2_improvement_validation_v1",
        "status": "SEALED_BEFORE_ONE_TIME_VALIDATION",
        "candidate": {
            "name": "official_place_logistic_baseline_v2_f1_f3_candidate",
            "snapshot_table": "mart.place_feature_snapshot_v2_engineered_candidate",
            "target": "place_hit",
            "base_feature_count": len(base.inputs),
            "f1_feature_count": len(BUNDLE_FEATURES["F1"]),
            "f3_feature_count": len(BUNDLE_FEATURES["F3"]),
            "total_feature_count": len(candidate.inputs),
            "feature_hash": candidate.feature_hash,
            "feature_order": list(candidate.inputs),
            "f1_features": list(BUNDLE_FEATURES["F1"]),
            "f3_features": list(BUNDLE_FEATURES["F3"]),
            "bundle_definitions": definitions,
            "frozen_after_validation": True,
        },
        "date_contract": {
            "historical_warmup": ["2022-01-01", "2022-12-31"],
            "train": ["2023-01-01", "2024-06-30"],
            "validation": ["2024-07-01", "2025-06-30"],
            "post_selection_temporal_evaluation": ["2025-07-01", "2026-07-26"],
            "post_selection_access_allowed_now": False,
        },
        "preprocessing": {
            "fit_scope": "Train only; temporal OOF preprocessing is fold-train only",
            "categorical": "Train most-frequent imputation + OneHotEncoder(handle_unknown=ignore)",
            "ordinary_numeric": "Train median imputation + StandardScaler",
            "historical_count": "NULL means zero observations; fill 0 + StandardScaler",
            "new_f1_count": "NULL to 0 + StandardScaler",
            "new_f1_f3_continuous": "Train median imputation + StandardScaler",
            "new_missing_indicators": [],
            "validation_fit_forbidden": True,
        },
        "logistic": {
            "penalty": "l2",
            "C": 1.0,
            "solver": "lbfgs",
            "max_iter": 2000,
            "class_weight": None,
            "random_state": RANDOM_SEED,
            "warning_policy": (
                "record sklearn penalty deprecation separately; "
                "any ConvergenceWarning fails the run"
            ),
        },
        "calibration": {
            "candidates": ["logistic_raw", "logistic_temporal_oof_sigmoid"],
            "oof_rule": "first 3 months train; predict next 3 months; expand by 3 months",
            "strict_temporal_order": "max(training date) < min(prediction date)",
            "preprocessing_scope": "each OOF fold train only",
            "calibrator_fit_source": "Train-period temporal OOF raw probabilities only",
            "selection_rule": (
                "select sigmoid only when both Validation Macro Log Loss and Macro Brier "
                "are lower than raw; otherwise select raw"
            ),
            "other_calibration_methods_allowed": False,
            "intercept_slope_are_diagnostic_only": True,
        },
        "validation_comparison": {
            "baseline": "sealed official_place_logistic_baseline_v2 logistic_raw",
            "improvement_candidate": "selected raw-or-sigmoid F1+F3 procedure",
            "allowed_improvement_probabilities": [
                "f1_f3_logistic_raw",
                "f1_f3_logistic_temporal_oof_sigmoid",
            ],
            "primary_metrics": ["macro_log_loss", "macro_brier"],
            "secondary_metrics": [
                "micro_log_loss",
                "micro_brier",
                "calibration_intercept",
                "calibration_slope",
                "monthly_metrics",
                "predefined_segment_metrics",
            ],
            "predefined_segments": [
                "meet_code",
                "registered_runner_count",
                "race_grade",
                "distance_m",
            ],
            "additional_candidates_allowed": False,
        },
        "promotion_rule": {
            "PROMOTE": (
                "selected F1+F3 procedure improves both aggregate primary metrics versus B0 "
                "and improves each primary metric in at least half of observed Validation months"
            ),
            "CONDITIONAL": (
                "only one aggregate primary metric improves, or both improve but either monthly "
                "improvement count is below half of observed Validation months"
            ),
            "REJECT": "neither aggregate primary metric improves or clear generalization worsening",
            "small_effect_policy": (
                "report numerical advantage as small; do not overstate improvement"
            ),
            "rules_mutable_after_access": False,
        },
        "validation_access_budget": {
            "current_access_count": 0,
            "reserved_accesses": 1,
            "increment_only_when_validation_is_loaded": True,
            "repeat_access_after_candidate_change_allowed": False,
        },
        "after_validation": {
            "freeze_selected_features_preprocessing_model_and_calibration": True,
            "train_plus_validation_refit_only_after_selection": True,
            "post_selection_temporal_evaluation_allowed_during_validation": False,
            "new_feature_work_requires_new_version": True,
        },
        "development_evidence": {
            "B0": {"macro_log_loss": 0.5355382200270552, "macro_brier": 0.17847722067265764},
            "F1": {"macro_log_loss": 0.5343501847315164, "macro_brier": 0.17794197209263982},
            "F3": {"macro_log_loss": 0.5288638941151531, "macro_brier": 0.1762028368749426},
            "F1+F3": {"macro_log_loss": 0.5276852686137958, "macro_brier": 0.17574387858273974},
        },
        "protection": {
            "sealed_baseline_artifacts": baseline_hashes,
            "other_protected_hashes": protected_hashes,
        },
        "forbidden_during_sealing": [
            "validation data or target access",
            "model fitting or prediction",
            "2024-07-01 or later data access",
            "Feature or model contract changes",
            "Train+Validation refit",
            "post-selection temporal evaluation",
        ],
    }
    output = project_paths.root / CONTRACT_PATH
    output.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return contract


def validate_improvement_validation_contract(
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    project_paths = paths or ProjectPaths.from_root()
    path = project_paths.root / CONTRACT_PATH
    contract: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    expected = build_improvement_validation_contract(project_paths)
    if contract != expected:
        raise ValueError("Stored Validation contract differs from the current sealed inputs")
    return contract
