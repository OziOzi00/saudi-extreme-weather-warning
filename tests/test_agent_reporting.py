import copy
from pathlib import Path

import pytest

from saudi_warning.agent.evidence import build_evidence_packet
from saudi_warning.agent.output import (
    deterministic_agent_report,
    render_agent_report,
    validate_agent_report,
)


ROOT = Path(__file__).resolve().parents[1]
RISK = (
    ROOT
    / "handoff"
    / "risk_results"
    / "development_heavy_rain"
    / "risk_20200501_00_024_SA-09_heavy_rain.json"
)
BUNDLE = ROOT / "handoff" / "knowledge_graph" / "heavy_rain_evaluation_bundle.json"


def _packet() -> dict:
    return build_evidence_packet(
        RISK,
        BUNDLE,
        mode="formal",
        schema_path=ROOT / "schemas" / "risk_result.schema.json",
        regions_path=ROOT / "configs" / "region_registry.csv",
        neo4j_verification_path=ROOT / "manifests" / "neo4j_live_verification.json",
    )


def test_agent_packet_closes_risk_graph_and_source_trace() -> None:
    packet = _packet()

    assert packet["formal_eligible"] is True
    assert packet["graph"]["risk_id"] == "20200501_00_024:SA-09:heavy_rain"
    assert packet["graph"]["case"]["id"] == "20200501_00"
    assert packet["graph"]["region"]["id"] == "SA-09"
    assert packet["graph"]["rule"]["rule_status"] == "frozen"
    assert {item["source_id"] for item in packet["graph"]["impact_records"]} == {
        "SRC-WATAN-20200502"
    }
    assert len(packet["provenance"]["risk_sha256"]) == 64
    assert packet["graph"]["neo4j_live_verification"]["status"] == "passed"
    assert any("后续Neo4j本地实机联调已通过" in item for item in packet["boundaries"])


def test_deterministic_fallback_passes_same_guard_and_renders_sources() -> None:
    packet = _packet()
    report = deterministic_agent_report(packet)

    assert validate_agent_report(report, packet) == []
    markdown = render_agent_report(report, packet)
    assert "冻结规则研究回放" in markdown
    assert "SRC-WATAN-20200502" in markdown
    assert packet["provenance"]["risk_sha256"] in markdown


def test_guard_rejects_changed_risk_and_fabricated_source() -> None:
    packet = _packet()
    report = deterministic_agent_report(packet)
    tampered = copy.deepcopy(report)
    tampered["risk_level"] = "high"
    tampered["cited_source_ids"].append("SRC-FABRICATED")

    errors = validate_agent_report(tampered, packet)
    assert "risk_level must exactly preserve Risk JSON" in errors
    assert "unknown source IDs: SRC-FABRICATED" in errors


def test_formal_packet_rejects_non_frozen_result(tmp_path: Path) -> None:
    import json

    value = json.loads(RISK.read_text(encoding="utf-8"))
    value["rule_status"] = "draft"
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="formal delivery requires explicit frozen status"):
        build_evidence_packet(
            path,
            BUNDLE,
            mode="formal",
            schema_path=ROOT / "schemas" / "risk_result.schema.json",
            regions_path=ROOT / "configs" / "region_registry.csv",
            neo4j_verification_path=ROOT / "manifests" / "neo4j_live_verification.json",
        )


@pytest.mark.parametrize("api_mode", ["responses", "chat_completions"])
def test_optional_openai_agent_constructs_without_network_access(
    monkeypatch: pytest.MonkeyPatch, api_mode: str
) -> None:
    pytest.importorskip("agents")
    from saudi_warning.agent.openai_runtime import AgentReportModel, build_openai_agent

    monkeypatch.setenv("SAUDI_WARNING_AGENT_API_MODE", api_mode)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    agent = build_openai_agent(_packet(), "gpt-5.6-luna")

    assert agent.name == "Saudi Weather Controlled Report Agent"
    assert len(agent.tools) == 5
    assert agent.output_type is AgentReportModel
