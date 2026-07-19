"""Build a truth-sealed evidence packet for a forecast-mode Agent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from saudi_warning.knowledge_graph.prediction_bundle import (
    build_prediction_bundle,
    forecast_risk_view,
    validate_prediction_bundle,
)
from saudi_warning.risk.validation import load_region_ids, validate_result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _node_index(bundle: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(node["label"]), str(node["id"])): node
        for node in bundle["nodes"]
    }


def _consistency_check(
    risk: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    """Flag internal forecast-evidence conflicts without claiming ground truth."""

    supporting = [
        item
        for item in risk.get("supporting_evidence", [])
        if item.get("role") == "support"
    ]
    primary_contradictions = [
        item
        for item in risk.get("contradicting_evidence", [])
        if item.get("role") == "primary"
    ]
    missing_primary = [
        item
        for item in risk.get("missing_evidence", [])
        if item.get("role") == "primary"
    ]
    underestimation = config["heavy_rain"]["possible_underestimation"]
    summary = risk.get("indicator_summary", {})
    primary_value = summary.get("precip_spatial_p95_mm")
    primary_threshold = summary.get("precip_medium_threshold_mm")
    primary_ratio = (
        float(primary_value) / float(primary_threshold)
        if primary_value is not None
        and primary_threshold not in {None, 0}
        else None
    )
    minimum_primary_ratio = float(
        underestimation.get("minimum_primary_to_threshold_ratio", 0.0)
    )
    conflict = "none"
    rationale = "主指标与辅助证据没有触发预注册前的保守冲突提示。"
    if missing_primary:
        conflict = str(config["missing_primary"]["conflict_flag"])
        rationale = str(config["missing_primary"]["rationale_zh"])
    elif (
        risk.get("hazard") == "heavy_rain"
        and risk.get("risk_level")
        == underestimation["required_risk_level"]
        and len(primary_contradictions)
        >= int(
            underestimation["minimum_primary_contradictions"]
        )
        and len(supporting)
        >= int(
            underestimation["minimum_supporting_conditions"]
        )
        and primary_ratio is not None
        and primary_ratio >= minimum_primary_ratio
    ):
        conflict = str(
            config["heavy_rain"]["possible_underestimation"]["conflict_flag"]
        )
        rationale = str(
            config["heavy_rain"]["possible_underestimation"]["rationale_zh"]
        )
    attention = {
        "high": "urgent",
        "medium": "watch",
        "low": "routine",
    }[str(risk["risk_level"])]
    candidate_attention = attention
    if conflict == "insufficient_primary_evidence":
        candidate_attention = str(config["missing_primary"]["attention_level"])
        attention = candidate_attention
    elif conflict == "possible_underestimation":
        section = underestimation
        candidate_attention = str(section["candidate_attention_level"])
        if config.get("may_change_attention_level") is True:
            attention = candidate_attention
        else:
            attention = str(section["effective_attention_level"])
    shadow = config.get("shadow_correction", {})
    shadow_triggered = conflict == "possible_underestimation" and bool(shadow)
    return {
        "schema_version": "forecast_consistency_check_v1",
        "rule_version": config["version"],
        "rule_status": config["status"],
        "conflict_flag": conflict,
        "attention_level": attention,
        "candidate_attention_level": candidate_attention,
        "attention_gate_status": (
            "shadow_not_validated"
            if shadow_triggered and config.get("may_change_attention_level") is False
            else "development_gate_failed_diagnostic_only"
            if conflict == "possible_underestimation" and config.get("may_change_attention_level") is False
            else "active"
        ),
        "supporting_condition_count": len(supporting),
        "primary_contradiction_count": len(primary_contradictions),
        "missing_primary_count": len(missing_primary),
        "primary_to_threshold_ratio": primary_ratio,
        "minimum_primary_to_threshold_ratio": minimum_primary_ratio,
        "shadow_correction_status": (
            shadow.get("status_when_triggered", "triggered_not_activated")
            if shadow_triggered
            else shadow.get("status_when_not_triggered", "not_triggered")
        ),
        "shadow_suggested_risk_level": (
            underestimation.get("shadow_suggested_risk_level")
            if shadow_triggered
            else None
        ),
        "shadow_may_overwrite_base_risk": shadow.get(
            "may_overwrite_base_risk", False
        ),
        "rationale_zh": rationale,
        "may_change_risk_level": False,
    }


def build_forecast_evidence_packet(
    risk_path: Path,
    *,
    generated_at: str,
    schema_path: Path = Path("schemas/risk_result.schema.json"),
    regions_path: Path = Path("configs/region_registry.csv"),
    consistency_rules_path: Path = Path(
        "configs/knowledge_consistency_rules_v2.yaml"
    ),
    static_context_path: Path | None = Path(
        "handoff/knowledge_prior/static_context_v1.json"
    ),
) -> dict[str, Any]:
    """Create a packet with forecast-time facts and no observation or impact truth."""

    risk = json.loads(risk_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = validate_result(
        risk,
        schema,
        load_region_ids(regions_path),
        require_frozen=True,
    )
    if errors:
        raise ValueError("invalid Risk JSON: " + "; ".join(errors))
    consistency_rules = yaml.safe_load(
        consistency_rules_path.read_text(encoding="utf-8")
    )
    if consistency_rules.get("status") not in {
        "development_gate_failed_diagnostic_only",
        "development_selected_shadow_not_validated",
    }:
        raise ValueError("unexpected consistency-rule status")
    if consistency_rules.get("truth_access") != "forbidden":
        raise ValueError("consistency rules must forbid truth access")
    bundle = build_prediction_bundle(
        risk_path,
        regions_path,
        generated_at,
        consistency_rules_path,
        static_context_path,
    )
    bundle_errors = validate_prediction_bundle(bundle)
    if bundle_errors:
        raise ValueError("invalid prediction bundle: " + "; ".join(bundle_errors))
    index = _node_index(bundle)
    risk_id = f"{risk['case_id']}:{risk['region_id']}:{risk['hazard']}"
    graph_risk = index[("RiskAssessment", risk_id)]["properties"]
    risk_view = forecast_risk_view(risk)
    if graph_risk != risk_view:
        raise ValueError("prediction bundle risk view diverges from Risk JSON")
    base_case_id = str(risk["case_id"]).removesuffix(
        f"_{int(risk['lead_time_hours']):03d}"
    )
    profile_nodes = [
        node for node in bundle["nodes"] if node["label"] == "StaticPriorProfile"
    ]
    source_nodes = [
        node for node in bundle["nodes"] if node["label"] == "PriorSource"
    ]
    if profile_nodes:
        if len(profile_nodes) != 1:
            raise ValueError("forecast snapshot must contain at most one static profile")
        static_profile = {
            "id": profile_nodes[0]["id"],
            **profile_nodes[0]["properties"],
        }
        prior_sources = [
            {"id": node["id"], **node["properties"]} for node in source_nodes
        ]
        prior = {
            "status": "context_only",
            "risk_level": None,
            "confidence": "low",
            "reason_zh": (
                "已取得满足起报时间边界的ADM1静态地形和月降水气候背景，"
                "但它不能识别具体事件日，因此不生成知识风险等级。"
            ),
            "context": static_profile,
            "source_ids": [source["id"] for source in prior_sources],
        }
    else:
        static_profile = None
        prior_sources = []
        prior = {
            "status": "not_available",
            "risk_level": None,
            "confidence": "low",
            "reason_zh": (
                "当前无满足起报时间边界的地形、暴露度、脆弱性和历史事件先验；"
                "不得使用同期2020真值代替知识先验。"
            ),
            "context": None,
            "source_ids": [],
        }
    boundaries = [
        "Forecast Agent不得读取同期或事后的气象观测、灾害影响、新闻证据和验证结果。",
        "Risk JSON中的verification字段已从预测视图剔除，不得在预测报告中复述。",
        "风险等级、分数、置信度和规则状态必须与Risk JSON一致。",
        "知识先验不可用时必须明确写unknown/not_available，不得用同期真值补齐。",
        "未通过新验证的影子纠错只保留并列建议，不得提高默认关注级别、证明模型错误或改写气象风险。",
        "本项目使用MAZU 2025方法参考回放2020案例，属于迁移回放，不是字面意义上的2020实时业务预报。",
    ]
    return {
        "schema_version": "agent_forecast_evidence_packet_v2",
        "report_mode": "forecast",
        "temporal_mode": bundle["temporal_mode"],
        "knowledge_cutoff": bundle["knowledge_cutoff"],
        "truth_accessed": False,
        "risk": risk_view,
        "graph": {
            "bundle": bundle,
            "risk_id": risk_id,
            "case": {
                "id": base_case_id,
                **index[("ForecastCase", base_case_id)]["properties"],
            },
            "window": {
                "id": str(risk["case_id"]),
                **index[("ForecastWindow", str(risk["case_id"]))]["properties"],
            },
            "region": {
                "id": str(risk["region_id"]),
                **index[("Region", str(risk["region_id"]))]["properties"],
            },
            "rule": {
                "id": str(risk["rule_id"]),
                **index[("Rule", str(risk["rule_id"]))]["properties"],
            },
            "consistency_rule": {
                "id": str(consistency_rules["version"]),
                **index[
                    ("ConsistencyRule", str(consistency_rules["version"]))
                ]["properties"],
            },
            "static_context": static_profile,
            "prior_sources": prior_sources,
        },
        "knowledge_prior": prior,
        "consistency_check": _consistency_check(risk_view, consistency_rules),
        "boundaries": boundaries,
        "provenance": {
            "risk_path": risk_path.as_posix(),
            "risk_sha256": _sha256(risk_path),
            "prediction_bundle_content_sha256": bundle["content_sha256"],
        },
    }
