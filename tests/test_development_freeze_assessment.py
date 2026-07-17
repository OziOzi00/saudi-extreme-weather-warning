import csv
from pathlib import Path


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
    assert "insufficient_event_cases" in heat["blocking_reasons"]
    assert "observation_qc_not_accepted" in heat["blocking_reasons"]
    assert heat["observation_qc_statuses"] == "provisional"
