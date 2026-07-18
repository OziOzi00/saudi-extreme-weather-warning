import json
from pathlib import Path

from saudi_warning.knowledge_graph.spatial_diagnostics import (
    validate_spatial_diagnostics,
)


ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS = (
    ROOT / "handoff/knowledge_prior/development_spatial_diagnostics_v1.json"
)


def test_versioned_spatial_diagnostics_are_truth_sealed() -> None:
    bundle = json.loads(DIAGNOSTICS.read_text(encoding="utf-8"))

    assert validate_spatial_diagnostics(bundle) == []
    assert bundle["truth_accessed"] is False
    assert bundle["may_change_meteorological_risk"] is False
    assert len(bundle["diagnostics"]) == 15
    assert all(
        item["candidate_status"]
        == "preregistered_before_spatial_metric_evaluation"
        for item in bundle["diagnostics"]
    )


def test_preregistered_local_hotspot_candidate_did_not_trigger() -> None:
    bundle = json.loads(DIAGNOSTICS.read_text(encoding="utf-8"))
    target_misses = {
        "20200501_00_024",
        "20200501_00_048",
    }
    rows = [item for item in bundle["diagnostics"] if item["case_id"] in target_misses]

    assert len(rows) == 2
    assert all(item["candidate_triggered"] is False for item in rows)
    assert all(item["precip_spatial_p99_mm"] < 5.0 for item in rows)
    assert all(item["precip_spatial_max_mm"] < 10.0 for item in rows)
