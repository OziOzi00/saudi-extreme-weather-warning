import json
from pathlib import Path

from saudi_warning.knowledge_graph.static_context import validate_static_context


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "handoff/knowledge_prior/static_context_v1.json"


def test_versioned_static_context_is_truth_sealed_and_context_only() -> None:
    context = json.loads(CONTEXT.read_text(encoding="utf-8"))

    assert validate_static_context(context) == []
    assert context["truth_accessed"] is False
    assert context["may_change_meteorological_risk"] is False
    assert len(context["profiles"]) == 13 * 12
    assert {source["id"] for source in context["sources"]} == {
        "WORLDCLIM21_ELEV_10M",
        "WORLDCLIM21_PREC_10M",
    }
    assert all(profile["knowledge_prior_risk"] is None for profile in context["profiles"])


def test_jazan_may_profile_has_auditable_temporal_and_source_fields() -> None:
    context = json.loads(CONTEXT.read_text(encoding="utf-8"))
    profile = next(
        item
        for item in context["profiles"]
        if item["region_id"] == "SA-09" and item["month"] == 5
    )

    assert profile["temporal"]["available_at"] == "2020-03-15T00:00:00Z"
    assert profile["temporal"]["available_at"] < "2020-05-01T00:00:00Z"
    assert profile["prior_status"] == "context_only"
    assert profile["terrain"]["p90_m"] > profile["terrain"]["p10_m"]
    assert profile["precipitation_climatology"]["mean_mm"] >= 0
    assert profile["source_ids"] == [
        "WORLDCLIM21_ELEV_10M",
        "WORLDCLIM21_PREC_10M",
    ]
