"""Descriptive disaster-impact coverage evaluation for frozen risk results."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


RISK_RANK = {"low": 0, "medium": 1, "high": 2}
UNIT_FIELDS = [
    "dataset_split",
    "case_id",
    "region_id",
    "hazard",
    "impact_record_count",
    "impact_record_ids",
    "impact_categories",
    "impact_start_time",
    "impact_end_time",
    "evidence_tiers",
    "risk_result_count",
    "overlapping_risk_count",
    "alerting_overlapping_risk_count",
    "best_overlapping_risk_level",
    "detected",
    "detected_lead_time_hours",
    "nominal_issue_to_impact_start_hours",
    "evaluation_scope",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def intervals_overlap(
    risk_start: str, risk_end: str, impact_start: str, impact_end: str
) -> bool:
    """Treat risk windows as half-open and impact timestamps as recorded bounds."""

    return parse_time(risk_start) < parse_time(impact_end) and parse_time(
        risk_end
    ) > parse_time(impact_start)


def base_case_id(risk: dict[str, Any]) -> str:
    initial = parse_time(risk["initial_time"])
    return initial.strftime("%Y%m%d_%H")


def load_risks(paths: Iterable[tuple[Path, str]]) -> list[dict[str, Any]]:
    rows = []
    for directory, split in paths:
        for path in sorted(directory.glob("*.json")):
            risk = json.loads(path.read_text(encoding="utf-8"))
            risk["_path"] = path.as_posix()
            risk["_dataset_split"] = split
            risk["_base_case_id"] = base_case_id(risk)
            rows.append(risk)
    return rows


def _join(values: Iterable[str]) -> str:
    return ";".join(sorted(set(values)))


def build_positive_units(
    truth: list[dict[str, str]],
    catalog: list[dict[str, str]],
    risks: list[dict[str, Any]],
    minimum_risk_level: str = "medium",
) -> list[dict[str, Any]]:
    if minimum_risk_level not in RISK_RANK:
        raise ValueError(f"unsupported minimum risk level: {minimum_risk_level}")
    catalog_by_case = {row["case_id"]: row for row in catalog}
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in truth:
        if row["impact_status"] == "yes" and row["review_status"] == "reviewed":
            grouped[(row["case_id"], row["region_id"], row["hazard"])].append(row)

    units = []
    for (case_id, region_id, hazard), records in sorted(grouped.items()):
        case = catalog_by_case.get(case_id)
        if not case or case["selection_status"] != "approved":
            raise ValueError(f"impact truth does not map to an approved case: {case_id}")
        if case["case_role"] != "event":
            raise ValueError(f"positive impact truth maps to a non-event case: {case_id}")
        impact_start = min(parse_time(row["event_start_time"]) for row in records)
        impact_end = max(parse_time(row["event_end_time"]) for row in records)
        matching = [
            risk
            for risk in risks
            if risk["_base_case_id"] == case_id
            and risk["region_id"] == region_id
            and risk["hazard"] == hazard
        ]
        if len(matching) != 3:
            raise ValueError(
                f"expected three frozen risk results for {case_id}/{region_id}: "
                f"found {len(matching)}"
            )
        if any(risk.get("rule_status") != "frozen" for risk in matching):
            raise ValueError(f"non-frozen risk result in impact evaluation: {case_id}")
        if {risk["_dataset_split"] for risk in matching} != {case["dataset_split"]}:
            raise ValueError(f"risk split disagrees with catalog: {case_id}")
        overlapping = [
            risk
            for risk in matching
            if intervals_overlap(
                risk["valid_start_time"],
                risk["valid_end_time"],
                impact_start.isoformat(),
                impact_end.isoformat(),
            )
        ]
        alerting = [
            risk
            for risk in overlapping
            if RISK_RANK[risk["risk_level"]] >= RISK_RANK[minimum_risk_level]
        ]
        best = (
            max(overlapping, key=lambda row: RISK_RANK[row["risk_level"]])
            if overlapping
            else None
        )
        detected_risk = min(alerting, key=lambda row: row["lead_time_hours"]) if alerting else None
        initial = parse_time(matching[0]["initial_time"])
        units.append(
            {
                "dataset_split": case["dataset_split"],
                "case_id": case_id,
                "region_id": region_id,
                "hazard": hazard,
                "impact_record_count": len(records),
                "impact_record_ids": _join(row["record_id"] for row in records),
                "impact_categories": _join(row["impact_category"] for row in records),
                "impact_start_time": impact_start.isoformat().replace("+00:00", "Z"),
                "impact_end_time": impact_end.isoformat().replace("+00:00", "Z"),
                "evidence_tiers": _join(row["evidence_tier"] for row in records),
                "risk_result_count": len(matching),
                "overlapping_risk_count": len(overlapping),
                "alerting_overlapping_risk_count": len(alerting),
                "best_overlapping_risk_level": best["risk_level"] if best else "",
                "detected": bool(alerting),
                "detected_lead_time_hours": (
                    detected_risk["lead_time_hours"] if detected_risk else ""
                ),
                "nominal_issue_to_impact_start_hours": (
                    impact_start - initial
                ).total_seconds()
                / 3600,
                "evaluation_scope": "reviewed_positive_impact_only",
            }
        )
    return units


def summarize(
    units: list[dict[str, Any]], truth: list[dict[str, str]]
) -> dict[str, Any]:
    partitions = {}
    for split in ("development", "independent_test", "all"):
        selected = units if split == "all" else [u for u in units if u["dataset_split"] == split]
        detected = sum(bool(row["detected"]) for row in selected)
        partitions[split] = {
            "eligible_positive_units": len(selected),
            "detected_positive_units": detected,
            "positive_coverage_fraction": detected / len(selected) if selected else None,
        }
    reviewed_positive = sum(
        row["impact_status"] == "yes" and row["review_status"] == "reviewed"
        for row in truth
    )
    reviewed_negative = sum(
        row["impact_status"] == "no" and row["review_status"] == "reviewed"
        for row in truth
    )
    excluded_unknown = sum(row["impact_status"] == "unknown" for row in truth)
    excluded_nonreviewed = sum(row["review_status"] != "reviewed" for row in truth)
    return {
        "status": "complete_with_scope_limitations",
        "protocol_version": "impact_layer_descriptive_v1",
        "minimum_alerting_risk_level": "medium",
        "evaluation_unit": "case_region_hazard",
        "eligible_truth": "reviewed_and_impact_status_yes",
        "reviewed_positive_record_count": reviewed_positive,
        "excluded_unknown_record_count": excluded_unknown,
        "excluded_nonreviewed_record_count": excluded_nonreviewed,
        "reviewed_negative_record_count": reviewed_negative,
        "partitions": partitions,
        "negative_class_metrics_status": "unavailable_no_reviewed_no_impact_truth",
        "precision": None,
        "specificity": None,
        "false_alarm_ratio": None,
        "impact_evaluation_independence": (
            "not_blind_cases_were_selected_using_known_impact_evidence"
        ),
        "interpretation": "descriptive_positive_coverage_not_population_accuracy",
        "retuning_performed": False,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def risk_set_sha256(risks: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for risk in sorted(risks, key=lambda row: row["_path"]):
        path = Path(risk["_path"])
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_units(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=UNIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
