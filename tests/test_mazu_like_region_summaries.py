import csv
from pathlib import Path


def test_mazu_like_region_summary_has_all_leads_regions_and_indicators() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "handoff" / "region_summaries" / "mazu_like_adm1_indicator_summaries.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 3 * 13 * 11
    assert {int(row["lead_time_hours"]) for row in rows} == {24, 48, 72}
    assert len({row["region_id"] for row in rows}) == 13
    assert len({row["indicator"] for row in rows}) == 11
    for row in rows:
        minimum = float(row["minimum"])
        mean = float(row["weighted_mean"])
        p95 = float(row["spatial_p95"])
        maximum = float(row["maximum"])
        assert minimum <= mean <= maximum
        assert minimum <= p95 <= maximum
