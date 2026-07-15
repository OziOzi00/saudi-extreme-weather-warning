"""Convert a GraphCast forecast window into MAZU-like v1 indicators."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import xarray as xr


STANDARD_GRAVITY = 9.80665
V1_VERTICAL_LEVELS_HPA = [1000, 925, 850, 700, 500, 300, 200]


def ensure_supported_lead(lead_time_hours: int) -> None:
    """Validate the only lead windows supported by v1."""
    if lead_time_hours not in {24, 48, 72}:
        raise ValueError("v1 supports 24, 48, and 72 hour windows only")


def _window_steps(lead_time_hours: int) -> list[str]:
    """Return the four six-hour steps ending at one requested lead."""
    ensure_supported_lead(lead_time_hours)
    return [f"{hour}h" for hour in range(lead_time_hours - 18, lead_time_hours + 1, 6)]


def _pressure_integral(field: xr.DataArray) -> xr.DataArray:
    """Integrate a pressure-level field in hPa and convert the integral to Pa."""
    return field.sortby("level").integrate("level") * 100.0 / STANDARD_GRAVITY


def _utc_timestamp(value: str) -> datetime:
    """Parse the UTC initial time accepted by the command-line runner."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def convert_window(case: xr.Dataset, initial_time: str, lead_time_hours: int) -> xr.Dataset:
    """Compute the common MAZU-like indicators for one 24-hour forecast window.

    ``lead024`` represents +6 through +24 h, ``lead048`` represents +30 through
    +48 h, and similarly for +72 h. This makes every output a non-overlapping
    24-hour window.
    """
    steps = _window_steps(lead_time_hours)
    # Cached GraphCast steps use WeatherBench's native integer-hour coordinate.
    window = case.sel(prediction_timedelta=[int(step.removesuffix("h")) for step in steps])
    t2m_k = window["2m_temperature"]
    u10 = window["10m_u_component_of_wind"]
    v10 = window["10m_v_component_of_wind"]

    q = window["specific_humidity"].sel(level=V1_VERTICAL_LEVELS_HPA)
    u = window["u_component_of_wind"].sel(level=V1_VERTICAL_LEVELS_HPA)
    v = window["v_component_of_wind"].sel(level=V1_VERTICAL_LEVELS_HPA)
    ivt_u = _pressure_integral(q * u)
    ivt_v = _pressure_integral(q * v)

    derived = {
        # Small negative ML precipitation artefacts have no physical meaning.
        "daily_precip_total": (
            window["total_precipitation_6hr"].sum("prediction_timedelta") * 1000.0
        ).clip(min=0.0),
        "t2m_c": t2m_k.mean("prediction_timedelta") - 273.15,
        "tmax_c": t2m_k.max("prediction_timedelta") - 273.15,
        "tmin_c": t2m_k.min("prediction_timedelta") - 273.15,
        "wind10_speed": np.hypot(u10, v10).mean("prediction_timedelta"),
        "pwat": _pressure_integral(q).mean("prediction_timedelta"),
        "ivt": np.hypot(ivt_u, ivt_v).mean("prediction_timedelta"),
        "wind850_speed": np.hypot(u.sel(level=850), v.sel(level=850)).mean(
            "prediction_timedelta"
        ),
        "wind_shear_850_200": np.hypot(
            u.sel(level=200) - u.sel(level=850), v.sel(level=200) - v.sel(level=850)
        ).mean("prediction_timedelta"),
        "omega500": window["vertical_velocity"].sel(level=500).mean(
            "prediction_timedelta"
        ),
        "geopotential_height500": (
            window["geopotential"].sel(level=500).mean("prediction_timedelta")
            / STANDARD_GRAVITY
        ),
    }
    # Selections at 850/500 hPa leave scalar ``level`` coordinates behind.
    # They conflict when fields from different levels are assembled, while the
    # level is already encoded in each indicator name.
    output = xr.Dataset({name: value.reset_coords(drop=True) for name, value in derived.items()})
    output = output.drop_vars(
        [name for name in output.coords if name not in {"lat", "lon"}], errors="ignore"
    )
    output = output.rename({"lat": "latitude", "lon": "longitude"})
    output["daily_precip_total"].attrs["units"] = "mm"
    output["t2m_c"].attrs["units"] = "degC"
    output["tmax_c"].attrs["units"] = "degC"
    output["tmin_c"].attrs["units"] = "degC"
    output["wind10_speed"].attrs["units"] = "m s-1"
    output["pwat"].attrs["units"] = "kg m-2"
    output["ivt"].attrs["units"] = "kg m-1 s-1"
    output["wind850_speed"].attrs["units"] = "m s-1"
    output["wind_shear_850_200"].attrs["units"] = "m s-1"
    output["omega500"].attrs["units"] = "Pa s-1"
    output["geopotential_height500"].attrs["units"] = "gpm"

    initial = _utc_timestamp(initial_time)
    valid_end = initial + timedelta(hours=lead_time_hours)
    valid_start = valid_end - timedelta(hours=24)
    output.attrs = {
        "forecast_model": "GraphCast",
        "initial_time": initial.isoformat().replace("+00:00", "Z"),
        "lead_time_hours": lead_time_hours,
        "valid_start_time": valid_start.isoformat().replace("+00:00", "Z"),
        "valid_end_time": valid_end.isoformat().replace("+00:00", "Z"),
        "source_resolution": "0.25 degree",
        "indicator_version": "mazu_like_v1",
        "window_steps": ",".join(steps),
    }
    return output
