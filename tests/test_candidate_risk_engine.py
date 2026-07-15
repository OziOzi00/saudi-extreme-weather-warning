"""Validate candidate rules and their deliberately separate dry-run artifacts."""

import csv
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_candidate_rules_remain_draft_and_auditable() -> None:
    for filename, hazard in (
        ("heavy_rain_rules_v1.yaml", "heavy_rain"),
        ("heatwave_rules_v1.yaml", "heatwave"),
    ):
        rule = yaml.safe_load((ROOT / "configs" / filename).read_text(encoding="utf-8"))
        assert rule["hazard"] == hazard
        assert rule["status"] == "draft"
        assert (ROOT / rule["calibration_source"]).exists()
        assert (ROOT / rule["temporal_semantics"]).exists()


def test_dry_run_has_one_result_per_lead_region_and_hazard() -> None:
    files = sorted((ROOT / "handoff" / "risk_dry_runs" / "results").glob("*.json"))
    assert len(files) == 3 * 13 * 2
    identities = set()
    for path in files:
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["rule_status"] == "draft"
        assert result["verification"] is None
        assert result["risk_level"] in {"low", "medium", "high"}
        assert result["confidence"] in {"low", "medium", "high"}
        assert result["missing_evidence"] is not None
        identities.add(
            (
                result["initial_time"],
                result["lead_time_hours"],
                result["region_id"],
                result["hazard"],
            )
        )
    assert len(identities) == len(files)


def test_low_candidate_risk_has_zero_score_and_threshold_audit_is_complete() -> None:
    for path in (ROOT / "handoff" / "risk_dry_runs" / "results").glob("*.json"):
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["hazard"] == "heavy_rain" and result["risk_level"] == "low":
            assert result["risk_score"] == 0.0

    audit = ROOT / "handoff" / "risk_dry_runs" / "candidate_threshold_audit.csv"
    with audit.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 13 * 4 * 5
    assert all(row["rule_status"] == "draft" for row in rows)
    assert all(float(row["applied_threshold"]) >= float(row["absolute_floor"]) for row in rows)
