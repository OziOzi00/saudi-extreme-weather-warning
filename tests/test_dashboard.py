from __future__ import annotations

import json
from pathlib import Path

from saudi_warning.dashboard.build_data import build_bundle, write_bundle


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_bundle_uses_all_formal_risk_results_and_regions() -> None:
    bundle = build_bundle(ROOT)

    assert bundle["meta"]["risk_result_count"] == 33
    assert bundle["meta"]["region_count"] == 13
    assert len(bundle["risks"]) == 33
    assert len(bundle["regions"]) == 13
    assert {row["dataset_split"] for row in bundle["risks"]} == {
        "development",
        "independent_test",
    }


def test_dashboard_preserves_evaluation_boundaries() -> None:
    evaluation = build_bundle(ROOT)["evaluation"]

    assert evaluation["heavy_rain"] == {
        "status": "frozen",
        "split": "independent_test",
        "pairs": 18,
        "hits": 6,
        "misses": 0,
        "false_alarms": 0,
        "correct_negatives": 12,
        "pod": 1.0,
        "far": 0.0,
        "csi": 1.0,
    }
    assert evaluation["heatwave"]["status"] == "blocked"
    assert evaluation["heatwave"]["candidate_hits"] == 5
    assert evaluation["heatwave"]["target_windows"] == 9
    assert evaluation["heatwave"]["independent_opened"] is False
    assert evaluation["impact"]["negative_metrics_status"] == (
        "unavailable_no_reviewed_no_impact_truth"
    )


def test_dashboard_contains_success_and_known_miss_scenarios() -> None:
    bundle = build_bundle(ROOT)
    risks = bundle["risks"]

    success = next(
        row
        for row in risks
        if row["case_id"] == "20200725_00_072" and row["region_id"] == "SA-14"
    )
    known_miss = next(
        row
        for row in risks
        if row["case_id"] == "20200501_00_024" and row["region_id"] == "SA-09"
    )
    assert (success["region_id"], success["risk_level"], success["dataset_split"]) == (
        "SA-14",
        "high",
        "independent_test",
    )
    assert (known_miss["region_id"], known_miss["risk_level"]) == ("SA-09", "low")
    assert bundle["known_miss"]["records"][0]["primary_attribution"] == "weather_model_error"


def test_dashboard_bundle_is_deterministic_javascript(tmp_path: Path) -> None:
    first = write_bundle(tmp_path / "first.js", ROOT).read_text(encoding="utf-8")
    second = write_bundle(tmp_path / "second.js", ROOT).read_text(encoding="utf-8")

    assert first == second
    assert first.startswith("window.DASHBOARD_DATA=")
    payload = first.removeprefix("window.DASHBOARD_DATA=").removesuffix(";\n")
    assert json.loads(payload)["meta"]["risk_result_count"] == 33


def test_dashboard_exposes_dependency_free_case_exports() -> None:
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")

    assert 'id="export-png"' in html
    assert 'id="export-summary"' in html
    assert "async function exportPng()" in script
    assert "function exportSummary()" in script
    assert "html2canvas" not in script
