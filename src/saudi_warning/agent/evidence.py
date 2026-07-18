"""Build a deterministic evidence packet from Risk JSON and a graph bundle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from saudi_warning.risk.validation import load_region_ids, validate_result


PROTECTED_RISK_FIELDS = (
    "case_id",
    "region_id",
    "hazard",
    "risk_level",
    "risk_score",
    "confidence",
    "rule_id",
    "rule_status",
    "lead_time_hours",
    "valid_start_time",
    "valid_end_time",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _relation_targets(
    relations: list[dict[str, Any]], relation_type: str, start_id: str
) -> list[dict[str, Any]]:
    return [
        relation
        for relation in relations
        if relation.get("type") == relation_type and relation.get("start_id") == start_id
    ]


def build_evidence_packet(
    risk_path: Path,
    bundle_path: Path,
    *,
    mode: str = "formal",
    schema_path: Path = Path("schemas/risk_result.schema.json"),
    regions_path: Path = Path("configs/region_registry.csv"),
    neo4j_verification_path: Path = Path("manifests/neo4j_live_verification.json"),
) -> dict[str, Any]:
    """Return one immutable, JSON-serializable packet for the reporting Agent."""

    if mode not in {"development", "formal"}:
        raise ValueError(f"unsupported Agent mode: {mode}")
    risk = _load_object(risk_path)
    schema = _load_object(schema_path)
    errors = validate_result(
        risk,
        schema,
        load_region_ids(regions_path),
        require_frozen=mode == "formal",
    )
    if errors:
        raise ValueError("invalid Risk JSON: " + "; ".join(errors))

    bundle = _load_object(bundle_path)
    if bundle.get("schema_version") != "kg_bundle_v1":
        raise ValueError("knowledge-graph bundle must use kg_bundle_v1")
    nodes = bundle.get("nodes")
    relations = bundle.get("relations")
    if not isinstance(nodes, list) or not isinstance(relations, list):
        raise ValueError("knowledge-graph bundle must contain node and relation arrays")

    node_index = {
        (str(node.get("label")), str(node.get("id"))): node
        for node in nodes
        if isinstance(node, dict)
    }
    risk_id = f"{risk['case_id']}:{risk['region_id']}:{risk['hazard']}"
    graph_risk_node = node_index.get(("RiskAssessment", risk_id))
    if graph_risk_node is None:
        raise ValueError(f"RiskAssessment {risk_id!r} is absent from the graph bundle")
    graph_risk = graph_risk_node.get("properties", {})
    mismatches = [
        field for field in PROTECTED_RISK_FIELDS if graph_risk.get(field) != risk.get(field)
    ]
    if mismatches:
        raise ValueError("Risk JSON and graph bundle disagree on: " + ", ".join(mismatches))

    case_links = _relation_targets(relations, "BASED_ON", risk_id)
    region_links = _relation_targets(relations, "CONCERNS", risk_id)
    rule_links = _relation_targets(relations, "EVALUATED_BY", risk_id)
    if len(case_links) != 1 or len(region_links) != 1 or len(rule_links) != 1:
        raise ValueError("risk trace must have exactly one case, region, and rule link")
    case_id = str(case_links[0]["end_id"])
    region_id = str(region_links[0]["end_id"])
    rule_id = str(rule_links[0]["end_id"])
    case_node = node_index.get(("ForecastCase", case_id))
    region_node = node_index.get(("Region", region_id))
    rule_node = node_index.get(("Rule", rule_id))
    if case_node is None or region_node is None or rule_node is None:
        raise ValueError("risk trace points to a missing graph node")

    event_links = _relation_targets(relations, "VALID_FOR", case_id)
    events: list[dict[str, Any]] = []
    impact_records: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for link in event_links:
        event_id = str(link["end_id"])
        event_node = node_index.get(("HistoricalEvent", event_id))
        if event_node is None:
            raise ValueError(f"HistoricalEvent {event_id!r} is missing")
        events.append({"id": event_id, **event_node.get("properties", {})})
        for evidence_link in _relation_targets(relations, "EVALUATED_BY", event_id):
            source_id = str(evidence_link["end_id"])
            source_ids.add(source_id)
            impact_records.append(
                {
                    "event_id": event_id,
                    "source_id": source_id,
                    **evidence_link.get("properties", {}),
                }
            )

    sources = []
    for source_id in sorted(source_ids):
        node = node_index.get(("Evidence", source_id))
        if node is None:
            raise ValueError(f"Evidence {source_id!r} is missing")
        sources.append({"id": source_id, **node.get("properties", {})})

    region_cases: list[dict[str, Any]] = []
    for link in relations:
        if link.get("type") != "CONCERNS" or link.get("end_id") != region_id:
            continue
        linked_case = node_index.get(("ForecastCase", str(link.get("start_id"))))
        if linked_case is None:
            continue
        properties = linked_case.get("properties", {})
        region_cases.append(
            {
                "case_id": linked_case.get("id"),
                "initial_time": properties.get("initial_time"),
                "hazard": properties.get("hazard"),
                "case_role": properties.get("case_role"),
                "dataset_split": properties.get("dataset_split"),
                "impact_evidence_status": properties.get("impact_evidence_status"),
            }
        )
    region_cases.sort(key=lambda item: (str(item.get("initial_time")), str(item["case_id"])))

    live_verification: dict[str, Any] | None = None
    if neo4j_verification_path.exists():
        live_verification = _load_object(neo4j_verification_path)
        if live_verification.get("status") != "passed":
            raise ValueError("recorded Neo4j live verification did not pass")
        if live_verification.get("bundle_sha256") != _sha256(bundle_path):
            raise ValueError("Neo4j live verification does not match the selected graph bundle")

    boundaries = [
        (
            f"图谱bundle在{bundle.get('generated_at', 'unknown')}生成时的原始声明："
            f"{bundle.get('warning_zh', '缺失')}"
        ),
        "Agent不得改变Risk JSON中的等级、分数、阈值、规则状态或验证结论。",
        "unknown表示证据不足，不等于没有灾害影响。",
        "历史回放和development结果不得描述为实时业务预警。",
        "高温draft/blocked结果不得进入正式报告模式。",
    ]
    if live_verification is not None:
        boundaries.insert(
            1,
            (
                "后续Neo4j本地实机联调已通过："
                f"{live_verification.get('node_count')}节点、"
                f"{live_verification.get('relationship_count')}关系、"
                f"{live_verification.get('constraint_count')}约束；"
                "该结果不是生产部署声明。"
            ),
        )

    return {
        "schema_version": "agent_evidence_packet_v1",
        "mode": mode,
        "formal_eligible": risk.get("rule_status") == "frozen",
        "risk": risk,
        "graph": {
            "risk_id": risk_id,
            "case": {"id": case_id, **case_node.get("properties", {})},
            "region": {"id": region_id, **region_node.get("properties", {})},
            "rule": {"id": rule_id, **rule_node.get("properties", {})},
            "events": events,
            "impact_records": impact_records,
            "sources": sources,
            "region_case_context": region_cases,
            "neo4j_live_verification": live_verification,
        },
        "boundaries": boundaries,
        "provenance": {
            "risk_path": risk_path.as_posix(),
            "risk_sha256": _sha256(risk_path),
            "bundle_path": bundle_path.as_posix(),
            "bundle_sha256": _sha256(bundle_path),
            "bundle_content_sha256": bundle.get("content_sha256"),
            "neo4j_verification_path": (
                neo4j_verification_path.as_posix() if live_verification is not None else None
            ),
        },
    }
