"""Evaluate the locked heatwave v3 candidate on the prospective development pair."""

from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from saudi_warning.risk.engine import evaluate_all, load_rule, load_statistics, load_summaries
from saudi_warning.risk.run_development_review import (
    ARTIFACT_CREATED_AT,
    AUDIT_FIELDS,
    build_review,
    read_development_cases,
)
from saudi_warning.verification.heatwave_v3_prospective import validate_prospective_lock


DETAIL_FIELDS = [
    "case_id",
    "case_role",
    "region_id",
    "lead_time_hours",
    "evaluation_scope",
    "candidate_outcome",
    "risk_level",
    "source_spatial_p95_degc",
    "source_maximum_degc",
    "candidate_tmax_degc",
    "event_threshold_degc",
    "observed_tmax_degc",
    "observed_hot_day",
]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(
    root: Path,
    candidate_path: Path,
    catalog_path: Path,
    summaries_path: Path,
    pairs_path: Path,
    statistics_path: Path,
    heavy_rule_path: Path,
    heat_rule_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    errors = validate_prospective_lock(root, check_forecast_absence=False)
    if errors:
        raise ValueError("; ".join(errors))
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    if candidate["status"] != "locked_before_new_development_forecast_access":
        raise ValueError("heatwave v3 candidate is not locked")
    if candidate["independent_heatwave_access"] != "forbidden":
        raise ValueError("independent heatwave guard is missing")

    selected_ids = set(candidate["prospective_inputs"]["selected_case_ids"])
    cases = [
        row
        for row in read_development_cases(catalog_path)
        if row["case_id"] in selected_ids
    ]
    if {row["case_id"] for row in cases} != selected_ids:
        raise ValueError("prospective cases are not integrated as development")

    summaries = load_summaries(summaries_path)
    temperature = candidate["temperature_candidate"]
    weight = float(temperature["maximum_weight"])
    correction = float(temperature["fixed_bias_correction_degc"])
    selected_summaries: list[dict[str, Any]] = []
    candidate_values: dict[tuple[str, int, str], dict[str, float]] = {}
    case_by_initial = {row["initial_time"]: row["case_id"] for row in cases}
    for source in summaries:
        case_id = case_by_initial.get(str(source["initial_time"]))
        if case_id is None:
            continue
        case = next(item for item in cases if item["case_id"] == case_id)
        if str(source["region_id"]) not in set(case["target_region_ids"].split(";")):
            continue
        row = deepcopy(source)
        if row["indicator"] == "tmax_c":
            spatial_p95 = float(row["spatial_p95"])
            maximum = float(row["maximum"])
            value = spatial_p95 + weight * (maximum - spatial_p95) + correction
            row["spatial_p95"] = value
            candidate_values[(case_id, int(row["lead_time_hours"]), str(row["region_id"]))] = {
                "source_spatial_p95_degc": spatial_p95,
                "source_maximum_degc": maximum,
                "candidate_tmax_degc": value,
            }
        selected_summaries.append(row)

    expected = len(cases) * 3 * 11
    if len(selected_summaries) != expected or len(candidate_values) != len(cases) * 3:
        raise ValueError("prospective regional summaries are incomplete")

    results = evaluate_all(
        selected_summaries,
        load_statistics(statistics_path),
        load_rule(heavy_rule_path, "heavy_rain"),
        load_rule(heat_rule_path, "heatwave"),
        ARTIFACT_CREATED_AT,
    )
    _, audit = build_review(cases, results)
    pairs = pd.read_csv(pairs_path)
    pairs = pairs[
        pairs["case_id"].astype(str).isin(selected_ids)
        & (pairs["variable"] == "tmax_c")
        & (pairs["aggregation"] == "station_max")
        & (pairs["qc_status"] == "accepted")
    ].copy()
    if len(pairs) != len(cases) * 3:
        raise ValueError("prospective observed tmax pairs are incomplete")
    pair_index = {
        (str(row.case_id), int(row.lead_time_hours), str(row.region_id)): row
        for row in pairs.itertuples(index=False)
    }
    audit_index = {
        (str(row["case_id"]), int(row["lead_time_hours"]), str(row["region_id"])): row
        for row in audit
    }
    details: list[dict[str, Any]] = []
    for key, values in sorted(candidate_values.items()):
        pair = pair_index[key]
        item = audit_index[key]
        threshold = float(pair.event_threshold)
        details.append(
            {
                "case_id": key[0],
                "case_role": item["case_role"],
                "region_id": key[2],
                "lead_time_hours": key[1],
                "evaluation_scope": item["evaluation_scope"],
                "candidate_outcome": item["candidate_outcome"],
                "risk_level": item["risk_level"],
                **values,
                "event_threshold_degc": threshold,
                "observed_tmax_degc": float(pair.observed_value),
                "observed_hot_day": bool(float(pair.observed_value) >= threshold),
            }
        )

    detail_frame = pd.DataFrame(details)
    event_target = detail_frame[
        (detail_frame["case_role"] == "event")
        & (detail_frame["evaluation_scope"] == "target_window")
    ]
    control_target = detail_frame[
        (detail_frame["case_role"] == "control")
        & (detail_frame["evaluation_scope"] == "target_window")
    ]
    positive = detail_frame["risk_level"].isin(["medium", "high"])
    detail_frame["candidate_positive"] = positive
    event_target = detail_frame.loc[event_target.index]
    control_target = detail_frame.loc[control_target.index]
    observed_hot_target = event_target[event_target["observed_hot_day"]]
    gates = candidate["success_gates"]
    checks = {
        "event_target_windows": len(event_target) == int(gates["event_target_windows_expected"]),
        "event_target_hits": int(event_target["candidate_positive"].sum())
        >= int(gates["minimum_event_target_hits"]),
        "observed_hot_target_windows": len(observed_hot_target)
        == int(gates["observed_hot_target_windows_expected"]),
        "observed_hot_target_hits": int(observed_hot_target["candidate_positive"].sum())
        >= int(gates["minimum_observed_hot_target_hits"]),
        "control_target_windows": len(control_target)
        == int(gates["control_target_windows_expected"]),
        "control_correct_negatives": int((~control_target["candidate_positive"]).sum())
        >= int(gates["required_control_correct_negatives"]),
    }
    passed = all(checks.values())
    assessment = {
        "schema_version": "heatwave_v3_prospective_assessment_v1",
        "scope": "prospective_development_only",
        "candidate_weight": weight,
        "fixed_bias_correction_degc": correction,
        "event_target_windows": len(event_target),
        "event_target_hits": int(event_target["candidate_positive"].sum()),
        "observed_hot_target_windows": len(observed_hot_target),
        "observed_hot_target_hits": int(observed_hot_target["candidate_positive"].sum()),
        "control_target_windows": len(control_target),
        "control_correct_negatives": int((~control_target["candidate_positive"]).sum()),
        "gate_checks": checks,
        "recommendation": "join_all_development_cv" if passed else "keep_blocked",
        "heatwave_rule_frozen": False,
        "independent_heatwave_opened": False,
        "alternative_weights_searched_after_lock": False,
    }
    return detail_frame[DETAIL_FIELDS].to_dict("records"), audit, assessment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--candidate", type=Path, default=Path("configs/heatwave_v3_prospective_candidate.yaml")
    )
    parser.add_argument("--catalog", type=Path, default=Path("configs/case_catalog_candidates.csv"))
    parser.add_argument(
        "--summaries",
        type=Path,
        default=Path("handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv"),
    )
    parser.add_argument(
        "--pairs", type=Path, default=Path("handoff/weather_verification/development_pairs.csv")
    )
    parser.add_argument(
        "--statistics",
        type=Path,
        default=Path("handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv"),
    )
    parser.add_argument("--heavy-rule", type=Path, default=Path("configs/heavy_rain_rules_v2.yaml"))
    parser.add_argument("--heat-rule", type=Path, default=Path("configs/heatwave_rules_v2.yaml"))
    parser.add_argument(
        "--detail-output",
        type=Path,
        default=Path("handoff/weather_verification/heatwave_v3_prospective_details.csv"),
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=Path("handoff/risk_dry_runs/heatwave_v3_prospective_review.csv"),
    )
    parser.add_argument(
        "--assessment-output",
        type=Path,
        default=Path("manifests/heatwave_v3_prospective_assessment.json"),
    )
    args = parser.parse_args()
    details, audit, assessment = run(
        args.root,
        args.candidate,
        args.catalog,
        args.summaries,
        args.pairs,
        args.statistics,
        args.heavy_rule,
        args.heat_rule,
    )
    _write_csv(args.detail_output, details, DETAIL_FIELDS)
    _write_csv(args.audit_output, audit, AUDIT_FIELDS)
    args.assessment_output.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(assessment, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
