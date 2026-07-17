from __future__ import annotations

import csv
import json
from pathlib import Path

from saudi_warning.verification.impact import intervals_overlap


ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "handoff" / "impact_verification" / "positive_impact_units.csv"
ASSESSMENT = ROOT / "manifests" / "impact_layer_assessment.json"


def read_units() -> list[dict[str, str]]:
    with UNITS.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_interval_overlap_does_not_count_touching_boundaries() -> None:
    assert intervals_overlap(
        "2020-05-05T00:00:00Z",
        "2020-05-06T00:00:00Z",
        "2020-05-06T00:00:00Z",
        "2020-05-06T23:59:59Z",
    ) is False
    assert intervals_overlap(
        "2020-05-06T00:00:00Z",
        "2020-05-07T00:00:00Z",
        "2020-05-06T00:00:00Z",
        "2020-05-06T23:59:59Z",
    ) is True


def test_positive_impact_units_are_deduplicated_by_case_region() -> None:
    rows = read_units()

    assert len(rows) == 6
    assert sum(int(row["impact_record_count"]) for row in rows) == 9
    assert {row["hazard"] for row in rows} == {"heavy_rain"}
    assert all(row["evaluation_scope"] == "reviewed_positive_impact_only" for row in rows)
    assert all(int(row["risk_result_count"]) == 3 for row in rows)


def test_impact_assessment_reports_positive_coverage_only() -> None:
    result = json.loads(ASSESSMENT.read_text(encoding="utf-8"))

    assert result["status"] == "complete_with_scope_limitations"
    assert result["reviewed_positive_record_count"] == 9
    assert result["excluded_unknown_record_count"] == 3
    assert result["reviewed_negative_record_count"] == 0
    assert result["excluded_nonreviewed_record_count"] == 0
    assert result["partitions"]["development"]["detected_positive_units"] == 2
    assert result["partitions"]["development"]["eligible_positive_units"] == 3
    assert result["partitions"]["independent_test"]["detected_positive_units"] == 3
    assert result["partitions"]["independent_test"]["eligible_positive_units"] == 3
    assert result["partitions"]["all"]["positive_coverage_fraction"] == 5 / 6
    assert result["specificity"] is None
    assert result["false_alarm_ratio"] is None
    assert result["retuning_performed"] is False
    assert len(result["inputs"]["frozen_risk_result_set_sha256"]) == 64
