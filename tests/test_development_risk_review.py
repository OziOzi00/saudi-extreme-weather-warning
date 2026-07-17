import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "handoff" / "risk_dry_runs" / "development_rule_review.csv"
RESULTS = ROOT / "handoff" / "risk_dry_runs" / "development_results"


def read_audit() -> list[dict[str, str]]:
    with AUDIT.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_review_contains_only_approved_development_targets() -> None:
    rows = read_audit()

    assert len(rows) == 33
    assert {row["case_id"] for row in rows} == {
        "20200501_00",
        "20200505_00",
        "20200515_00",
        "20200619_00",
        "20200706_00",
        "20200715_00",
        "20200806_00",
        "20200908_00",
        "20200927_00",
        "20201109_00",
        "20201119_00",
    }
    assert {row["hazard"] for row in rows} == {"heavy_rain", "heatwave"}
    assert {int(row["lead_time_hours"]) for row in rows} == {24, 48, 72}
    assert all(row["rule_status"] == "draft" for row in rows)


def test_review_artifacts_match_audit_and_remain_nonformal() -> None:
    rows = read_audit()
    files = sorted(RESULTS.glob("*.json"))

    assert len(files) == len(rows) == 33
    identities = set()
    for path in files:
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["rule_status"] == "draft"
        assert result["verification"] is None
        assert result["hazard"] in {"heavy_rain", "heatwave"}
        identities.add((result["case_id"], result["region_id"], result["hazard"]))
    audit_identities = {
        (row["prediction_case_id"], row["region_id"], row["hazard"]) for row in rows
    }
    assert identities == audit_identities


def test_candidate_outcomes_are_traceable_not_final_truth() -> None:
    rows = read_audit()
    allowed = {
        "candidate_hit",
        "candidate_miss",
        "candidate_false_alarm",
        "candidate_correct_negative",
        "not_scored_context",
    }

    assert {row["candidate_outcome"] for row in rows}.issubset(allowed)
    assert all(row["primary_indicator"] for row in rows)
    assert all(row["primary_value"] for row in rows)
    assert all(row["primary_threshold"] for row in rows)
    assert all(row["weather_screening_status"] for row in rows)
    assert all(row["impact_evidence_status"] for row in rows)

    scored = [row for row in rows if row["evaluation_scope"] == "target_window"]
    context = [row for row in rows if row["evaluation_scope"] == "context_only"]
    assert len(scored) == 20
    assert len(context) == 13
    assert {row["candidate_outcome"] for row in context} == {"not_scored_context"}
