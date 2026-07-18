"""Validate and render structured Agent reports without trusting model prose."""

from __future__ import annotations

from typing import Any


REQUIRED_FIELDS = {
    "schema_version",
    "case_id",
    "region_id",
    "hazard",
    "risk_level",
    "risk_score",
    "confidence",
    "rule_id",
    "rule_status",
    "generation_mode",
    "status_disclosure_zh",
    "executive_summary_zh",
    "evidence_summary_zh",
    "limitations_zh",
    "recommended_actions_zh",
    "cited_source_ids",
}


def validate_agent_report(report: dict[str, Any], packet: dict[str, Any]) -> list[str]:
    """Check protected facts, citations, disclosure, and structural completeness."""

    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(report))
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))
    if report.get("schema_version") != "agent_report_v1":
        errors.append("schema_version must be agent_report_v1")
    risk = packet["risk"]
    for field in (
        "case_id",
        "region_id",
        "hazard",
        "risk_level",
        "risk_score",
        "confidence",
        "rule_id",
        "rule_status",
    ):
        if report.get(field) != risk.get(field):
            errors.append(f"{field} must exactly preserve Risk JSON")
    if report.get("generation_mode") not in {
        "deterministic",
        "openai_luna",
        "openai_terra",
    }:
        errors.append("generation_mode is unsupported")
    for field in ("status_disclosure_zh", "executive_summary_zh", "evidence_summary_zh"):
        if not isinstance(report.get(field), str) or not report[field].strip():
            errors.append(f"{field} must be a non-empty string")
    for field in ("limitations_zh", "recommended_actions_zh", "cited_source_ids"):
        value = report.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"{field} must be an array of strings")
    allowed_sources = {source["id"] for source in packet["graph"]["sources"]}
    cited_sources = report.get("cited_source_ids", [])
    if isinstance(cited_sources, list):
        unknown = sorted(set(cited_sources) - allowed_sources)
        if unknown:
            errors.append("unknown source IDs: " + ", ".join(unknown))
    disclosure = str(report.get("status_disclosure_zh", ""))
    if risk.get("rule_status") != "frozen" and "正式" not in disclosure:
        errors.append("non-frozen output must explicitly disclose formal-use restriction")
    if packet.get("mode") == "formal" and risk.get("rule_status") != "frozen":
        errors.append("formal mode requires a frozen rule")
    return errors


def deterministic_agent_report(packet: dict[str, Any]) -> dict[str, Any]:
    """Provide a no-API fallback that obeys the same output contract."""

    risk = packet["risk"]
    graph = packet["graph"]
    status = risk.get("rule_status", "unknown")
    disclosure = (
        "冻结规则研究回放；仍须结合验证状态和证据边界使用。"
        if status == "frozen"
        else "规则尚未冻结，仅供研究联调，不能作为正式预警。"
    )
    impacts = graph["impact_records"]
    impact_text = (
        f"图谱中有{len(impacts)}条与当前历史事件关联的影响证据记录。"
        if impacts
        else "图谱中没有与当前案例匹配的影响记录，影响状态保持unknown。"
    )
    return {
        "schema_version": "agent_report_v1",
        "case_id": risk["case_id"],
        "region_id": risk["region_id"],
        "hazard": risk["hazard"],
        "risk_level": risk["risk_level"],
        "risk_score": risk["risk_score"],
        "confidence": risk["confidence"],
        "rule_id": risk["rule_id"],
        "rule_status": status,
        "generation_mode": "deterministic",
        "status_disclosure_zh": disclosure,
        "executive_summary_zh": (
            f"{risk['region_name']}在{risk['valid_start_time']}至{risk['valid_end_time']}的"
            f"{risk['hazard']}风险等级为{risk['risk_level']}，置信度为{risk['confidence']}。"
        ),
        "evidence_summary_zh": (
            f"Risk JSON记录{len(risk['supporting_evidence'])}条支持证据、"
            f"{len(risk['contradicting_evidence'])}条反向证据和"
            f"{len(risk['missing_evidence'])}条缺失证据。{impact_text}"
        ),
        "limitations_zh": list(packet["boundaries"]),
        "recommended_actions_zh": [
            "按Risk JSON原始等级使用，不由报告层改写风险分数或阈值。",
            "结合验证状态、缺失证据和数据集划分进行人工复核。",
        ],
        "cited_source_ids": sorted({item["source_id"] for item in impacts}),
    }


def render_agent_report(report: dict[str, Any], packet: dict[str, Any]) -> str:
    """Render a validated structured Agent report to auditable Markdown."""

    sources = {source["id"]: source for source in packet["graph"]["sources"]}
    lines = [
        "# Agent综合极端天气报告",
        "",
        f"> **状态声明：{report['status_disclosure_zh']}**",
        "",
        "## 综合结论",
        "",
        report["executive_summary_zh"],
        "",
        "## 受保护的风险事实",
        "",
        f"- 案例：`{report['case_id']}`",
        f"- 区域：`{report['region_id']}`",
        f"- 灾种：`{report['hazard']}`",
        f"- 风险等级：`{report['risk_level']}`",
        f"- 风险分数：`{report['risk_score']}`",
        f"- 置信度：`{report['confidence']}`",
        f"- 规则：`{report['rule_id']}`（`{report['rule_status']}`）",
        "",
        "## 证据综合",
        "",
        report["evidence_summary_zh"],
        "",
        "## 限制",
        "",
    ]
    lines.extend(f"- {item}" for item in report["limitations_zh"])
    lines.extend(["", "## 建议", ""])
    lines.extend(f"- {item}" for item in report["recommended_actions_zh"])
    lines.extend(["", "## 引用来源", ""])
    if not report["cited_source_ids"]:
        lines.append("- 当前没有与该案例匹配的图谱来源；不得据此推断无灾害影响。")
    for source_id in report["cited_source_ids"]:
        source = sources[source_id]
        lines.append(
            f"- `{source_id}`：[{source.get('publisher', source_id)}]"
            f"({source.get('url', '')})"
        )
    lines.extend(
        [
            "",
            "## 生成与溯源",
            "",
            f"- 生成模式：`{report['generation_mode']}`",
            f"- Risk SHA-256：`{packet['provenance']['risk_sha256']}`",
            f"- 图谱 bundle SHA-256：`{packet['provenance']['bundle_sha256']}`",
            "- Agent只做受控整合，没有重新计算或修改气象指标、阈值和风险等级。",
            "",
        ]
    )
    return "\n".join(lines)
