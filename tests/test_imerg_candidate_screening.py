import csv
from pathlib import Path

from scripts.screen_imerg_candidates import build_control_screening


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_control_screening_requires_both_p95_and_maximum_to_be_lower() -> None:
    rows = [
        {
            "case_id": "event",
            "case_role": "event",
            "region_id": "SA-01",
            "window_start_date": "2020-01-01",
            "spatial_p95_mm": 10.0,
            "maximum_mm": 20.0,
        },
        {
            "case_id": "control",
            "case_role": "control",
            "region_id": "SA-01",
            "window_start_date": "2020-01-10",
            "spatial_p95_mm": 5.0,
            "maximum_mm": 21.0,
        },
    ]
    screening = build_control_screening(rows)
    assert screening[0]["screening_status"] == "imerg_not_lower_than_event"


def test_versioned_imerg_screening_matches_candidate_catalog() -> None:
    screening = _read(ROOT / "manifests" / "imerg_2020_control_screening.csv")
    assert len(screening) == 5
    assert all(
        row["screening_status"] == "imerg_screened_lower_intensity"
        for row in screening
    )
    catalog = _read(ROOT / "configs" / "case_catalog_candidates.csv")
    rainfall_controls = [
        row
        for row in catalog
        if row["case_role"] == "control" and row["hazard"] == "heavy_rain"
    ]
    assert len(rainfall_controls) == 4
    assert all(
        row["weather_screening_status"] == "imerg_screened_lower_intensity"
        for row in rainfall_controls
    )
