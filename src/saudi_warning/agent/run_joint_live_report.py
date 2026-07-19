"""Run a real Neo4j-backed Luna/Terra Agent on one locked joint forecast."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from saudi_warning.agent.joint_openai_runtime import generate_joint_report
from saudi_warning.agent.run_joint_forecast_report import (
    _lock_reference,
    build_report,
)
from saudi_warning.knowledge_graph.joint_runtime import (
    prediction_rows,
    query_joint_context,
    sha256,
    upsert_joint_predictions,
)


def _generation_mode(model: str) -> str:
    lowered = model.lower()
    if "terra" in lowered:
        return "openai_terra"
    if "luna" in lowered:
        return "openai_luna"
    raise ValueError("only Luna and Terra are allowed")


def build_packet(
    root: Path,
    *,
    hazard: str,
    split: str,
    case_id: str,
    region_id: str,
    lead_time_hours: int,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deterministic = build_report(
        root, hazard, split, case_id, region_id, lead_time_hours
    )
    prediction_path, expected_hash, _ = _lock_reference(root, split, hazard)
    predictions = pd.read_csv(prediction_path)
    selection_path = root / "manifests/joint_pipeline_selection_lock_v2.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selected = selection[hazard]["selected"]
    rows = prediction_rows(
        predictions,
        hazard=hazard,
        split=split,
        selected_rule=str(selected["method"]),
        prediction_lock_sha256=expected_hash,
    )
    graph_counts = upsert_joint_predictions(
        rows, uri=neo4j_uri, user=neo4j_user, password=neo4j_password
    )
    context = query_joint_context(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        hazard=hazard,
        split=split,
        case_id=case_id,
        region_id=region_id,
    )
    if context["prediction_lock_sha256"] != expected_hash:
        raise ValueError("Neo4j context and prediction lock hash disagree")
    focus = [
        item
        for item in context["timeline"]
        if int(item["lead_time_hours"]) == int(lead_time_hours)
    ]
    if len(focus) != 1:
        raise ValueError("Neo4j did not return exactly one focus window")
    for field in (
        "base_risk_level",
        "knowledge_triggered",
        "joint_final_risk_level",
    ):
        if focus[0][field] != deterministic[field]:
            raise ValueError(f"Neo4j and prediction lock disagree on {field}")
    policy = yaml.safe_load(
        (root / "configs/joint_operating_policy_v2.yaml").read_text(encoding="utf-8")
    )
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
    packet = {
        "schema_version": "joint_live_agent_evidence_packet_v1",
        "truth_accessed": False,
        "joint_decision": {
            key: deterministic[key]
            for key in (
                "case_id",
                "region_id",
                "hazard",
                "lead_time_hours",
                "selected_joint_rule",
                "base_risk_level",
                "knowledge_triggered",
                "joint_final_risk_level",
                "development_gate_passed",
                "operating_status",
                "formal_warning_allowed",
                "forecast_features",
            )
        },
        "neo4j_context": context,
        "method_status": {
            "passes_all_development_gates": bool(selected["passes_all_gates"]),
            "operating_status": deterministic["operating_status"],
            "formal_warning_allowed": False,
            "development_metrics": {
                key: selected[key] for key in metric_names
            },
            "policy_reason_zh": policy["hazards"][hazard]["reason"],
        },
        "provenance": {
            "prediction_lock_path": str(prediction_path.relative_to(root)).replace(
                "\\", "/"
            ),
            "prediction_lock_sha256": expected_hash,
            "selection_lock_path": str(selection_path.relative_to(root)).replace(
                "\\", "/"
            ),
            "selection_lock_sha256": sha256(selection_path),
            "neo4j_query_mode": "live_neo4j",
            "neo4j_import_counts": graph_counts,
        },
        "constraints": [
            "不得读取或推测同期观测、灾害影响、新闻、命中、漏报和事后验证。",
            "不得修改基础风险、图谱触发状态或联合最终风险。",
            "必须分析Neo4j返回的全部24/48/72小时窗口。",
            "当前产物是历史迁移研究回放，不是正式业务预警。",
        ],
    }
    return packet, deterministic


def validate_live_report(
    report: dict[str, Any], packet: dict[str, Any], generation_mode: str
) -> list[str]:
    errors: list[str] = []
    decision = packet["joint_decision"]
    if report.get("schema_version") != "agent_joint_forecast_report_v5":
        errors.append("unexpected schema version")
    if report.get("report_mode") != "joint_forecast_live":
        errors.append("unexpected report mode")
    if report.get("truth_accessed") is not False:
        errors.append("truth_accessed must be false")
    if report.get("neo4j_query_mode") != "live_neo4j":
        errors.append("report must preserve live Neo4j query mode")
    mappings = {
        "case_id": "case_id",
        "region_id": "region_id",
        "hazard": "hazard",
        "focus_lead_time_hours": "lead_time_hours",
        "selected_joint_rule": "selected_joint_rule",
        "base_risk_level": "base_risk_level",
        "knowledge_triggered": "knowledge_triggered",
        "joint_final_risk_level": "joint_final_risk_level",
        "development_gate_passed": "development_gate_passed",
        "operating_status": "operating_status",
        "formal_warning_allowed": "formal_warning_allowed",
    }
    for report_field, packet_field in mappings.items():
        if report.get(report_field) != decision[packet_field]:
            errors.append(f"{report_field} changed an immutable decision")
    if report.get("generation_mode") != generation_mode:
        errors.append("generation mode does not match the model used")
    expected_timeline = packet["neo4j_context"]["timeline"]
    actual_timeline = report.get("timeline_analysis", [])
    if len(actual_timeline) != len(expected_timeline):
        errors.append("timeline does not cover every Neo4j window")
    else:
        for actual, expected in zip(actual_timeline, expected_timeline, strict=True):
            for field in (
                "lead_time_hours",
                "base_risk_level",
                "knowledge_triggered",
                "joint_final_risk_level",
            ):
                if actual.get(field) != expected[field]:
                    errors.append(f"timeline changed {field} at a forecast lead")
    for field in (
        "executive_summary_zh",
        "spatial_temporal_analysis_zh",
        "knowledge_graph_analysis_zh",
        "uncertainty_analysis_zh",
        "provenance_summary_zh",
    ):
        if not isinstance(report.get(field), str) or not report[field].strip():
            errors.append(f"{field} must be non-empty")
    return errors


def render_markdown(report: dict[str, Any], packet: dict[str, Any]) -> str:
    timeline_rows = [
        "| 时效 | 基础风险 | 图谱触发 | 联合风险 | Agent分析 |",
        "| ---: | --- | --- | --- | --- |",
    ]
    timeline_rows.extend(
        "| +{lead_time_hours}h | {base_risk_level} | {trigger} | "
        "{joint_final_risk_level} | {signal_analysis_zh} |".format(
            trigger=str(item["knowledge_triggered"]).lower(), **item
        )
        for item in report["timeline_analysis"]
    )
    limitations = "\n".join(f"- {item}" for item in report["limitations_zh"])
    actions = "\n".join(f"- {item}" for item in report["recommended_actions_zh"])
    provenance = packet["provenance"]
    return f"""# 极端天气联合Agent综合报告

> 运行模式：`{report['neo4j_query_mode']} + {report['generation_mode']}`；真值访问：`false`。

## 综合研判

{report['executive_summary_zh']}

## 锁定决策

- 案例/区域：`{report['case_id']} / {report['region_id']}`
- 灾种与重点时效：`{report['hazard']} / +{report['focus_lead_time_hours']}h`
- 基础风险：`{report['base_risk_level']}`
- 图谱触发：`{str(report['knowledge_triggered']).lower()}`
- 联合最终风险：`{report['joint_final_risk_level']}`
- 开发门槛通过：`{str(report['development_gate_passed']).lower()}`
- 运行状态：`{report['operating_status']}`
- 正式预警许可：`false`

## 24/48/72小时时间线

{chr(10).join(timeline_rows)}

## 时空与气象证据分析

{report['spatial_temporal_analysis_zh']}

## 知识图谱贡献

{report['knowledge_graph_analysis_zh']}

## 不确定性

{report['uncertainty_analysis_zh']}

## 限制

{limitations}

## 建议

{actions}

## 在线运行与溯源

{report['provenance_summary_zh']}

- Neo4j查询：`live_neo4j`
- Neo4j写入窗口数：`{provenance['neo4j_import_counts']['windows']}`
- 预测锁：`{provenance['prediction_lock_path']}`
- 预测锁SHA-256：`{provenance['prediction_lock_sha256']}`
- 选择锁SHA-256：`{provenance['selection_lock_sha256']}`
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--hazard", choices=["heavy_rain", "heatwave"], required=True)
    parser.add_argument("--split", choices=["development", "independent_test"], required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--region-id", required=True)
    parser.add_argument("--lead-time-hours", type=int, required=True)
    parser.add_argument("--model", default=os.getenv("SAUDI_WARNING_AGENT_MODEL", "gpt-5.6-luna"))
    parser.add_argument(
        "--escalation-model",
        default=os.getenv("SAUDI_WARNING_AGENT_ESCALATION_MODEL", "gpt-5.6-terra"),
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    required = ["OPENAI_API_KEY", "NEO4J_PASSWORD"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit("missing runtime secrets: " + ", ".join(missing))
    root = args.root.resolve()
    packet, _ = build_packet(
        root,
        hazard=args.hazard,
        split=args.split,
        case_id=args.case_id,
        region_id=args.region_id,
        lead_time_hours=args.lead_time_hours,
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.environ["NEO4J_PASSWORD"],
    )
    errors: list[str] = []
    report: dict[str, Any] | None = None
    used_model = ""
    for model in dict.fromkeys([args.model, args.escalation_model]):
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
        raise SystemExit("live Joint Agent failed: " + "; ".join(errors))
    for path in (args.output_json, args.output_markdown, args.evidence_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output_markdown.write_text(
        render_markdown(report, packet), encoding="utf-8"
    )
    args.evidence_output.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output_json}")
    print(f"wrote {args.output_markdown}")
    print(f"wrote {args.evidence_output}")
    print(f"model={used_model}")
    print("neo4j_query_mode=live_neo4j")
    print("truth_accessed=false")


if __name__ == "__main__":
    main()
