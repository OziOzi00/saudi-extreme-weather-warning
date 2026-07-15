"""Test observation normalization and weather-layer metric calculations."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from saudi_warning.verification.metrics import (
    PAIR_COLUMNS,
    compute_heatwave_sequences,
    compute_metrics,
    validate_pairs,
)
from saudi_warning.verification.observations import (
    accumulate_imerg_window,
    ghcn_year_url,
    read_ghcn_by_year,
    sample_forecast_at_stations,
)


ROOT = Path(__file__).resolve().parents[1]


def _pair(
    lead: int,
    variable: str,
    forecast: float,
    observed: float,
    threshold: float,
    aggregation: str = "spatial_p95",
) -> dict[str, object]:
    unit = "mm" if variable == "daily_precip_total" else "degC"
    return {
        "case_id": "synthetic_case",
        "initial_time": "2020-08-20T00:00:00Z",
        "lead_time_hours": lead,
        "valid_start_time": f"2020-08-{19 + lead // 24:02d}T00:00:00Z",
        "valid_end_time": f"2020-08-{20 + lead // 24:02d}T00:00:00Z",
        "region_id": "SA-01",
        "variable": variable,
        "aggregation": aggregation,
        "forecast_value": forecast,
        "observed_value": observed,
        "unit": unit,
        "event_threshold": threshold,
        "observation_source": "IMERG" if unit == "mm" else "GHCN_DAILY",
        "observation_id": f"synthetic_{variable}_{lead}",
        "coverage_fraction": 1.0,
        "station_count": None if unit == "mm" else 3,
        "qc_status": "accepted",
    }


def test_precipitation_continuous_and_categorical_metrics() -> None:
    frame = pd.DataFrame(
        [
            _pair(24, "daily_precip_total", 10.0, 8.0, 10.0),
            _pair(48, "daily_precip_total", 0.0, 5.0, 10.0),
            _pair(72, "daily_precip_total", 20.0, 25.0, 10.0),
        ]
    )
    assert set(frame.columns) == PAIR_COLUMNS
    assert validate_pairs(frame) == []
    all_leads = compute_metrics(frame).query("scope == 'all_leads'").iloc[0]
    assert np.isclose(all_leads["mae"], 4.0)
    assert all_leads["hits"] == 1
    assert all_leads["false_alarms"] == 1
    assert all_leads["correct_negatives"] == 1
    assert np.isclose(all_leads["csi"], 0.5)


def test_pair_template_schema_and_code_use_the_same_fields() -> None:
    template = pd.read_csv(ROOT / "configs" / "weather_verification_pairs_template.csv")
    schema = json.loads(
        (ROOT / "schemas" / "weather_verification_pair.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(template.columns) == PAIR_COLUMNS
    assert set(schema["properties"]) == PAIR_COLUMNS
    assert set(schema["required"]) == PAIR_COLUMNS


def test_heatwave_onset_and_duration_errors() -> None:
    frame = pd.DataFrame(
        [
            _pair(24, "tmax_c", 45.0, 35.0, 40.0, "station_mean"),
            _pair(48, "tmax_c", 45.0, 45.0, 40.0, "station_mean"),
            _pair(72, "tmax_c", 35.0, 45.0, 40.0, "station_mean"),
        ]
    )
    result = compute_heatwave_sequences(frame, minimum_duration=2).iloc[0]
    assert result["forecast_onset_lead_hours"] == 24
    assert result["observed_onset_lead_hours"] == 48
    assert result["onset_error_days"] == -1
    assert result["forecast_max_duration_days"] == 2
    assert result["observed_max_duration_days"] == 2


def test_ghcn_by_year_normalization_and_quality_flag(tmp_path: Path) -> None:
    source = tmp_path / "2020.csv"
    source.write_text(
        "SAM00041024,20200820,TMAX,450,,,S,\n"
        "SAM00041024,20200820,TMIN,300,,X,S,\n"
        "SAM00041024,20200820,PRCP,25,,,S,\n",
        encoding="utf-8",
    )
    frame = read_ghcn_by_year(source)
    assert frame["value"].tolist() == [45.0, 30.0, 2.5]
    assert frame["qc_status"].tolist() == ["accepted", "rejected", "accepted"]
    assert ghcn_year_url(2020).endswith("/2020.csv.gz")


def test_imerg_half_hour_rate_accumulation(tmp_path: Path) -> None:
    path = tmp_path / "imerg.nc"
    field = xr.DataArray(
        np.full((4, 2, 2), 2.0),
        dims=("time", "lat", "lon"),
        coords={
            "time": pd.date_range(
                "2020-08-20T00:00:00Z", periods=4, freq="30min"
            ).tz_localize(None),
            "lat": [24.0, 24.1],
            "lon": [46.0, 46.1],
        },
        attrs={"units": "mm/hr"},
        name="precipitation",
    )
    field.to_dataset().to_netcdf(path, engine="scipy")
    accumulated = accumulate_imerg_window(
        path, "2020-08-20T00:00:00", "2020-08-20T02:00:00"
    )
    assert np.allclose(accumulated.values, 4.0)
    assert accumulated.attrs["units"] == "mm"


def test_forecast_is_sampled_at_same_station_locations(tmp_path: Path) -> None:
    path = tmp_path / "forecast.nc"
    field = xr.DataArray(
        [[40.0, 42.0], [44.0, 46.0]],
        dims=("latitude", "longitude"),
        coords={"latitude": [24.0, 25.0], "longitude": [46.0, 47.0]},
        attrs={"units": "degC"},
        name="tmax_c",
    )
    field.to_dataset().to_netcdf(path, engine="scipy")
    stations = pd.DataFrame(
        {
            "station_id": ["A", "B"],
            "latitude": [24.1, 24.9],
            "longitude": [46.1, 46.9],
            "region_id": ["SA-01", "SA-01"],
        }
    )
    result = sample_forecast_at_stations(path, stations, "tmax_c").iloc[0]
    assert result["forecast_value"] == 43.0
    assert result["station_count"] == 2
    assert result["aggregation"] == "station_mean"
