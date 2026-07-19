"""Validate and render truth-sealed forecast Agent reports."""

from __future__ import annotations

from typing import Any


REQUIRED_FIELDS = {
    "schema_version",
    "report_mode",
    "truth_accessed",
    "case_id",
    "region_id",
    "hazard",
    "risk_level",
    "risk_score",
    "confidence",
    "rule_id",
    "rule_status",
    "knowledge_prior_status",
    "knowledge_prior_risk",
    "conflict_flag",
    "attention_level",
    "shadow_correction_status",
    "shadow_suggested_risk_level",
    "shadow_may_overwrite_base_risk",
    "generation_mode",
    "status_disclosure_zh",
    "executive_summary_zh",
    "weather_evidence_zh",
    "knowledge_context_zh",
    "limitations_zh",
    "recommended_actions_zh",
    "cited_prior_source_ids",
}


def validate_forecast_report(
    report: dict[str, Any], packet: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(report))
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))
    if report.get("schema_version") != "agent_forecast_report_v3":
        errors.append("schema_version must be agent_forecast_report_v3")
    if report.get("report_mode") != "forecast":
        errors.append("report_mode must be forecast")
    if report.get("truth_accessed") is not False:
        errors.append("report must declare truth_accessed=false")
    if packet.get("truth_accessed") is not False:
        errors.append("forecast packet must prove truth_accessed=false")
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
    prior = packet["knowledge_prior"]
    if report.get("knowledge_prior_status") != prior["status"]:
        errors.append("knowledge_prior_status must preserve the guarded prior")
    if report.get("knowledge_prior_risk") != prior["risk_level"]:
        errors.append("knowledge_prior_risk must preserve the guarded prior")
    if report.get("knowledge_prior_status") != "available" and report.get(
        "knowledge_prior_risk"
    ) is not None:
        errors.append("unvalidated or missing knowledge context cannot assign risk")
    check = packet["consistency_check"]
    if report.get("conflict_flag") != check["conflict_flag"]:
        errors.append("conflict_flag must preserve the deterministic check")
    if report.get("attention_level") != check["attention_level"]:
        errors.append("attention_level must preserve the deterministic check")
    for field in (
        "shadow_correction_status",
        "shadow_suggested_risk_level",
        "shadow_may_overwrite_base_risk",
    ):
        if report.get(field) != check.get(field):
            errors.append(f"{field} must preserve the deterministic check")
    if report.get("shadow_may_overwrite_base_risk") is not False:
        errors.append("shadow correction must not overwrite base risk")
    allowed_sources = {
        source["id"] for source in packet["graph"].get("prior_sources", [])
    }
    citations = report.get("cited_prior_source_ids", [])
    if not isinstance(citations, list):
        errors.append("cited_prior_source_ids must be an array")
    else:
        unknown = sorted(set(citations) - allowed_sources)
        if unknown:
            errors.append("unknown or truth-only source IDs: " + ", ".join(unknown))
        if prior["status"] == "context_only" and set(citations) != set(
            prior["source_ids"]
        ):
            errors.append("context-only report must cite every guarded prior source")
    for field in (
        "status_disclosure_zh",
        "executive_summary_zh",
        "weather_evidence_zh",
        "knowledge_context_zh",
    ):
        if not isinstance(report.get(field), str) or not report[field].strip():
            errors.append(f"{field} must be a non-empty string")
    for field in ("limitations_zh", "recommended_actions_zh"):
        value = report.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"{field} must be an array of strings")
    return errors


def deterministic_forecast_report(packet: dict[str, Any]) -> dict[str, Any]:
    risk = packet["risk"]
    prior = packet["knowledge_prior"]
    check = packet["consistency_check"]
    summary = (
        f"{risk['region_name']}在{risk['valid_start_time']}至{risk['valid_end_time']}的"
        f"{risk['hazard']}气象风险为{risk['risk_level']}，置信度为{risk['confidence']}。"
    )
    if check["conflict_flag"] != "none":
        if check.get("attention_gate_status") == "shadow_not_validated":
            summary += "触发影子纠错候选，但它尚未取得新的前瞻或独立验证，默认关注级别不变。"
        elif check.get("attention_gate_status") == "development_gate_failed_diagnostic_only":
            summary += "存在未通过development门槛的内部诊断记录，默认关注级别不变。"
        else:
            summary += "预测内部证据存在需人工关注的一致性冲突，但风险等级保持不变。"
    if prior["status"] == "context_only":
        context = prior["context"]
        terrain = context["terrain"]
        precipitation = context["precipitation_climatology"]
        knowledge_text = (
            prior["reason_zh"]
            + f"该ADM1高程P10/P90为{terrain['p10_m']}/{terrain['p90_m']} m，"
            + "对应月份长期降水区域均值/P90为"
            + f"{precipitation['mean_mm']}/{precipitation['p90_mm']} mm。"
            + check["rationale_zh"]
        )
    else:
        knowledge_text = prior["reason_zh"] + check["rationale_zh"]
    if check.get("attention_gate_status") == "shadow_not_validated":
        diagnostic_action = (
            "影子纠错建议仅供人工复核；在取得新的前瞻或独立证据前，不覆盖冻结Risk JSON。"
        )
    elif check.get("attention_gate_status") == "development_gate_failed_diagnostic_only":
        diagnostic_action = (
            "保留possible_underestimation作为失败候选审计，不提升默认关注级别；"
            "如获得全新development证据再重新预注册。"
        )
    else:
        diagnostic_action = (
            "若存在有效possible_underestimation或主指标缺失，进行人工气象复核。"
        )
    return {
        "schema_version": "agent_forecast_report_v3",
        "report_mode": "forecast",
        "truth_accessed": False,
        "case_id": risk["case_id"],
        "region_id": risk["region_id"],
        "hazard": risk["hazard"],
        "risk_level": risk["risk_level"],
        "risk_score": risk["risk_score"],
        "confidence": risk["confidence"],
        "rule_id": risk["rule_id"],
        "rule_status": risk["rule_status"],
        "knowledge_prior_status": prior["status"],
        "knowledge_prior_risk": prior["risk_level"],
        "conflict_flag": check["conflict_flag"],
        "attention_level": check["attention_level"],
        "shadow_correction_status": check["shadow_correction_status"],
        "shadow_suggested_risk_level": check["shadow_suggested_risk_level"],
        "shadow_may_overwrite_base_risk": check[
            "shadow_may_overwrite_base_risk"
        ],
        "generation_mode": "deterministic",
        "status_disclosure_zh": (
            "无真值预测模式；本报告未读取同期观测、灾害影响、新闻真值或事后验证。"
            "本案例为使用后期方法参考进行的2020迁移回放，不是实时业务预警。"
        ),
        "executive_summary_zh": summary,
        "weather_evidence_zh": (
            f"Risk JSON包含{len(risk.get('supporting_evidence', []))}条支持证据、"
            f"{len(risk.get('contradicting_evidence', []))}条反向证据和"
            f"{len(risk.get('missing_evidence', []))}条缺失证据。"
        ),
        "knowledge_context_zh": knowledge_text,
        "limitations_zh": list(packet["boundaries"]),
        "recommended_actions_zh": [
            "保持Risk JSON原始风险等级，不由报告层改写。",
            diagnostic_action,
            "预测锁定后才能由Verification Agent读取2020真值并判断命中或漏报。",
        ],
        "cited_prior_source_ids": list(prior["source_ids"]),
    }


def render_forecast_report(report: dict[str, Any], packet: dict[str, Any]) -> str:
    lines = [
        "# 极端天气预测报告（无真值模式）",
        "",
        f"> **状态声明：{report['status_disclosure_zh']}**",
        "",
        "## 综合结论",
        "",
        report["executive_summary_zh"],
        "",
        "## 气象风险事实",
        "",
        f"- 案例：`{report['case_id']}`",
        f"- 区域：`{report['region_id']}`",
        f"- 灾种：`{report['hazard']}`",
        f"- 风险等级：`{report['risk_level']}`",
        f"- 风险分数：`{report['risk_score']}`",
        f"- 置信度：`{report['confidence']}`",
        f"- 规则：`{report['rule_id']}`（`{report['rule_status']}`）",
        "",
        "## 气象证据",
        "",
        report["weather_evidence_zh"],
        "",
        "## 知识图谱先验与冲突检查",
        "",
        f"- 知识先验状态：`{report['knowledge_prior_status']}`",
        "- 知识先验风险：`"
        + (
            str(report["knowledge_prior_risk"])
            if report["knowledge_prior_risk"] is not None
            else "not_available"
        )
        + "`",
        f"- 冲突标记：`{report['conflict_flag']}`",
        f"- 综合关注级别：`{report['attention_level']}`",
        f"- 影子纠错状态：`{report['shadow_correction_status']}`",
        "- 影子建议风险：`"
        + str(report["shadow_suggested_risk_level"] or "none")
        + "`",
        "",
        report["knowledge_context_zh"],
        "",
        "## 限制",
        "",
    ]
    lines.extend(f"- {item}" for item in report["limitations_zh"])
    lines.extend(["", "## 建议", ""])
    lines.extend(f"- {item}" for item in report["recommended_actions_zh"])
    lines.extend(["", "## 预测前可用来源", ""])
    if not report["cited_prior_source_ids"]:
        lines.append("- 当前没有满足起报时间边界的外部历史先验来源。")
    else:
        lines.extend(
            f"- `{source_id}`" for source_id in report["cited_prior_source_ids"]
        )
    lines.extend(
        [
            "",
            "## 生成与溯源",
            "",
            f"- 生成模式：`{report['generation_mode']}`",
            f"- Risk SHA-256：`{packet['provenance']['risk_sha256']}`",
            f"- 真值访问：`{str(report['truth_accessed']).lower()}`",
            "- 本报告不能判断事后是否命中、漏报或误报。",
            "",
        ]
    )
    return "\n".join(lines)
