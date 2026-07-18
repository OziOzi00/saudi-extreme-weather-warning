from pathlib import Path

from saudi_warning.knowledge_graph.assess_forecast_context import (
    assess_development_context,
)


ROOT = Path(__file__).resolve().parents[1]


def test_development_context_assessment_keeps_static_context_non_predictive() -> None:
    rows, assessment = assess_development_context(
        ROOT / "handoff/risk_dry_runs/development_v2_rule_review.csv",
        ROOT / "handoff/risk_results/development_heavy_rain",
        "2026-07-18T13:10:00Z",
    )

    assert assessment["dataset_split"] == "development"
    assert assessment["independent_data_accessed"] is False
    assert assessment["may_change_frozen_risk"] is False
    assert assessment["context_coverage_count"] == len(rows)
    assert assessment["context_changes_risk_count"] == 0
    assert assessment["spatial_candidate_trigger_count"] == 0
    assert assessment["spatial_candidate_decision"] == (
        "reject_no_miss_reduction_do_not_connect_to_agent_attention"
    )
    assert assessment["risk_plus_preregistered_spatial_attention"] == assessment[
        "base_risk_alert"
    ]
    assert assessment["decision"] == "retain_context_only_do_not_promote_to_knowledge_risk"
    assert all(row["truth_accessed_by_forecast"] is False for row in rows)


def test_context_assessment_rejects_non_development_review(tmp_path: Path) -> None:
    review = tmp_path / "independent_review.csv"
    review.write_text("hazard,evaluation_scope\n", encoding="utf-8")

    try:
        assess_development_context(
            review,
            ROOT / "handoff/risk_results/development_heavy_rain",
            "2026-07-18T13:10:00Z",
        )
    except ValueError as exc:
        assert "development review input only" in str(exc)
    else:
        raise AssertionError("independent review input must be rejected")
