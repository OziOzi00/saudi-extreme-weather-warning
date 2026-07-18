import csv
import json
from pathlib import Path

import pytest

from saudi_warning.knowledge_graph.bundle import build_bundle, validate_member_c_inputs
from saudi_warning.reporting.generate_report import render_report, validate_report_mode


ROOT = Path(__file__).resolve().parents[1]
REGIONS = ROOT / "configs" / "region_registry.csv"
CASES = ROOT / "configs" / "case_catalog_candidates.csv"
TRUTH = ROOT / "handoff" / "disaster_truth" / "disaster_impact_truth.csv"
SOURCES = ROOT / "handoff" / "disaster_truth" / "source_catalog.csv"
RISK = ROOT / "handoff" / "risk_results" / "example_risk_result.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_member_c_contracts_are_cross_referenced() -> None:
    counts = validate_member_c_inputs(REGIONS, CASES, TRUTH, SOURCES)
    assert counts == {"regions": 13, "cases": 21, "truth_records": 12, "sources": 15}
    regions = read_csv(REGIONS)
    assert all(row["region_name_ar"] for row in regions)
    controls = [row for row in read_csv(CASES) if row["case_role"] == "control"]
    assert controls
    assert {row["weather_screening_status"] for row in controls} <= {
        "needs_b_observation_screening",
        "ghcn_screened_lower_intensity",
        "ssod_utc_screened_lower_intensity",
        "imerg_screened_lower_intensity",
    }
    assert all(row["impact_evidence_status"] == "unknown" for row in controls)
    assert all(row["selection_status"] == "approved" for row in controls)
    assert {row["dataset_split"] for row in controls} <= {
        "development",
        "independent_test",
    }


def test_truth_never_converts_missing_evidence_to_no() -> None:
    truth = read_csv(TRUTH)
    assert {row["impact_status"] for row in truth} == {"yes", "unknown"}
    heat = [row for row in truth if row["hazard"] == "heatwave"]
    assert heat and all(row["impact_status"] == "unknown" for row in heat)


def test_bundle_is_deterministic_and_contains_only_summaries() -> None:
    kwargs = {
        "regions_path": REGIONS,
        "cases_path": CASES,
        "truth_path": TRUTH,
        "sources_path": SOURCES,
        "risk_paths": [RISK],
        "generated_at": "2026-07-15T00:00:00Z",
    }
    first = build_bundle(**kwargs)
    second = build_bundle(**kwargs)
    assert first == second
    assert first["schema_version"] == "kg_bundle_v1"
    assert first["content_sha256"] == second["content_sha256"]
    assert {node["label"] for node in first["nodes"]} == {
        "Evidence",
        "ForecastCase",
        "HistoricalEvent",
        "Region",
        "RiskAssessment",
        "Rule",
    }
    serialized = json.dumps(first)
    assert "latitude" not in serialized
    assert "longitude" not in serialized
    assert ".nc" in serialized  # provenance path only; no grid values are embedded
    for node in first["nodes"]:
        assert all(
            isinstance(value, (str, int, float, bool))
            for value in node["properties"].values()
        )


def test_contract_rejects_control_claimed_as_screened(tmp_path: Path) -> None:
    rows = read_csv(CASES)
    row = next(item for item in rows if item["case_role"] == "control")
    row["weather_screening_status"] = "weather_confirmed"
    broken = tmp_path / "cases.csv"
    with broken.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="must remain pending"):
        validate_member_c_inputs(REGIONS, broken, TRUTH, SOURCES)


def test_report_preserves_example_disclosure_and_score() -> None:
    risk = json.loads(RISK.read_text(encoding="utf-8"))
    regions = {row["region_id"]: row for row in read_csv(REGIONS)}
    sources = {row["source_id"]: row for row in read_csv(SOURCES)}
    report = render_report(risk, regions["SA-01"], [], sources)
    assert "虚构契约示例" in report
    assert "风险分数：`7.0`" in report
    assert "状态应视为 `unknown`" in report
    assert "不能据此宣称预报准确" in report
    assert "重新计算" in report
    validate_report_mode(risk, "development")
    with pytest.raises(ValueError, match="rule_status=frozen"):
        validate_report_mode(risk, "formal")
