"""Evaluate the preregistered heatwave v5 candidate on the sealed 2018 batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from saudi_warning.verification.heatwave_v5_prospective import validate_v5_lock


LEADS = (24, 48, 72)
DETAIL_COLUMNS = [
    "case_id",
    "matched_pair_id",
    "case_role",
    "region_id",
    "lead_time_hours",
    "observed_tmax_degc",
    "observed_hot_day",
    "source_spatial_p95_degc",
    "correction_degc",
    "candidate_tmax_degc",
    "hot_day_threshold_degc",
    "severe_hot_day_threshold_degc",
    "candidate_hot_day",
    "candidate_severe_hot_day",
    "forecast_hot_day_streak",
    "candidate_positive",
]


def _read_config(root: Path, path: Path) -> dict[str, Any]:
    errors = validate_v5_lock(root, check_forecast_absence=False)
    if errors:
        raise ValueError("; ".join(errors))
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if config.get("status") != "preregistered_before_2018_forecast_access":
        raise ValueError("v5 candidate was not preregistered")
    if config.get("independent_heatwave_access") != "forbidden":
        raise ValueError("independent heatwave access must remain forbidden")
    candidate = config["candidate"]
    if candidate.get("permitted_methods") != ["lead_specific_median"]:
        raise ValueError("v5 evaluation permits exactly one candidate")
    if candidate.get("maximum_blending_forbidden") is not True:
        raise ValueError("regional maximum blending must remain forbidden")
    if candidate.get("threshold_search_forbidden") is not True:
        raise ValueError("post-lock threshold search must remain forbidden")
    return config


def build_candidate_rows(
    summaries: pd.DataFrame,
    selection: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Apply the single locked candidate without fitting or threshold search."""
    corrections = {
        int(lead): float(value)
        for lead, value in config["candidate"]["corrections_degc"].items()
    }
    if set(corrections) != set(LEADS):
        raise ValueError("v5 corrections must cover lead024, lead048, and lead072")
    clip = config["candidate"]["correction_clip_degc"]
    minimum = float(clip["minimum"])
    maximum = float(clip["maximum"])

    tmax = summaries[summaries["indicator"].astype(str) == "tmax_c"].copy()
    tmax["lead_time_hours"] = tmax["lead_time_hours"].astype(int)
    rows: list[dict[str, Any]] = []
    for case in selection.itertuples(index=False):
        source = tmax[
            (tmax["initial_time"].astype(str) == str(case.initial_time))
            & (tmax["region_id"].astype(str) == str(case.region_id))
            & (tmax["lead_time_hours"].isin(LEADS))
        ].sort_values("lead_time_hours")
        if list(source["lead_time_hours"]) != list(LEADS):
            raise ValueError(f"{case.case_id}: incomplete or duplicate forecast summaries")

        observed = [float(value) for value in str(case.observed_values_degc).split(";")]
        declared_flags = [
            value.lower() == "true"
            for value in str(case.observed_hot_day_flags).split(";")
        ]
        if len(observed) != len(LEADS) or len(declared_flags) != len(LEADS):
            raise ValueError(f"{case.case_id}: incomplete locked observations")
        hot_threshold = float(case.regional_hot_threshold_degc)
        severe_threshold = float(case.regional_severe_threshold_degc)
        observed_flags = [value >= hot_threshold for value in observed]
        if observed_flags != declared_flags:
            raise ValueError(f"{case.case_id}: observation flags changed after lock")

        streak = 0
        for index, item in enumerate(source.itertuples(index=False)):
            lead = int(item.lead_time_hours)
            correction = float(np.clip(corrections[lead], minimum, maximum))
            candidate_value = float(item.spatial_p95) + correction
            hot = candidate_value >= hot_threshold
            severe = candidate_value >= severe_threshold
            streak = streak + 1 if hot else 0
            positive = bool(severe or streak >= 2)
            rows.append(
                {
                    "case_id": str(case.case_id),
                    "matched_pair_id": str(case.matched_pair_id),
                    "case_role": str(case.case_role),
                    "region_id": str(case.region_id),
                    "lead_time_hours": lead,
                    "observed_tmax_degc": observed[index],
                    "observed_hot_day": observed_flags[index],
                    "source_spatial_p95_degc": float(item.spatial_p95),
                    "correction_degc": correction,
                    "candidate_tmax_degc": candidate_value,
                    "hot_day_threshold_degc": hot_threshold,
                    "severe_hot_day_threshold_degc": severe_threshold,
                    "candidate_hot_day": bool(hot),
                    "candidate_severe_hot_day": bool(severe),
                    "forecast_hot_day_streak": streak,
                    "candidate_positive": positive,
                }
            )
    frame = pd.DataFrame(rows, columns=DETAIL_COLUMNS)
    if len(frame) != len(selection) * len(LEADS):
        raise ValueError("v5 detail row count is incomplete")
    return frame


def assess_candidate(rows: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """Apply the preregistered weather-day and case-level success gates."""
    observed_hot = rows[rows["observed_hot_day"]]
    observed_nonhot = rows[~rows["observed_hot_day"]]
    event_rows = rows[rows["case_role"] == "event"]
    control_rows = rows[rows["case_role"] == "control"]
    event_cases = event_rows.groupby("case_id")["candidate_positive"].any()
    control_cases = control_rows.groupby("case_id")["candidate_positive"].any()

    recall = float(observed_hot["candidate_hot_day"].mean())
    specificity = float((~observed_nonhot["candidate_hot_day"]).mean())
    event_detection = float(event_cases.mean())
    control_rejection = float((~control_cases).mean())
    gates = config["evaluation"]["success_gates"]
    checks = {
        "minimum_event_cases": int(event_cases.size) >= int(gates["minimum_event_cases"]),
        "minimum_control_cases": int(control_cases.size)
        >= int(gates["minimum_control_cases"]),
        "minimum_observed_hot_day_recall": recall
        >= float(gates["minimum_observed_hot_day_recall"]),
        "minimum_observed_nonhot_day_specificity": specificity
        >= float(gates["minimum_observed_nonhot_day_specificity"]),
        # The lock serializes 2/3 as 0.666667, so compare the reported six-decimal
        # fraction instead of silently requiring all three event cases.
        "minimum_event_case_detection_fraction": round(event_detection, 6)
        >= float(gates["minimum_event_case_detection_fraction"]),
        "required_control_case_rejection_fraction": control_rejection
        >= float(gates["required_control_case_rejection_fraction"]),
    }
    passed = all(checks.values())
    return {
        "schema_version": "heatwave_v5_cross_year_prospective_assessment_v1",
        "scope": config["scope"],
        "candidate_method": config["candidate"]["method"],
        "forecast_source_year": int(config["forecast_source"]["dataset_year"]),
        "weather_truth_definition": "synchronous_NOAA_SSOD_V2_station_max",
        "weather_hot_day_prediction": "candidate_hot_day",
        "risk_alert_prediction": "candidate_positive",
        "event_context_scored_as_weather_truth": False,
        "observed_hot_days": int(len(observed_hot)),
        "observed_hot_day_hits": int(observed_hot["candidate_hot_day"].sum()),
        "observed_hot_day_recall": recall,
        "observed_nonhot_days": int(len(observed_nonhot)),
        "observed_nonhot_day_correct_negatives": int(
            (~observed_nonhot["candidate_hot_day"]).sum()
        ),
        "observed_nonhot_day_specificity": specificity,
        "event_cases": int(event_cases.size),
        "event_case_detections": int(event_cases.sum()),
        "event_case_detection_fraction": event_detection,
        "control_cases": int(control_cases.size),
        "control_case_correct_rejections": int((~control_cases).sum()),
        "control_case_rejection_fraction": control_rejection,
        "gate_checks": checks,
        "passes_all_preregistered_gates": passed,
        "recommendation": (
            "freeze_candidate_before_one_time_independent_heatwave_evaluation"
            if passed
            else "keep_heatwave_draft_blocked"
        ),
        "can_freeze_candidate": passed,
        "heatwave_rule_frozen": False,
        "independent_heatwave_opened": False,
        "can_open_independent_heatwave_from_this_run": False,
        "post_lock_threshold_search_performed": False,
        "maximum_blending_used": False,
    }


def run(
    root: Path,
    candidate_path: Path,
    selection_path: Path,
    summaries_path: Path,
    detail_output: Path,
    assessment_output: Path,
) -> dict[str, Any]:
    config = _read_config(root, candidate_path)
    selection = pd.read_csv(selection_path)
    summaries = pd.read_csv(summaries_path)
    rows = build_candidate_rows(summaries, selection, config)
    assessment = assess_candidate(rows, config)
    detail_output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(detail_output, index=False, lineterminator="\n")
    assessment_output.parent.mkdir(parents=True, exist_ok=True)
    assessment_output.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return assessment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--candidate",
        type=Path,
        default=Path("configs/heatwave_v5_prospective_candidate.yaml"),
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=Path("manifests/heatwave_v5_prospective_selection.csv"),
    )
    parser.add_argument(
        "--summaries",
        type=Path,
        default=Path(
            "handoff/region_summaries/heatwave_v5_2018_adm1_indicator_summaries.csv"
        ),
    )
    parser.add_argument(
        "--detail-output",
        type=Path,
        default=Path("handoff/weather_verification/heatwave_v5_prospective_details.csv"),
    )
    parser.add_argument(
        "--assessment-output",
        type=Path,
        default=Path("manifests/heatwave_v5_prospective_assessment.json"),
    )
    args = parser.parse_args()
    assessment = run(
        args.root,
        args.candidate,
        args.selection,
        args.summaries,
        args.detail_output,
        args.assessment_output,
    )
    print(json.dumps(assessment, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
