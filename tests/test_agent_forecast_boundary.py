import copy
import json
from pathlib import Path

import pytest

from saudi_warning.agent.forecast_evidence import build_forecast_evidence_packet
from saudi_warning.agent.forecast_output import (
    deterministic_forecast_report,
    render_forecast_report,
    validate_forecast_report,
)
from saudi_warning.knowledge_graph.prediction_bundle import (
    FORBIDDEN_LABELS,
    build_prediction_bundle,
    validate_prediction_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
RISK = (
    ROOT
    / "handoff"
    / "risk_results"
    / "development_heavy_rain"
    / "risk_20200501_00_024_SA-09_heavy_rain.json"
)
GENERATED_AT = "2026-07-18T12:00:00Z"


def _packet() -> dict:
    return build_forecast_evidence_packet(
        RISK,
        generated_at=GENERATED_AT,
        schema_path=ROOT / "schemas/risk_result.schema.json",
        regions_path=ROOT / "configs/region_registry.csv",
    )


def test_prediction_bundle_contains_no_truth_nodes_or_verification() -> None:
    bundle = build_prediction_bundle(
        RISK, ROOT / "configs/region_registry.csv", GENERATED_AT
    )

    assert validate_prediction_bundle(bundle) == []
    assert bundle["truth_accessed"] is False
    assert not ({node["label"] for node in bundle["nodes"]} & FORBIDDEN_LABELS)
    serialized = json.dumps(bundle, ensure_ascii=False)
    assert "SRC-WATAN-20200502" not in serialized
    assert '"verification"' not in serialized
    assert "fatalities_min" not in serialized


def test_forecast_packet_seals_truth_and_flags_internal_disagreement() -> None:
    packet = _packet()

    assert packet["report_mode"] == "forecast"
    assert packet["truth_accessed"] is False
    assert "verification" not in packet["risk"]
    assert len(packet["graph"]["prior_sources"]) == 2
    assert packet["knowledge_prior"]["status"] == "context_only"
    assert packet["knowledge_prior"]["risk_level"] is None
    assert packet["graph"]["static_context"]["region_id"] == "SA-09"
    assert packet["graph"]["static_context"]["month"] == 5
    assert packet["consistency_check"]["conflict_flag"] == (
        "possible_underestimation"
    )
    assert packet["consistency_check"]["candidate_attention_level"] == "watch"
    assert packet["consistency_check"]["attention_level"] == "routine"
    assert packet["consistency_check"]["attention_gate_status"] == (
        "development_gate_failed_diagnostic_only"
    )
    assert packet["consistency_check"]["may_change_risk_level"] is False


def test_clean_forecast_report_cannot_claim_same_event_truth() -> None:
    packet = _packet()
    report = deterministic_forecast_report(packet)

    assert validate_forecast_report(report, packet) == []
    assert report["truth_accessed"] is False
    markdown = render_forecast_report(report, packet)
    assert "SRC-WATAN-20200502" not in markdown
    assert "造成1人死亡" not in markdown
    assert "truth_accessed=false" not in markdown
    assert "真值访问：`false`" in markdown
    assert "possible_underestimation" in markdown
    assert "综合关注级别：`routine`" in markdown
    assert "WORLDCLIM21_ELEV_10M" in markdown


def test_forecast_packet_without_static_context_stays_not_available(
    tmp_path: Path,
) -> None:
    packet = build_forecast_evidence_packet(
        RISK,
        generated_at=GENERATED_AT,
        schema_path=ROOT / "schemas/risk_result.schema.json",
        regions_path=ROOT / "configs/region_registry.csv",
        static_context_path=tmp_path / "missing.json",
    )

    assert packet["knowledge_prior"]["status"] == "not_available"
    assert packet["graph"]["static_context"] is None
    assert packet["graph"]["prior_sources"] == []


def test_forecast_report_rejects_truth_access_claim() -> None:
    packet = _packet()
    report = deterministic_forecast_report(packet)
    report["truth_accessed"] = True

    assert "report must declare truth_accessed=false" in validate_forecast_report(
        report, packet
    )


def test_context_only_report_requires_all_guarded_sources() -> None:
    packet = _packet()
    report = deterministic_forecast_report(packet)
    report["cited_prior_source_ids"] = []

    assert "context-only report must cite every guarded prior source" in (
        validate_forecast_report(report, packet)
    )


def test_prediction_bundle_rejects_truth_node_injection() -> None:
    bundle = build_prediction_bundle(
        RISK, ROOT / "configs/region_registry.csv", GENERATED_AT
    )
    tampered = copy.deepcopy(bundle)
    tampered["nodes"].append(
        {"label": "HistoricalEvent", "id": "LEAK", "properties": {}}
    )

    assert "forbidden prediction node label: HistoricalEvent" in (
        validate_prediction_bundle(tampered)
    )


@pytest.mark.parametrize("api_mode", ["responses", "chat_completions"])
def test_forecast_openai_agent_constructs_without_network(
    monkeypatch: pytest.MonkeyPatch, api_mode: str
) -> None:
    pytest.importorskip("agents")
    from saudi_warning.agent.forecast_openai_runtime import (
        ForecastReportModel,
        build_forecast_openai_agent,
    )

    monkeypatch.setenv("SAUDI_WARNING_AGENT_API_MODE", api_mode)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    agent = build_forecast_openai_agent(_packet(), "gpt-5.6-luna")

    assert agent.name == "Saudi Weather Truth-Sealed Forecast Agent"
    assert len(agent.tools) == 5
    assert agent.output_type is ForecastReportModel
