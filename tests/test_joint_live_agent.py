import json
import hashlib
from pathlib import Path

import pandas as pd

from saudi_warning.agent.run_joint_live_report import validate_live_report
from saudi_warning.knowledge_graph.joint_runtime import (
    FORBIDDEN_COLUMNS,
    prediction_rows,
)


ROOT = Path(__file__).resolve().parents[1]


def test_joint_graph_rows_are_truth_free_and_cover_locked_windows() -> None:
    lock_path = (
        ROOT
        / "handoff/model_selection/joint_v2/locked_development_joint_heavy_rain_predictions.csv"
    )
    frame = pd.read_csv(lock_path)
    rows = prediction_rows(
        frame,
        hazard="heavy_rain",
        split="development",
        selected_rule="joint_test_rule",
        prediction_lock_sha256="a" * 64,
    )
    assert len(rows) == len(frame)
    assert set(frame.columns).isdisjoint(FORBIDDEN_COLUMNS)
    assert all(row["prediction_lock_sha256"] == "a" * 64 for row in rows)
    assert all("observed" not in json.dumps(row).lower() for row in rows)


def test_joint_graph_loader_rejects_truth_columns() -> None:
    frame = pd.DataFrame(
        [
            {
                "case_id": "case",
                "region_id": "SA-01",
                "lead_time_hours": 24,
                "base_method": "base",
                "knowledge_mode": "none",
                "base_risk_level": "low",
                "knowledge_triggered": False,
                "joint_final_risk_level": "low",
                "observed_hot_day": True,
            }
        ]
    )
    try:
        prediction_rows(
            frame,
            hazard="heatwave",
            split="development",
            selected_rule="rule",
            prediction_lock_sha256="b" * 64,
        )
    except ValueError as exc:
        assert "truth fields" in str(exc)
    else:
        raise AssertionError("truth-bearing rows must be rejected")


def test_live_report_guardrail_preserves_neo4j_timeline() -> None:
    timeline = [
        {
            "lead_time_hours": lead,
            "base_risk_level": "low",
            "knowledge_triggered": True,
            "joint_final_risk_level": "medium",
        }
        for lead in (24, 48, 72)
    ]
    packet = {
        "joint_decision": {
            "case_id": "case",
            "region_id": "SA-09",
            "hazard": "heavy_rain",
            "lead_time_hours": 48,
            "selected_joint_rule": "rule",
            "base_risk_level": "low",
            "knowledge_triggered": True,
            "joint_final_risk_level": "medium",
            "development_gate_passed": True,
            "operating_status": "research_candidate",
            "formal_warning_allowed": False,
        },
        "neo4j_context": {"timeline": timeline},
    }
    report = {
        "schema_version": "agent_joint_forecast_report_v5",
        "report_mode": "joint_forecast_live",
        "truth_accessed": False,
        "neo4j_query_mode": "live_neo4j",
        "case_id": "case",
        "region_id": "SA-09",
        "hazard": "heavy_rain",
        "focus_lead_time_hours": 48,
        "selected_joint_rule": "rule",
        "base_risk_level": "low",
        "knowledge_triggered": True,
        "joint_final_risk_level": "medium",
        "development_gate_passed": True,
        "operating_status": "research_candidate",
        "formal_warning_allowed": False,
        "generation_mode": "openai_luna",
        "timeline_analysis": [
            {**item, "signal_analysis_zh": "受控分析"} for item in timeline
        ],
        "executive_summary_zh": "综合结论",
        "spatial_temporal_analysis_zh": "时空分析",
        "knowledge_graph_analysis_zh": "图谱分析",
        "uncertainty_analysis_zh": "不确定性",
        "provenance_summary_zh": "溯源",
    }
    assert validate_live_report(report, packet, "openai_luna") == []
    report["joint_final_risk_level"] = "high"
    assert "joint_final_risk_level changed an immutable decision" in validate_live_report(
        report, packet, "openai_luna"
    )


def test_live_agent_schema_is_valid_json() -> None:
    schema = json.loads(
        (ROOT / "schemas/agent_joint_forecast_report_v5.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["truth_accessed"]["const"] is False
    assert schema["properties"]["neo4j_query_mode"]["const"] == "live_neo4j"


def test_live_integration_manifest_hashes_real_reports() -> None:
    manifest = json.loads(
        (ROOT / "manifests/joint_agent_live_integration_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "passed"
    assert manifest["runtime"]["neo4j_bolt_connected"] is True
    assert manifest["runtime"]["truth_accessed"] is False
    for section, mode in (
        ("heavy_rain", "openai_luna"),
        ("heatwave", "openai_terra"),
    ):
        item = manifest[section]
        report_path = ROOT / item["report_json"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert hashlib.sha256(report_path.read_bytes()).hexdigest() == item[
            "report_json_sha256"
        ]
        assert report["generation_mode"] == mode
        assert report["neo4j_query_mode"] == "live_neo4j"
        assert report["truth_accessed"] is False
