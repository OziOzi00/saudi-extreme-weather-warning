from __future__ import annotations

from pathlib import Path

import pandas as pd

from saudi_warning.verification.ssod import aggregate_ssod_regions


ROOT = Path(__file__).resolve().parents[1]


def test_aggregate_ssod_regions_uses_station_extrema() -> None:
    observations = pd.DataFrame(
        [
            {
                "station_id": "A",
                "region_id": "SA-04",
                "date": pd.Timestamp("2020-07-07"),
                "variable": "tmax_c",
                "unit": "degC",
                "value": 48.0,
            },
            {
                "station_id": "B",
                "region_id": "SA-04",
                "date": pd.Timestamp("2020-07-07"),
                "variable": "tmax_c",
                "unit": "degC",
                "value": 50.0,
            },
        ]
    )
    result = aggregate_ssod_regions(observations).set_index("aggregation")
    assert result.loc["station_mean", "observed_value"] == 49.0
    assert result.loc["station_max", "observed_value"] == 50.0
    assert result.loc["station_min", "observed_value"] == 48.0
    assert set(result["station_count"]) == {2}
    assert set(result["utc_window"]) == {"00:00-23:59 UTC"}


def test_heatwave_expansion_selection_is_reproducible_and_development_only() -> None:
    selection = pd.read_csv(ROOT / "manifests" / "heatwave_development_selection.csv")
    daily = pd.read_csv(ROOT / "manifests" / "ssod_v2_saudi_2020_daily_summary.csv")
    assert len(selection) == 4
    assert set(selection["dataset_split"]) == {"development"}
    assert set(selection["independent_overlap"]) == {"no"}
    windows = [
        (pd.Timestamp(row.target_start_date), pd.Timestamp(row.target_end_date))
        for row in selection.itertuples(index=False)
    ]
    assert all(
        left_end < right_start or right_end < left_start
        for index, (left_start, left_end) in enumerate(windows)
        for right_start, right_end in windows[index + 1 :]
    )
    lookup = daily[
        (daily["region_id"] == "SA-04")
        & (daily["variable"] == "tmax_c")
        & (daily["aggregation"] == "station_max")
    ].set_index("date")
    for row in selection.itertuples(index=False):
        dates = pd.date_range(row.target_start_date, row.target_end_date).strftime(
            "%Y-%m-%d"
        )
        values = lookup.loc[list(dates), "observed_value"]
        counts = lookup.loc[list(dates), "station_count"]
        assert (counts >= row.minimum_station_count).all()
        if row.case_role == "event":
            assert (values >= 47.0).all()
        else:
            assert (values <= 45.0).all()


def test_ssod_supersedes_the_old_july_control_label() -> None:
    catalog = pd.read_csv(ROOT / "configs" / "case_catalog_candidates.csv")
    row = catalog[catalog["case_id"] == "20200715_00"].iloc[0]
    assert row["case_role"] == "event"
    assert row["weather_screening_status"] == "ssod_utc_confirmed"
    assert row["source_ids"] == "SRC-NOAA-SSOD-V2-2020"
