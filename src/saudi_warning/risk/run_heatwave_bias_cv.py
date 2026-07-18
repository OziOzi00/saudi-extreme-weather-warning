"""Run locked leave-one-case-out heatwave bias correction on development only."""

from __future__ import annotations

import argparse
import csv
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from saudi_warning.risk.assess_development_freeze import assess_hazard
from saudi_warning.risk.engine import (
    evaluate_all,
    load_rule,
    load_statistics,
    load_summaries,
)
from saudi_warning.risk.run_development_review import (
    ARTIFACT_CREATED_AT,
    AUDIT_FIELDS,
    build_review,
    read_development_cases,
)


PAIR_OUTPUT_FIELDS = [
    "case_id",
    "case_role",
    "lead_time_hours",
    "region_id",
    "training_case_count",
    "fold_correction_degc",
    "raw_forecast_tmax_degc",
    "corrected_forecast_tmax_degc",
    "observed_tmax_degc",
    "event_threshold_degc",
    "raw_hot_day",
    "corrected_hot_day",
    "observed_hot_day",
]

ASSESSMENT_FIELDS = [
    "hazard",
    "method",
    "folds",
    "calibration_pair_count",
    "fold_correction_min_degc",
    "fold_correction_max_degc",
    "final_correction_degc",
    "event_cases",
    "control_cases",
    "event_target_windows",
    "candidate_hits",
    "target_window_recall",
    "control_target_windows",
    "candidate_correct_negatives",
    "target_window_specificity",
    "event_case_detection_fraction",
    "control_case_rejection_fraction",
    "observation_qc_statuses",
    "recommendation",
    "blocking_reasons",
    "independent_heatwave_opened",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_preregistration(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    allowed_statuses = {
        "preregistered_before_cv_evaluation",
        "input_extension_locked_before_aggregate_cv_evaluation",
    }
    if config.get("status") not in allowed_statuses:
        raise ValueError("bias-correction configuration is not locked before evaluation")
    if config.get("scope") != "development_only":
        raise ValueError("bias-correction scope must be development_only")
    if config.get("independent_heatwave_access") != "forbidden":
        raise ValueError("independent heatwave access is not forbidden")
    for item in config["locked_inputs"].values():
        source = Path(item["path"])
        if _sha256(source) != str(item["sha256"]).lower():
            raise ValueError(f"locked input SHA-256 mismatch: {source}")
    return config


def _calibration_pairs(
    pairs: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    estimator = config["estimator"]
    allowed = set(config["approved_heatwave_development_case_ids"])
    selected = pairs[
        pairs["case_id"].astype(str).isin(allowed)
        & (pairs["variable"] == estimator["calibration_variable"])
        & (pairs["aggregation"] == estimator["calibration_aggregation"])
        & (pairs["qc_status"] == estimator["calibration_qc_status"])
    ].copy()
    if set(selected["case_id"].astype(str)) != allowed:
        raise ValueError("calibration pairs do not cover the locked heatwave case set")
    if len(selected) != len(allowed) * 3:
        raise ValueError("expected exactly three calibration leads per heatwave case")
    selected["forecast_value"] = pd.to_numeric(selected["forecast_value"], errors="raise")
    selected["observed_value"] = pd.to_numeric(selected["observed_value"], errors="raise")
    selected["event_threshold"] = pd.to_numeric(
        selected["event_threshold"], errors="raise"
    )
    selected["error_degc"] = selected["observed_value"] - selected["forecast_value"]
    return selected


def _clip(value: float, config: dict[str, Any]) -> float:
    limits = config["estimator"]["correction_clip_degc"]
    return float(np.clip(value, float(limits["minimum"]), float(limits["maximum"])))


def _correct_case_summaries(
    summaries: list[dict[str, Any]],
    case: dict[str, str],
    correction: float,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    regions = set(case["target_region_ids"].split(";"))
    selected = [
        deepcopy(row)
        for row in summaries
        if str(row["initial_time"]) == case["initial_time"]
        and str(row["region_id"]) in regions
    ]
    expected = len(regions) * 3 * 11
    if len(selected) != expected:
        raise ValueError(
            f"incomplete held-out summary for {case['case_id']}: {len(selected)}"
        )
    fields = config["application"]["corrected_summary_fields"]
    for row in selected:
        if row["indicator"] != config["application"]["corrected_summary_variable"]:
            continue
        for field in fields:
            row[field] = float(row[field]) + correction
    return selected


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(
    config_path: Path,
    pairs_path: Path,
    catalog_path: Path,
    summaries_path: Path,
    statistics_path: Path,
    heavy_rule_path: Path,
    heat_rule_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    config = load_preregistration(config_path)
    pairs = pd.read_csv(pairs_path)
    calibration = _calibration_pairs(pairs, config)
    cases = [
        row
        for row in read_development_cases(catalog_path)
        if row["hazard"] == "heatwave"
    ]
    allowed_ids = set(config["approved_heatwave_development_case_ids"])
    if {case["case_id"] for case in cases} != allowed_ids:
        raise ValueError("catalog heatwave development cases diverge from preregistration")
    summaries = load_summaries(summaries_path)
    statistics = load_statistics(statistics_path)
    heavy_rule = load_rule(heavy_rule_path, "heavy_rain")
    heat_rule = load_rule(heat_rule_path, "heatwave")
    if heat_rule["status"] != "draft":
        raise ValueError("cross-validation expects the blocked draft heatwave rule")
    # The correction-only magnitude gate has no equivalent in the base rule.
    comparable = dict(config["success_gates"])
    comparable.pop("maximum_absolute_final_correction_degc")
    if heat_rule.get("freeze_gates") != comparable:
        raise ValueError("preregistered success gates diverge from base heatwave rule")

    pair_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    corrections: list[float] = []
    minimum_training = int(config["estimator"]["minimum_training_cases"])
    for case in cases:
        held_out = case["case_id"]
        training = calibration[calibration["case_id"].astype(str) != held_out]
        training_cases = int(training["case_id"].nunique())
        if training_cases < minimum_training:
            raise ValueError(f"insufficient training cases for fold {held_out}")
        correction = _clip(float(training["error_degc"].median()), config)
        corrections.append(correction)
        held_pairs = calibration[calibration["case_id"].astype(str) == held_out]
        for row in held_pairs.sort_values("lead_time_hours").itertuples(index=False):
            corrected = float(row.forecast_value) + correction
            threshold = float(row.event_threshold)
            pair_rows.append(
                {
                    "case_id": held_out,
                    "case_role": case["case_role"],
                    "lead_time_hours": int(row.lead_time_hours),
                    "region_id": row.region_id,
                    "training_case_count": training_cases,
                    "fold_correction_degc": correction,
                    "raw_forecast_tmax_degc": float(row.forecast_value),
                    "corrected_forecast_tmax_degc": corrected,
                    "observed_tmax_degc": float(row.observed_value),
                    "event_threshold_degc": threshold,
                    "raw_hot_day": bool(float(row.forecast_value) >= threshold),
                    "corrected_hot_day": bool(corrected >= threshold),
                    "observed_hot_day": bool(float(row.observed_value) >= threshold),
                }
            )
        corrected_summaries = _correct_case_summaries(
            summaries, case, correction, config
        )
        results = evaluate_all(
            corrected_summaries,
            statistics,
            heavy_rule,
            heat_rule,
            ARTIFACT_CREATED_AT,
        )
        _, fold_audit = build_review([case], results)
        audit_rows.extend(fold_audit)

    audit = pd.DataFrame(audit_rows)
    base_assessment = assess_hazard(audit, pairs, heat_rule)
    final_correction = _clip(float(calibration["error_degc"].median()), config)
    reasons = [item for item in str(base_assessment["blocking_reasons"]).split(";") if item]
    correction_limit = float(
        config["success_gates"]["maximum_absolute_final_correction_degc"]
    )
    if abs(final_correction) > correction_limit:
        reasons.append("final_correction_above_gate")
    assessment = {
        "hazard": "heatwave",
        "method": config["estimator"]["method"],
        "folds": len(cases),
        "calibration_pair_count": len(calibration),
        "fold_correction_min_degc": min(corrections),
        "fold_correction_max_degc": max(corrections),
        "final_correction_degc": final_correction,
        **{
            key: base_assessment[key]
            for key in (
                "event_cases",
                "control_cases",
                "event_target_windows",
                "candidate_hits",
                "target_window_recall",
                "control_target_windows",
                "candidate_correct_negatives",
                "target_window_specificity",
                "event_case_detection_fraction",
                "control_case_rejection_fraction",
                "observation_qc_statuses",
            )
        },
        "recommendation": "eligible_for_fixed_v3_candidate" if not reasons else "blocked",
        "blocking_reasons": ";".join(reasons),
        "independent_heatwave_opened": False,
    }
    return pair_rows, audit_rows, assessment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/heatwave_bias_correction_cv_v1.yaml"),
    )
    parser.add_argument(
        "--pairs",
        type=Path,
        default=Path("handoff/weather_verification/development_pairs.csv"),
    )
    parser.add_argument(
        "--catalog", type=Path, default=Path("configs/case_catalog_candidates.csv")
    )
    parser.add_argument(
        "--summaries",
        type=Path,
        default=Path("handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv"),
    )
    parser.add_argument(
        "--statistics",
        type=Path,
        default=Path("handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv"),
    )
    parser.add_argument(
        "--heavy-rule", type=Path, default=Path("configs/heavy_rain_rules_v2.yaml")
    )
    parser.add_argument(
        "--heat-rule", type=Path, default=Path("configs/heatwave_rules_v2.yaml")
    )
    parser.add_argument(
        "--pair-output",
        type=Path,
        default=Path("handoff/weather_verification/heatwave_bias_cv_pairs.csv"),
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=Path("handoff/risk_dry_runs/heatwave_bias_cv_rule_review.csv"),
    )
    parser.add_argument(
        "--assessment-output",
        type=Path,
        default=Path("manifests/heatwave_bias_cv_assessment.csv"),
    )
    args = parser.parse_args()

    pair_rows, audit_rows, assessment = run(
        args.config,
        args.pairs,
        args.catalog,
        args.summaries,
        args.statistics,
        args.heavy_rule,
        args.heat_rule,
    )
    _write_csv(args.pair_output, pair_rows, PAIR_OUTPUT_FIELDS)
    _write_csv(args.audit_output, audit_rows, AUDIT_FIELDS)
    _write_csv(args.assessment_output, [assessment], ASSESSMENT_FIELDS)
    print(args.pair_output)
    print(args.audit_output)
    print(args.assessment_output)
    print(
        f"recommendation={assessment['recommendation']} "
        f"correction={assessment['final_correction_degc']:.3f} "
        f"recall={assessment['target_window_recall']:.3f} "
        f"specificity={assessment['target_window_specificity']:.3f}"
    )


if __name__ == "__main__":
    main()
