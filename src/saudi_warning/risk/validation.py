"""Dependency-free validation for Risk JSON files and directories."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _utc(value: Any, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        errors.append(f"{field}: expected UTC ISO-8601 ending in Z")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field}: invalid ISO-8601 timestamp")
        return None
    return parsed.astimezone(timezone.utc)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_evidence(name: str, value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{name}: expected array")
        return
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{name}[{index}]: expected object")
            continue
        if not isinstance(item.get("indicator"), str) or not item["indicator"]:
            errors.append(f"{name}[{index}].indicator: expected non-empty string")
        if not isinstance(item.get("role"), str) or not item["role"]:
            errors.append(f"{name}[{index}].role: expected non-empty string")
        for numeric_field in ("value", "threshold"):
            numeric = item.get(numeric_field)
            if numeric is not None and not _finite(numeric):
                errors.append(f"{name}[{index}].{numeric_field}: expected finite number or null")


def validate_result(
    result: dict[str, Any],
    schema: dict[str, Any],
    known_region_ids: set[str] | None = None,
    require_frozen: bool = False,
) -> list[str]:
    """Return all structural and cross-field errors for one Risk JSON object."""
    errors: list[str] = []
    required = set(schema.get("required", []))
    properties = schema.get("properties", {})
    missing = sorted(required - set(result))
    extra = sorted(set(result) - set(properties))
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    if extra and schema.get("additionalProperties") is False:
        errors.append(f"unexpected fields: {', '.join(extra)}")

    for field, definition in properties.items():
        if field not in result:
            continue
        value = result[field]
        if "const" in definition and value != definition["const"]:
            errors.append(f"{field}: expected {definition['const']!r}")
        if "enum" in definition and value not in definition["enum"]:
            errors.append(f"{field}: unsupported value {value!r}")
        if "pattern" in definition and (
            not isinstance(value, str) or re.fullmatch(definition["pattern"], value) is None
        ):
            errors.append(f"{field}: does not match required pattern")

    lead = result.get("lead_time_hours")
    if lead not in {24, 48, 72}:
        errors.append("lead_time_hours: expected 24, 48, or 72")
    score = result.get("risk_score")
    if not _finite(score) or score < 0:
        errors.append("risk_score: expected a non-negative finite number")
    if result.get("risk_level") not in {"low", "medium", "high"}:
        errors.append("risk_level: unsupported value")
    if result.get("confidence") not in {"low", "medium", "high"}:
        errors.append("confidence: unsupported value")
    if result.get("hazard") not in {"heavy_rain", "heatwave"}:
        errors.append("hazard: unsupported value")
    for field in ("case_id", "source_file", "region_id", "region_name", "rule_id"):
        if not isinstance(result.get(field), str) or not result[field].strip():
            errors.append(f"{field}: expected non-empty string")
    if "rule_status" in result and result["rule_status"] not in {"draft", "frozen", "example"}:
        errors.append("rule_status: unsupported value")

    initial = _utc(result.get("initial_time"), "initial_time", errors)
    valid_start = _utc(result.get("valid_start_time"), "valid_start_time", errors)
    valid_end = _utc(result.get("valid_end_time"), "valid_end_time", errors)
    _utc(result.get("created_at"), "created_at", errors)
    if valid_start is not None and valid_end is not None:
        if valid_end - valid_start != timedelta(hours=24):
            errors.append("valid window: expected exactly 24 hours")
    if initial is not None and valid_end is not None and lead in {24, 48, 72}:
        if valid_end != initial + timedelta(hours=lead):
            errors.append("valid_end_time: inconsistent with initial_time and lead")

    source_file = result.get("source_file")
    if isinstance(source_file, str) and lead in {24, 48, 72}:
        if f"lead{lead:03d}.nc" not in source_file:
            errors.append("source_file: lead suffix is inconsistent with lead_time_hours")
    region_id = result.get("region_id")
    if known_region_ids is not None and region_id not in known_region_ids:
        errors.append(f"region_id: unknown value {region_id!r}")
    if require_frozen and result.get("rule_status") != "frozen":
        errors.append("rule_status: formal delivery requires explicit frozen status")

    if not isinstance(result.get("indicator_summary"), dict):
        errors.append("indicator_summary: expected object")
    else:
        for key, value in result["indicator_summary"].items():
            if isinstance(value, float) and not math.isfinite(value):
                errors.append(f"indicator_summary.{key}: expected finite value or null")
            if not isinstance(value, (int, float, str, bool, type(None))):
                errors.append(f"indicator_summary.{key}: unsupported value type")
    for name in ("supporting_evidence", "contradicting_evidence", "missing_evidence"):
        _validate_evidence(name, result.get(name), errors)
    verification = result.get("verification")
    if verification is not None and not isinstance(verification, dict):
        errors.append("verification: expected object or null")
    evidence_sets = []
    for name in ("supporting_evidence", "contradicting_evidence", "missing_evidence"):
        items = result.get(name)
        if not isinstance(items, list):
            evidence_sets.append(set())
            continue
        evidence_sets.append(
            {
                (item.get("indicator"), item.get("metric"), item.get("role"))
                for item in items
                if isinstance(item, dict)
            }
        )
    if evidence_sets[0] & evidence_sets[1]:
        errors.append("evidence: same condition appears as both supporting and contradicting")
    if (evidence_sets[0] | evidence_sets[1]) & evidence_sets[2]:
        errors.append("evidence: missing condition also appears as evaluated evidence")
    return errors


def load_region_ids(path: Path) -> set[str]:
    import csv

    with path.open(encoding="utf-8", newline="") as stream:
        return {row["region_id"] for row in csv.DictReader(stream)}


def validate_paths(
    paths: list[Path],
    schema_path: Path,
    registry_path: Path | None = None,
    require_frozen: bool = False,
) -> dict[str, list[str]]:
    """Validate files, including duplicate identity detection across the batch."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    regions = load_region_ids(registry_path) if registry_path is not None else None
    report: dict[str, list[str]] = {}
    identities: dict[tuple[Any, ...], Path] = {}
    for path in paths:
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report[str(path)] = [f"invalid JSON: {exc}"]
            continue
        if not isinstance(result, dict):
            report[str(path)] = ["root: expected object"]
            continue
        errors = validate_result(result, schema, regions, require_frozen)
        identity = (
            result.get("case_id"),
            result.get("region_id"),
            result.get("hazard"),
            result.get("lead_time_hours"),
        )
        if identity in identities:
            errors.append(f"duplicate identity also found in {identities[identity]}")
        else:
            identities[identity] = path
        report[str(path)] = errors
    return report
