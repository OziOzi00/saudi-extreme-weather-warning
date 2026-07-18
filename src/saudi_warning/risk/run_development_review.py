"""Review draft risk rules on approved development cases only."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from saudi_warning.risk.engine import (
    evaluate_all,
    load_rule,
    load_statistics,
    load_summaries,
    write_results,
)


ARTIFACT_CREATED_AT = "2026-07-17T00:00:00Z"
AUDIT_FIELDS = [
    "case_id",
    "prediction_case_id",
    "event_id",
    "case_role",
    "hazard",
    "region_id",
    "lead_time_hours",
    "valid_start_time",
    "valid_end_time",
    "risk_level",
    "risk_score",
    "confidence",
    "evaluation_scope",
    "candidate_outcome",
    "primary_indicator",
    "primary_value",
    "primary_threshold",
    "severe_threshold",
    "primary_stage_or_duration",
    "weather_screening_status",
    "impact_evidence_status",
    "rule_id",
    "rule_status",
]


def read_development_cases(path: Path) -> list[dict[str, str]]:
    """Read metadata only and return the frozen approved development partition."""

    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    cases = [
        row
        for row in rows
        if row["selection_status"] == "approved" and row["dataset_split"] == "development"
    ]
    if not cases:
        raise ValueError("catalog contains no approved development cases")
    if any(row["case_role"] not in {"event", "control"} for row in cases):
        raise ValueError("development review supports only event and control cases")
    return cases


def select_development_summaries(
    summary_rows: list[dict[str, Any]], cases: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Keep only target regions from development initializations."""

    allowed = {
        (case["initial_time"], region_id)
        for case in cases
        for region_id in case["target_region_ids"].split(";")
    }
    selected = [
        row
        for row in summary_rows
        if (str(row["initial_time"]), str(row["region_id"])) in allowed
    ]
    actual = {(str(row["initial_time"]), str(row["region_id"])) for row in selected}
    if actual != allowed:
        raise ValueError(f"development summaries incomplete: missing {sorted(allowed - actual)}")
    return selected


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _overlaps_case_window(case: dict[str, str], result: dict[str, Any]) -> bool:
    valid_start = _utc(result["valid_start_time"])
    valid_end = _utc(result["valid_end_time"])
    case_start = _utc(case["event_start_time"])
    case_end = _utc(case["event_end_time"])
    return valid_start < case_end and valid_end > case_start


def _candidate_outcome(case_role: str, risk_level: str, in_window: bool) -> str:
    if not in_window:
        return "not_scored_context"
    positive = risk_level in {"medium", "high"}
    if case_role == "event":
        return "candidate_hit" if positive else "candidate_miss"
    return "candidate_false_alarm" if positive else "candidate_correct_negative"


def _primary_audit(result: dict[str, Any]) -> dict[str, Any]:
    summary = result["indicator_summary"]
    if result["hazard"] == "heavy_rain":
        return {
            "primary_indicator": "daily_precip_total_spatial_p95",
            "primary_value": summary.get("precip_spatial_p95_mm"),
            "primary_threshold": summary.get("precip_medium_threshold_mm"),
            "severe_threshold": summary.get("precip_high_threshold_mm"),
            "primary_stage_or_duration": summary.get("precipitation_stage"),
        }
    return {
        "primary_indicator": "tmax_c_spatial_p95",
        "primary_value": summary.get("tmax_spatial_p95_degc"),
        "primary_threshold": summary.get("hot_day_threshold_degc"),
        "severe_threshold": summary.get("severe_hot_day_threshold_degc"),
        "primary_stage_or_duration": summary.get("forecast_hot_day_duration"),
    }


def build_review(
    cases: list[dict[str, str]], results: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep each case's own hazard and attach review-only labels."""

    case_lookup = {case["initial_time"]: case for case in cases}
    reviewed_results: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for result in results:
        case = case_lookup[result["initial_time"]]
        if result["hazard"] != case["hazard"]:
            continue
        if result["region_id"] not in case["target_region_ids"].split(";"):
            raise AssertionError("non-target region entered development review")
        in_window = _overlaps_case_window(case, result)
        reviewed_results.append(result)
        audit.append(
            {
                "case_id": case["case_id"],
                "prediction_case_id": result["case_id"],
                "event_id": case["event_id"],
                "case_role": case["case_role"],
                "hazard": result["hazard"],
                "region_id": result["region_id"],
                "lead_time_hours": result["lead_time_hours"],
                "valid_start_time": result["valid_start_time"],
                "valid_end_time": result["valid_end_time"],
                "risk_level": result["risk_level"],
                "risk_score": result["risk_score"],
                "confidence": result["confidence"],
                "evaluation_scope": "target_window" if in_window else "context_only",
                "candidate_outcome": _candidate_outcome(
                    case["case_role"], result["risk_level"], in_window
                ),
                **_primary_audit(result),
                "weather_screening_status": case["weather_screening_status"],
                "impact_evidence_status": case["impact_evidence_status"],
                "rule_id": result["rule_id"],
                "rule_status": result["rule_status"],
            }
        )
    expected = sum(len(case["target_region_ids"].split(";")) * 3 for case in cases)
    if len(audit) != expected:
        raise ValueError(f"expected {expected} development decisions, found {len(audit)}")
    return reviewed_results, audit


def write_audit(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _is_formal_output(path: Path) -> bool:
    formal = (Path.cwd() / "handoff" / "risk_results").resolve()
    resolved = path.resolve()
    return resolved == formal or formal in resolved.parents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--heavy-rule", type=Path, default=Path("configs/heavy_rain_rules_v1.yaml")
    )
    parser.add_argument(
        "--heat-rule", type=Path, default=Path("configs/heatwave_rules_v1.yaml")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("handoff/risk_dry_runs/development_results"),
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=Path("handoff/risk_dry_runs/development_rule_review.csv"),
    )
    parser.add_argument("--created-at", default=ARTIFACT_CREATED_AT)
    args = parser.parse_args()

    heavy_rule = load_rule(args.heavy_rule, "heavy_rain")
    heat_rule = load_rule(args.heat_rule, "heatwave")
    if _is_formal_output(args.output_dir):
        raise ValueError("development review cannot write into formal risk_results")
    cases = read_development_cases(args.catalog)
    summaries = select_development_summaries(load_summaries(args.summaries), cases)
    results = evaluate_all(
        summaries,
        load_statistics(args.statistics),
        heavy_rule,
        heat_rule,
        args.created_at,
    )
    reviewed_results, audit = build_review(cases, results)
    write_results(reviewed_results, args.output_dir)
    write_audit(args.audit_output, audit)
    counts: dict[str, int] = {}
    for row in audit:
        outcome = str(row["candidate_outcome"])
        counts[outcome] = counts.get(outcome, 0) + 1
    print(f"wrote {len(reviewed_results)} development results to {args.output_dir}")
    print(args.audit_output)
    print(" ".join(f"{key}={value}" for key, value in sorted(counts.items())))


if __name__ == "__main__":
    main()
