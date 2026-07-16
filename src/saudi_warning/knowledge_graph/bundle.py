"""Build a deterministic, database-neutral Neo4j import bundle.

The bundle deliberately contains summaries and provenance only. NetCDF grids and
raw news material remain outside Neo4j.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any


CASE_ROLES = {"event", "control", "demo"}
CASE_SELECTION_STATUSES = {"candidate", "approved", "rejected", "demo_only"}
IMPACT_STATUSES = {"yes", "no", "unknown"}
REVIEW_STATUSES = {"pending", "reviewed", "disputed"}
WEATHER_SCREENING_STATUSES = {
    "weather_confirmed",
    "ghcn_confirmed",
    "ghcn_screened_lower_intensity",
    "imerg_screened_lower_intensity",
    "needs_b_observation_screening",
    "not_applicable",
}
ALLOWED_NODE_LABELS = {
    "Evidence",
    "ForecastCase",
    "HistoricalEvent",
    "Region",
    "RiskAssessment",
    "Rule",
}
ALLOWED_RELATION_TYPES = {
    "BASED_ON",
    "CONCERNS",
    "EVALUATED_BY",
    "HAS_EVIDENCE",
    "VALID_FOR",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _require_columns(rows: list[dict[str, str]], required: set[str], name: str) -> None:
    columns = set(rows[0]) if rows else set()
    missing = sorted(required - columns)
    if missing:
        raise ValueError(f"{name} missing columns: {', '.join(missing)}")


def _parse_utc(value: str, field: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError(f"{field} must use UTC Z: {value}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is not an ISO-8601 timestamp: {value}") from exc


def _assert_unique(rows: list[dict[str, str]], field: str, name: str) -> None:
    values = [row[field] for row in rows]
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"{name} duplicate {field}: {', '.join(duplicates)}")


def validate_member_c_inputs(
    regions_path: Path,
    cases_path: Path,
    truth_path: Path,
    sources_path: Path,
) -> dict[str, int]:
    """Validate C-side CSV contracts and cross-file identifiers."""

    regions = _read_csv(regions_path)
    cases = _read_csv(cases_path)
    truth = _read_csv(truth_path)
    sources = _read_csv(sources_path)
    _require_columns(
        regions,
        {"region_id", "region_name_en", "region_name_ar", "source_shape_id"},
        "region registry",
    )
    _require_columns(
        cases,
        {
            "case_id",
            "initial_time",
            "event_id",
            "case_role",
            "hazard",
            "target_region_ids",
            "event_start_time",
            "event_end_time",
            "selection_status",
            "dataset_split",
            "weather_screening_status",
            "impact_evidence_status",
            "selection_reason_zh",
            "source_ids",
        },
        "candidate cases",
    )
    _require_columns(
        truth,
        {
            "record_id",
            "event_id",
            "case_id",
            "region_id",
            "hazard",
            "event_start_time",
            "event_end_time",
            "impact_status",
            "impact_category",
            "source_id",
            "review_status",
        },
        "impact truth",
    )
    _require_columns(sources, {"source_id", "publisher", "url"}, "source catalog")
    for rows, field, name in (
        (regions, "region_id", "region registry"),
        (cases, "case_id", "candidate cases"),
        (truth, "record_id", "impact truth"),
        (sources, "source_id", "source catalog"),
    ):
        _assert_unique(rows, field, name)

    region_ids = {row["region_id"] for row in regions}
    source_ids = {row["source_id"] for row in sources}
    case_ids = {row["case_id"] for row in cases}
    event_ids = {row["event_id"] for row in cases}
    for row in regions:
        if not row["region_name_ar"].strip():
            raise ValueError(f"missing Arabic name for {row['region_id']}")
    for row in cases:
        if re.fullmatch(r"2020\d{4}_(00|12)", row["case_id"]) is None:
            raise ValueError(f"invalid case_id: {row['case_id']}")
        if row["case_role"] not in CASE_ROLES:
            raise ValueError(f"invalid case_role for {row['case_id']}")
        if row["selection_status"] not in CASE_SELECTION_STATUSES:
            raise ValueError(f"invalid selection_status for {row['case_id']}")
        if row["dataset_split"] not in {
            "proposed_development",
            "proposed_independent_test",
            "development",
            "independent_test",
            "demo",
        }:
            raise ValueError(f"invalid dataset_split for {row['case_id']}")
        if row["weather_screening_status"] not in WEATHER_SCREENING_STATUSES:
            raise ValueError(f"invalid weather_screening_status for {row['case_id']}")
        if row["selection_status"] == "candidate" and not row["dataset_split"].startswith(
            "proposed_"
        ):
            raise ValueError("candidate cases must use a proposed dataset split")
        if row["selection_status"] == "approved" and row["dataset_split"] not in {
            "development",
            "independent_test",
        }:
            raise ValueError("approved cases require a frozen dataset split")
        initial = _parse_utc(row["initial_time"], "initial_time")
        start = _parse_utc(row["event_start_time"], "event_start_time")
        end = _parse_utc(row["event_end_time"], "event_end_time")
        if start > end or initial > end:
            raise ValueError(f"invalid event time order for {row['case_id']}")
        expected_case_id = initial.strftime("%Y%m%d_%H")
        if row["case_id"] != expected_case_id:
            raise ValueError(f"case_id does not match initial_time: {row['case_id']}")
        unknown_regions = set(row["target_region_ids"].split(";")) - region_ids
        if unknown_regions:
            raise ValueError(f"unknown case regions: {sorted(unknown_regions)}")
        listed_sources = {value for value in row["source_ids"].split(";") if value}
        if listed_sources - source_ids:
            raise ValueError(f"unknown case sources: {sorted(listed_sources - source_ids)}")
        if row["case_role"] == "control" and row["weather_screening_status"] not in {
            "needs_b_observation_screening",
            "ghcn_screened_lower_intensity",
            "imerg_screened_lower_intensity",
        }:
            raise ValueError("control candidates must remain pending or explicitly screened")
        if row["case_role"] == "event" and not listed_sources:
            raise ValueError(f"event candidate has no evidence source: {row['case_id']}")
    for row in truth:
        if row["case_id"] not in case_ids:
            raise ValueError(f"unknown truth case_id: {row['case_id']}")
        if row["region_id"] not in region_ids:
            raise ValueError(f"unknown truth region_id: {row['region_id']}")
        if row["source_id"] not in source_ids:
            raise ValueError(f"unknown truth source_id: {row['source_id']}")
        if row["event_id"] not in event_ids:
            raise ValueError(f"unknown truth event_id: {row['event_id']}")
        if row["impact_status"] not in IMPACT_STATUSES:
            raise ValueError(f"invalid impact_status for {row['record_id']}")
        if row["review_status"] not in REVIEW_STATUSES:
            raise ValueError(f"invalid review_status for {row['record_id']}")
        if row["impact_status"] == "no" and row["review_status"] != "reviewed":
            raise ValueError("no-impact evidence must be reviewed before use")
        for field in ("fatalities_min", "fatalities_max", "affected_households_min"):
            if row.get(field) and (not row[field].isdigit() or int(row[field]) < 0):
                raise ValueError(f"invalid {field} for {row['record_id']}")
        if row.get("fatalities_min") and row.get("fatalities_max"):
            if int(row["fatalities_min"]) > int(row["fatalities_max"]):
                raise ValueError(f"fatality range reversed for {row['record_id']}")
        _parse_utc(row["event_start_time"], "truth event_start_time")
        _parse_utc(row["event_end_time"], "truth event_end_time")
    return {
        "regions": len(regions),
        "cases": len(cases),
        "truth_records": len(truth),
        "sources": len(sources),
    }


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value not in (None, "")}


def _node(label: str, identifier: str, properties: dict[str, Any]) -> dict[str, Any]:
    if label not in ALLOWED_NODE_LABELS:
        raise ValueError(f"unsupported node label: {label}")
    return {"label": label, "id": identifier, "properties": _compact(properties)}


def _relation(
    relation_type: str,
    start_label: str,
    start_id: str,
    end_label: str,
    end_id: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if relation_type not in ALLOWED_RELATION_TYPES:
        raise ValueError(f"unsupported relation type: {relation_type}")
    return {
        "type": relation_type,
        "start_label": start_label,
        "start_id": start_id,
        "end_label": end_label,
        "end_id": end_id,
        "properties": _compact(properties or {}),
    }


def _risk_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        files.extend(sorted(path.glob("*.json")) if path.is_dir() else [path])
    return sorted(set(files))


def build_bundle(
    regions_path: Path,
    cases_path: Path,
    truth_path: Path,
    sources_path: Path,
    risk_paths: Iterable[Path],
    generated_at: str,
) -> dict[str, Any]:
    """Build nodes and relations without requiring a running Neo4j server."""

    counts = validate_member_c_inputs(regions_path, cases_path, truth_path, sources_path)
    regions = _read_csv(regions_path)
    cases = _read_csv(cases_path)
    truth = _read_csv(truth_path)
    sources = _read_csv(sources_path)
    nodes: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []

    for row in regions:
        nodes.append(_node("Region", row["region_id"], row))
    for row in sources:
        nodes.append(_node("Evidence", row["source_id"], row))
    for row in cases:
        nodes.append(_node("ForecastCase", row["case_id"], row))
        nodes.append(
            _node(
                "HistoricalEvent",
                row["event_id"],
                {
                    "event_id": row["event_id"],
                    "case_role": row["case_role"],
                    "hazard": row["hazard"],
                    "event_start_time": row["event_start_time"],
                    "event_end_time": row["event_end_time"],
                    "impact_evidence_status": row["impact_evidence_status"],
                },
            )
        )
        relations.append(
            _relation(
                "VALID_FOR",
                "ForecastCase",
                row["case_id"],
                "HistoricalEvent",
                row["event_id"],
            )
        )
        for region_id in row["target_region_ids"].split(";"):
            relations.append(
                _relation("CONCERNS", "ForecastCase", row["case_id"], "Region", region_id)
            )
        for source_id in filter(None, row["source_ids"].split(";")):
            relations.append(
                _relation("HAS_EVIDENCE", "HistoricalEvent", row["event_id"], "Evidence", source_id)
            )

    for row in truth:
        relations.append(
            _relation(
                "EVALUATED_BY",
                "HistoricalEvent",
                row["event_id"],
                "Evidence",
                row["source_id"],
                {
                    "record_id": row["record_id"],
                    "region_id": row["region_id"],
                    "impact_status": row["impact_status"],
                    "impact_category": row["impact_category"],
                    "review_status": row["review_status"],
                    "description_zh": row["impact_description_zh"],
                },
            )
        )

    risks = []
    for path in _risk_files(risk_paths):
        with path.open(encoding="utf-8") as stream:
            risk = json.load(stream)
        risk_id = f"{risk['case_id']}:{risk['region_id']}:{risk['hazard']}"
        rule_id = risk["rule_id"]
        scalar_risk = {
            key: value
            for key, value in risk.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        for key in (
            "indicator_summary",
            "supporting_evidence",
            "contradicting_evidence",
            "missing_evidence",
            "verification",
        ):
            scalar_risk[f"{key}_json"] = json.dumps(
                risk.get(key), sort_keys=True, ensure_ascii=False
            )
        scalar_risk["input_path"] = path.as_posix()
        nodes.append(_node("RiskAssessment", risk_id, scalar_risk))
        nodes.append(
            _node(
                "Rule",
                rule_id,
                {"rule_id": rule_id, "rule_status": risk.get("rule_status", "unknown")},
            )
        )
        base_case_id = risk["case_id"].removesuffix(f"_{risk['lead_time_hours']:03d}")
        if base_case_id in {row["case_id"] for row in cases}:
            relations.append(
                _relation("BASED_ON", "RiskAssessment", risk_id, "ForecastCase", base_case_id)
            )
        relations.append(
            _relation("CONCERNS", "RiskAssessment", risk_id, "Region", risk["region_id"])
        )
        relations.append(_relation("EVALUATED_BY", "RiskAssessment", risk_id, "Rule", rule_id))
        risks.append(path.as_posix())

    unique_nodes = {(item["label"], item["id"]): item for item in nodes}
    unique_relations = {
        (
            item["type"],
            item["start_label"],
            item["start_id"],
            item["end_label"],
            item["end_id"],
            json.dumps(item["properties"], sort_keys=True, ensure_ascii=False),
        ): item
        for item in relations
    }
    ordered_nodes = sorted(unique_nodes.values(), key=lambda item: (item["label"], item["id"]))
    ordered_relations = sorted(
        unique_relations.values(),
        key=lambda item: (
            item["type"],
            item["start_label"],
            item["start_id"],
            item["end_label"],
            item["end_id"],
        ),
    )
    payload = {
        "schema_version": "kg_bundle_v1",
        "generated_at": generated_at,
        "status": "development_bundle",
        "warning_zh": "含候选案例和示例风险结果，不代表正式预警或完成效果验证。",
        "input_counts": {**counts, "risk_files": len(risks)},
        "nodes": ordered_nodes,
        "relations": ordered_relations,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    payload["content_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload
