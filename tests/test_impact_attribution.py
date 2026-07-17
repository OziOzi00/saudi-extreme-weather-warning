from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROWS = ROOT / "handoff" / "impact_verification" / "missed_impact_attribution.csv"
ASSESSMENT = ROOT / "manifests" / "impact_miss_attribution.json"
SEARCH = ROOT / "manifests" / "control_impact_evidence_search.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_missed_impact_attribution_separates_weather_and_rule_failures() -> None:
    rows = read_csv(ROWS)

    assert len(rows) == 2
    lead24 = next(row for row in rows if row["lead_time_hours"] == "24")
    lead48 = next(row for row in rows if row["lead_time_hours"] == "48")
    assert lead24["primary_attribution"] == "weather_model_error"
    assert lead24["observed_p95_crosses_medium"] == "True"
    assert lead24["forecast_p95_crosses_medium"] == "False"
    assert lead48["primary_attribution"] == "risk_rule_error"
    assert lead48["secondary_attribution"] == "weather_model_error"
    assert lead48["observed_max_crosses_high"] == "True"


def test_attribution_does_not_modify_frozen_rule() -> None:
    result = json.loads(ASSESSMENT.read_text(encoding="utf-8"))

    assert result["status"] == "completed_without_rule_retuning"
    assert result["missed_positive_unit_count"] == 1
    assert result["attributed_overlapping_window_count"] == 2
    assert result["frozen_rule_modified"] is False


def test_control_search_does_not_promote_absence_to_negative_truth() -> None:
    rows = read_csv(SEARCH)

    assert len(rows) == 4
    assert {row["outcome"] for row in rows} == {
        "no_eligible_negative_evidence_found"
    }
    assert all(
        "absence" in row["decision_reason"].lower()
        or row["candidate_type"].startswith("pre_event")
        for row in rows
    )
