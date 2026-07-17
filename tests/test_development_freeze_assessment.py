import csv
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ASSESSMENT = ROOT / "manifests" / "development_v2_freeze_assessment.csv"


def test_v2_freeze_assessment_is_hazard_specific() -> None:
    with ASSESSMENT.open(encoding="utf-8", newline="") as stream:
        rows = {row["hazard"]: row for row in csv.DictReader(stream)}

    assert set(rows) == {"heavy_rain", "heatwave"}
    rain = rows["heavy_rain"]
    heat = rows["heatwave"]
    assert rain["freeze_recommendation"] == "eligible_to_freeze"
    assert rain["rule_status"] == "frozen"
    assert float(rain["target_window_recall"]) == 0.6
    assert float(rain["target_window_specificity"]) == 1.0
    assert rain["observation_qc_statuses"] == "accepted"
    assert heat["freeze_recommendation"] == "blocked"
    assert heat["rule_status"] == "draft"
    assert int(heat["event_cases"]) == 4
    assert int(heat["control_cases"]) == 2
    assert float(heat["target_window_recall"]) == pytest.approx(1 / 7)
    assert float(heat["target_window_specificity"]) == 1.0
    assert float(heat["event_case_detection_fraction"]) == 0.25
    assert "target_window_recall_below_gate" in heat["blocking_reasons"]
    assert "event_case_detection_below_gate" in heat["blocking_reasons"]
    assert "insufficient_event_cases" not in heat["blocking_reasons"]
    assert heat["observation_qc_statuses"] == "accepted"
