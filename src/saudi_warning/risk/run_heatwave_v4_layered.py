"""Compare preregistered layered heatwave calibrations on development only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


KEYS = ["case_id", "case_role", "lead_time_hours", "region_id"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_preregistration(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if config.get("status") != "preregistered_before_layered_development_run":
        raise ValueError("v4 calibration is not preregistered")
    if config.get("independent_heatwave_access") != "forbidden":
        raise ValueError("independent heatwave access must remain forbidden")
    if config.get("prospective_sa08_access_for_fitting") != "forbidden":
        raise ValueError("evaluated SA-08 cases cannot be used for fitting")
    if config["application"].get("maximum_blending_forbidden") is not True:
        raise ValueError("regional maximum blending must be forbidden")
    for item in config["locked_inputs"].values():
        source = Path(item["path"])
        if _sha256(source) != str(item["sha256"]).lower():
            raise ValueError(f"locked input SHA-256 mismatch: {source}")
    return config


def _clip(value: float, config: dict[str, Any]) -> float:
    limits = config["estimator"]["correction_clip_degc"]
    return float(np.clip(value, float(limits["minimum"]), float(limits["maximum"])))


def _candidate_rows(
    pairs: pd.DataFrame,
    diagnostics: pd.DataFrame,
    review: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    approved = set(config["approved_retrospective_case_ids"])
    excluded = set(config["excluded_from_fitting"])
    if approved & excluded:
        raise ValueError("approved and excluded case sets overlap")
    if set(pairs["case_id"].astype(str)) != approved:
        raise ValueError("calibration pairs diverge from approved retrospective cases")
    if set(diagnostics["case_id"].astype(str)) != approved:
        raise ValueError("diagnostics diverge from approved retrospective cases")

    severe = review[KEYS + ["severe_threshold"]]
    frame = diagnostics.merge(severe, on=KEYS, validate="one_to_one")
    error_lookup = pairs[KEYS + ["raw_forecast_tmax_degc", "observed_tmax_degc"]].copy()
    error_lookup["calibration_error_degc"] = (
        error_lookup["observed_tmax_degc"] - error_lookup["raw_forecast_tmax_degc"]
    )

    rows: list[dict[str, Any]] = []
    minimum_training = int(config["estimator"]["minimum_training_cases"])
    for held_out in sorted(approved):
        training = error_lookup[error_lookup["case_id"].astype(str) != held_out]
        if int(training["case_id"].nunique()) < minimum_training:
            raise ValueError(f"insufficient training cases for {held_out}")
        pooled = _clip(float(training["calibration_error_degc"].median()), config)
        held = frame[frame["case_id"].astype(str) == held_out].sort_values(
            "lead_time_hours"
        )
        for method in config["candidate_methods"]:
            streak = 0
            for source in held.itertuples(index=False):
                if method == "pooled_median":
                    correction = pooled
                elif method == "lead_specific_median":
                    lead_training = training[
                        training["lead_time_hours"] == source.lead_time_hours
                    ]
                    correction = _clip(
                        float(lead_training["calibration_error_degc"].median()), config
                    )
                else:
                    raise ValueError(f"unsupported method: {method}")
                value = float(source.source_spatial_p95_degc) + correction
                hot = value >= float(source.primary_threshold)
                severe_hot = value >= float(source.severe_threshold)
                streak = streak + 1 if hot else 0
                positive = bool(severe_hot or (hot and streak >= 2))
                rows.append(
                    {
                        **{key: getattr(source, key) for key in KEYS},
                        "method": method,
                        "evaluation_scope": source.evaluation_scope,
                        "fold_correction_degc": correction,
                        "candidate_spatial_p95_degc": value,
                        "hot_day_threshold_degc": float(source.primary_threshold),
                        "severe_hot_day_threshold_degc": float(source.severe_threshold),
                        "candidate_hot_day": hot,
                        "candidate_severe_hot_day": severe_hot,
                        "forecast_hot_day_duration": streak,
                        "candidate_positive": positive,
                        "observed_hot_day": bool(source.observed_hot_day),
                    }
                )
    return pd.DataFrame(rows)


def _assess(rows: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    assessments: list[dict[str, Any]] = []
    gates = config["success_gates"]
    for method, group in rows.groupby("method", sort=True):
        target = group[group["evaluation_scope"] == "target_window"]
        events = target[target["case_role"] == "event"]
        controls = target[target["case_role"] == "control"]
        event_cases = events.groupby("case_id")["candidate_positive"].any()
        control_cases = controls.groupby("case_id")["candidate_positive"].any()
        recall = float(events["candidate_positive"].mean())
        specificity = float((~controls["candidate_positive"]).mean())
        event_fraction = float(event_cases.mean())
        control_rejection = float((~control_cases).mean())
        passed = (
            recall >= float(gates["minimum_target_window_recall"])
            and specificity >= float(gates["minimum_target_window_specificity"])
            and event_fraction >= float(gates["minimum_event_case_detection_fraction"])
            and control_rejection
            >= float(gates["required_control_case_rejection_fraction"])
        )
        assessments.append(
            {
                "method": method,
                "event_target_windows": len(events),
                "event_target_hits": int(events["candidate_positive"].sum()),
                "target_window_recall": recall,
                "control_target_windows": len(controls),
                "control_correct_negatives": int((~controls["candidate_positive"]).sum()),
                "target_window_specificity": specificity,
                "event_case_detection_fraction": event_fraction,
                "control_case_rejection_fraction": control_rejection,
                "passes_development_gates": passed,
            }
        )
    passing = [item["method"] for item in assessments if item["passes_development_gates"]]
    return {
        "schema_version": "heatwave_v4_layered_development_v1",
        "scope": config["scope"],
        "independent_heatwave_opened": False,
        "evaluated_sa08_used_for_fitting": False,
        "thresholds_changed": False,
        "duration_rule_changed": False,
        "maximum_blending_used": False,
        "method_assessments": assessments,
        "passing_methods": passing,
        "recommendation": (
            "lock_best_passing_method_for_new_prospective_development"
            if passing
            else "keep_blocked_and_redesign_numeric_calibration"
        ),
        "can_freeze_now": False,
        "can_open_independent_heatwave": False,
    }


def run(config_path: Path, row_output: Path, assessment_output: Path) -> dict[str, Any]:
    config = load_preregistration(config_path)
    inputs = config["locked_inputs"]
    pairs = pd.read_csv(inputs["calibration_pairs"]["path"])
    diagnostics = pd.read_csv(inputs["development_diagnostics"]["path"])
    review = pd.read_csv(inputs["rule_review"]["path"])
    rows = _candidate_rows(pairs, diagnostics, review, config)
    assessment = _assess(rows, config)
    row_output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(row_output, index=False)
    assessment_output.parent.mkdir(parents=True, exist_ok=True)
    assessment_output.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return assessment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/heatwave_v4_layered_calibration.yaml"),
    )
    parser.add_argument(
        "--row-output",
        type=Path,
        default=Path("handoff/weather_verification/heatwave_v4_layered_details.csv"),
    )
    parser.add_argument(
        "--assessment-output",
        type=Path,
        default=Path("manifests/heatwave_v4_layered_assessment.json"),
    )
    args = parser.parse_args()
    assessment = run(args.config, args.row_output, args.assessment_output)
    print(args.row_output)
    print(args.assessment_output)
    print(f"recommendation={assessment['recommendation']}")


if __name__ == "__main__":
    main()
