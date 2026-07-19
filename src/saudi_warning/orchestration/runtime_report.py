"""Publish a runtime prediction lock to Neo4j and generate a guarded live report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from saudi_warning.agent.joint_openai_runtime import generate_joint_report
from saudi_warning.agent.run_joint_live_report import (
    _generation_mode,
    render_markdown,
    validate_live_report,
)
from saudi_warning.knowledge_graph.joint_runtime import (
    prediction_rows,
    query_joint_context,
    sha256,
    upsert_joint_predictions,
)


def build_runtime_packet(
    root: Path,
    *,
    prediction_lock: Path,
    hazard: str,
    runtime_namespace: str,
    case_id: str,
    region_id: str,
    lead_time_hours: int,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
) -> dict[str, Any]:
    """Build evidence from an arbitrary new-case lock without opening truth."""
    predictions = pd.read_csv(prediction_lock)
    focus = predictions[
        predictions["case_id"].astype(str).eq(case_id)
        & predictions["region_id"].astype(str).eq(region_id)
        & predictions["lead_time_hours"].astype(int).eq(int(lead_time_hours))
    ]
    if len(focus) != 1:
        raise ValueError("expected exactly one focus window in runtime prediction lock")
    selection_path = root / "manifests/joint_pipeline_selection_lock_v2.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selected = selection[hazard]["selected"]
    lock_hash = sha256(prediction_lock)
    rows = prediction_rows(
        predictions,
        hazard=hazard,
        split=runtime_namespace,
        selected_rule=str(selected["method"]),
        prediction_lock_sha256=lock_hash,
    )
    counts = upsert_joint_predictions(
        rows, uri=neo4j_uri, user=neo4j_user, password=neo4j_password
    )
    context = query_joint_context(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        hazard=hazard,
        split=runtime_namespace,
        case_id=case_id,
        region_id=region_id,
    )
    if context["prediction_lock_sha256"] != lock_hash:
        raise ValueError("Neo4j runtime context hash does not match prediction lock")
    graph_focus = [
        item for item in context["timeline"]
        if int(item["lead_time_hours"]) == int(lead_time_hours)
    ]
    if len(graph_focus) != 1:
        raise ValueError("Neo4j runtime context does not contain one focus window")
    item = graph_focus[0]
    policy = yaml.safe_load(
        (root / "configs/joint_operating_policy_v2.yaml").read_text(encoding="utf-8")
    )
    passed = bool(selected["passes_all_gates"])
    metric_names = (
        [
            "target_window_recall",
            "target_window_specificity",
            "event_case_detection_fraction",
            "control_case_rejection_fraction",
        ]
        if hazard == "heavy_rain"
        else [
            "observed_hot_day_recall",
            "observed_nonhot_day_specificity",
            "event_case_detection_fraction",
            "control_case_rejection_fraction",
        ]
    )
    return {
        "schema_version": "joint_runtime_agent_evidence_packet_v1",
        "truth_accessed": False,
        "joint_decision": {
            "case_id": case_id,
            "region_id": region_id,
            "hazard": hazard,
            "lead_time_hours": int(lead_time_hours),
            "selected_joint_rule": str(selected["method"]),
            "base_risk_level": item["base_risk_level"],
            "knowledge_triggered": bool(item["knowledge_triggered"]),
            "joint_final_risk_level": item["joint_final_risk_level"],
            "development_gate_passed": passed,
            "operating_status": "research_candidate" if passed else "research_only_blocked",
            "formal_warning_allowed": False,
            "forecast_features": item["forecast_features"],
        },
        "neo4j_context": context,
        "method_status": {
            "passes_all_development_gates": passed,
            "operating_status": "research_candidate" if passed else "research_only_blocked",
            "formal_warning_allowed": False,
            "development_metrics": {key: selected[key] for key in metric_names},
            "policy_reason_zh": policy["hazards"][hazard]["reason"],
        },
        "provenance": {
            "prediction_lock_path": prediction_lock.relative_to(root).as_posix(),
            "prediction_lock_sha256": lock_hash,
            "selection_lock_path": selection_path.relative_to(root).as_posix(),
            "selection_lock_sha256": sha256(selection_path),
            "neo4j_query_mode": "live_neo4j",
            "neo4j_import_counts": counts,
            "runtime_namespace": runtime_namespace,
        },
        "constraints": [
            "不得读取或推测同期观测、灾害影响、新闻、命中、漏报和事后验证。",
            "不得修改基础风险、图谱触发状态或联合最终风险。",
            "必须分析 Neo4j 返回的全部 24/48/72 小时窗口。",
            "当前产物是研究原型输出，不是正式业务预警。",
        ],
    }


def generate_runtime_report(
    packet: dict[str, Any],
    *,
    models: list[str],
    output_json: Path,
    output_markdown: Path,
    evidence_output: Path,
) -> tuple[dict[str, Any], str]:
    """Generate with Luna first, then Terra, while preserving all decisions."""
    errors: list[str] = []
    report: dict[str, Any] | None = None
    used_model = ""
    for model in dict.fromkeys(models):
        try:
            candidate = generate_joint_report(packet, model)
            mode = _generation_mode(model)
            candidate["generation_mode"] = mode
            errors = validate_live_report(candidate, packet, mode)
            if not errors:
                report = candidate
                used_model = model
                break
        except Exception as exc:
            errors = [f"{model}: {type(exc).__name__}: {exc}"]
    if report is None:
        raise RuntimeError("runtime report Agent failed: " + "; ".join(errors))
    for path in (output_json, output_markdown, evidence_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output_markdown.write_text(render_markdown(report, packet), encoding="utf-8")
    evidence_output.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report, used_model
