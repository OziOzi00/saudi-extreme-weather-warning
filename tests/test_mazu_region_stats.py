import csv
from pathlib import Path


def test_adm1_descriptive_statistics_are_complete_and_monotonic() -> None:
    root = Path(__file__).resolve().parents[1]
    with (
        root / "handoff" / "mazu_statistics" / "mazu_2025_adm1_descriptive_stats.csv"
    ).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 13 * 11 * 5
    assert {row["period"] for row in rows} == {"annual", "DJF", "MAM", "JJA", "SON"}
    assert len({row["region_id"] for row in rows}) == 13
    for row in rows:
        mean_values = [
            float(row["daily_region_mean_p50"]),
            float(row["daily_region_mean_p90"]),
            float(row["daily_region_mean_p95"]),
            float(row["daily_region_mean_max"]),
        ]
        maximum_values = [
            float(row["daily_region_max_p50"]),
            float(row["daily_region_max_p90"]),
            float(row["daily_region_max_p95"]),
            float(row["daily_region_max_max"]),
        ]
        assert mean_values == sorted(mean_values)
        assert maximum_values == sorted(maximum_values)
