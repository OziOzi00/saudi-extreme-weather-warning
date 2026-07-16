import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "configs" / "case_catalog_candidates.csv"
TRUTH = ROOT / "handoff" / "disaster_truth" / "disaster_impact_truth.csv"
REVIEWS = ROOT / "manifests" / "disaster_evidence_review.csv"
RECOMMENDATIONS = ROOT / "manifests" / "case_approval_recommendations.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_evidence_review_is_complete_without_inventing_negative_impact() -> None:
    truth = read_csv(TRUTH)
    reviews = read_csv(REVIEWS)

    assert len(truth) == len(reviews) == 12
    assert {row["record_id"] for row in truth} == {
        row["record_id"] for row in reviews
    }
    assert all(row["review_status"] == "reviewed" for row in truth)
    assert all(row["review_decision"] == "reviewed" for row in reviews)
    assert all(row["source_access_status"] == "accessible" for row in reviews)
    assert all(
        row[field] == "yes"
        for row in reviews
        for field in ("published_date_match", "region_match", "impact_statement_match")
    )

    heat = [row for row in truth if row["hazard"] == "heatwave"]
    assert len(heat) == 3
    assert all(row["impact_status"] == "unknown" for row in heat)
    assert "no" not in {row["impact_status"] for row in truth}


def test_case_approvals_preserve_layer_boundaries_and_frozen_split() -> None:
    cases = {row["case_id"]: row for row in read_csv(CASES)}
    recommendations = read_csv(RECOMMENDATIONS)

    assert len(cases) == len(recommendations) == 13
    assert {row["case_id"] for row in recommendations} == set(cases)

    real_cases = [row for row in recommendations if row["case_role"] != "demo"]
    assert len(real_cases) == 12
    assert all(row["weather_layer_recommendation"] == "recommend_approve" for row in real_cases)
    assert all(row["approval_status"] == "approved" for row in real_cases)
    assert all(row["approved_by"] == "member_A" for row in real_cases)
    assert all(row["approval_date"] == "2026-07-16" for row in real_cases)
    assert all(cases[row["case_id"]]["selection_status"] == "approved" for row in real_cases)
    assert all(
        row["recommended_split"] == cases[row["case_id"]]["dataset_split"]
        for row in real_cases
    )

    positive_impact_cases = {
        row["case_id"]
        for row in recommendations
        if row["impact_layer_recommendation"] == "recommend_positive_event"
    }
    assert positive_impact_cases == {
        row["case_id"]
        for row in cases.values()
        if row["case_role"] == "event"
        and row["hazard"] == "heavy_rain"
        and row["impact_evidence_status"] == "impact_confirmed"
    }
    assert all(
        row["impact_layer_recommendation"].startswith("exclude_")
        for row in recommendations
        if row["case_role"] in {"control", "demo"}
    )
