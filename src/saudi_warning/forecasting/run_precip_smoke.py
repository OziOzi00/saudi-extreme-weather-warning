"""Create and verify the smallest end-to-end GraphCast MAZU-like smoke case.

This intentionally reads only four global surface-precipitation chunks. The
WeatherBench GraphCast upper-air arrays are stored as whole global fields per
forecast step, so IVT conversion is deliberately kept out of this first
network/crop/write validation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from saudi_warning.forecasting.graphcast_loader import SAUDI_CONTEXT_BBOX, open_graphcast_2020


INITIAL_TIME = "2020-08-20T00:00:00Z"
LEAD_HOURS = 24


def build_precip_smoke_case() -> xr.Dataset:
    """Read +6..+24 h precipitation, crop it, and return daily total in mm."""
    source_time = np.datetime64(INITIAL_TIME.replace("Z", ""))
    source = open_graphcast_2020()["total_precipitation_6hr"]
    accumulated: xr.DataArray | None = None
    for step in (6, 12, 18, 24):
        # WeatherBench stores this field as one global chunk per time/lead. Load
        # one chunk at a time, crop immediately, and release the global source.
        chunk = (
            source.sel(
                time=source_time,
                prediction_timedelta=step,
                lat=slice(SAUDI_CONTEXT_BBOX["lat_min"], SAUDI_CONTEXT_BBOX["lat_max"]),
                lon=slice(SAUDI_CONTEXT_BBOX["lon_min"], SAUDI_CONTEXT_BBOX["lon_max"]),
            )
            .drop_vars("prediction_timedelta")
            .load()
        )
        chunk = chunk.clip(min=0.0)
        accumulated = chunk if accumulated is None else accumulated + chunk
    assert accumulated is not None
    output = (accumulated * 1000.0).to_dataset(name="daily_precip_total")
    output = output.rename({"lat": "latitude", "lon": "longitude"})
    output["daily_precip_total"].attrs = {
        "units": "mm",
        "long_name": "GraphCast forecast 24-hour accumulated precipitation",
    }
    output.attrs = {
        "forecast_model": "GraphCast",
        "initial_time": INITIAL_TIME,
        "lead_time_hours": LEAD_HOURS,
        "valid_start_time": INITIAL_TIME,
        "valid_end_time": "2020-08-21T00:00:00Z",
        "source_resolution": "0.25 degree",
        "indicator_version": "mazu_like_v1_smoke_precip",
        "window_steps": "6h,12h,18h,24h",
    }
    return output


def main() -> None:
    output_path = Path("data/processed/mazu_like/mazu_like_20200820_00_lead024_precip_smoke.nc")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # scipy avoids a Windows NetCDF4 unicode-path issue when the project lives
    # under a Chinese-named desktop directory.
    build_precip_smoke_case().to_netcdf(output_path, engine="scipy")
    # Reopen from disk so the command validates the actual persisted artifact.
    reopened = xr.open_dataset(output_path, engine="scipy")
    precip = reopened["daily_precip_total"]
    print(f"saved={output_path}")
    print(f"shape={dict(precip.sizes)} units={precip.units}")
    print(f"min_mm={float(precip.min()):.6f} max_mm={float(precip.max()):.6f}")
    print(f"metadata={dict(reopened.attrs)}")


if __name__ == "__main__":
    main()
