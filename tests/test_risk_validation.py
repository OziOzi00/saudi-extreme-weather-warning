"""Validate Risk JSON cross-field semantics without an optional JSON Schema package."""

import json
from copy import deepcopy
from pathlib import Path

from saudi_warning.risk.validation import load_region_ids, validate_result


ROOT = Path(__file__).resolve().parents[1]


def _example() -> tuple[dict, dict, set[str]]:
    schema = json.loads((ROOT / "schemas" / "risk_result.schema.json").read_text(encoding="utf-8"))
    result_path = (
        ROOT
        / "handoff"
        / "risk_dry_runs"
        / "results"
        / "risk_draft_20200820_00_024_SA-01_heavy_rain.json"
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    regions = load_region_ids(ROOT / "configs" / "region_registry.csv")
    return schema, result, regions


def test_existing_draft_result_passes_semantic_validation() -> None:
    schema, result, regions = _example()
    assert validate_result(result, schema, regions) == []


def test_validator_rejects_time_lead_region_and_non_finite_errors() -> None:
    schema, result, regions = _example()
    broken = deepcopy(result)
    broken["valid_end_time"] = "2020-08-22T00:00:00Z"
    broken["source_file"] = broken["source_file"].replace("lead024", "lead048")
    broken["region_id"] = "NOT-A-REGION"
    broken["risk_score"] = float("nan")
    errors = validate_result(broken, schema, regions)
    assert any("valid window" in error for error in errors)
    assert any("inconsistent with initial_time" in error for error in errors)
    assert any("lead suffix" in error for error in errors)
    assert any("unknown value" in error for error in errors)
    assert any("non-negative finite" in error for error in errors)


def test_formal_validation_requires_explicit_frozen_status() -> None:
    schema, result, regions = _example()
    errors = validate_result(result, schema, regions, require_frozen=True)
    assert errors == ["rule_status: formal delivery requires explicit frozen status"]
