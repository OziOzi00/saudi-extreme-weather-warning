from pathlib import Path

from saudi_warning.demo.build_summary import RELEASE_TAG, build_demo_summary


ROOT = Path(__file__).resolve().parents[1]


def test_prototype_summary_validates_frozen_pipeline() -> None:
    summary = build_demo_summary(ROOT)
    assert summary["release_tag"] == RELEASE_TAG
    assert summary["release_status"] == "stable_research_prototype"
    assert summary["pipeline"]["delivered_netcdf_count"] == 57
    assert summary["pipeline"]["development_pair_count"] == 189
    assert summary["pipeline"]["frozen_risk_json_count"] == 33


def test_prototype_summary_preserves_hazard_gates() -> None:
    summary = build_demo_summary(ROOT)
    assert summary["heavy_rain"]["rule_status"] == "frozen"
    assert summary["heavy_rain"]["independent_spatial_p95_contingency"] == {
        "hits": 6,
        "misses": 0,
        "false_alarms": 0,
        "correct_negatives": 12,
    }
    assert summary["heatwave"]["rule_status"] == "draft"
    assert summary["heatwave"]["freeze_recommendation"] == "blocked"
    assert summary["heatwave"]["independent_evaluation_opened"] is False


def test_prototype_summary_includes_success_and_known_miss() -> None:
    cases = build_demo_summary(ROOT)["demonstration_cases"]
    assert cases["covered_positive"]["lead048_risk_level"] == "medium"
    assert cases["covered_positive"]["lead072_risk_level"] == "high"
    assert cases["known_miss"]["lead024_risk_level"] == "low"
    assert cases["known_miss"]["lead048_risk_level"] == "low"
    assert cases["known_miss"]["frozen_rule_modified"] is False


def test_prototype_summary_does_not_overclaim_impact_or_deployment() -> None:
    summary = build_demo_summary(ROOT)
    assert summary["impact_layer"]["covered_positive_units"] == 5
    assert summary["impact_layer"]["eligible_positive_units"] == 6
    assert summary["impact_layer"]["reviewed_negative_units"] == 0
    assert summary["impact_layer"]["negative_class_metrics_available"] is False
    graph = summary["knowledge_graph_live_development_verification"]
    assert graph["production_deployment"] is False
    assert "research_prototype_not_operational_forecast_service" in summary["release_limitations"]
