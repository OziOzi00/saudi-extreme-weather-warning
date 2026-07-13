"""Read the minimal GraphCast 2020 subset required by MAZU-like v1."""

from collections.abc import Sequence

import fsspec
import numpy as np
import xarray as xr


GRAPHCAST_2020_ZARR = (
    "https://storage.googleapis.com/weatherbench2/datasets/graphcast/2020/"
    "date_range_2019-11-16_2021-02-01_12_hours_derived.zarr"
)

# This deliberately exceeds Saudi Arabia slightly; member B/C applies the national mask later.
SAUDI_CONTEXT_BBOX = {"lat_min": 15.0, "lat_max": 33.0, "lon_min": 33.0, "lon_max": 57.0}
PRESSURE_LEVELS_HPA = [1000, 925, 850, 700, 500, 300, 200]


def requested_lead_steps(max_lead_hours: int = 72) -> list[str]:
    """Return six-hour GraphCast lead steps required by a v1 forecast window."""
    if max_lead_hours not in {24, 48, 72}:
        raise ValueError("max_lead_hours must be one of 24, 48, or 72")
    return [f"{hour}h" for hour in range(6, max_lead_hours + 1, 6)]


def required_variables() -> Sequence[str]:
    """Return the minimal GraphCast variable contract for MAZU-like v1."""
    return (
        "total_precipitation_6hr",
        "2m_temperature",
        "10m_u_component_of_wind",
        "10m_v_component_of_wind",
        "specific_humidity",
        "u_component_of_wind",
        "v_component_of_wind",
        "vertical_velocity",
        "geopotential",
    )


def open_graphcast_2020() -> xr.Dataset:
    """Open the public consolidated Zarr metadata without downloading global fields.

    The HTTP mapper is intentionally used instead of a local data download. Array chunks
    are fetched only when a selected subset is loaded by :func:`load_case_subset`.
    """
    mapper = fsspec.get_mapper(GRAPHCAST_2020_ZARR)
    return xr.open_zarr(mapper, consolidated=True)


def load_case_subset(initial_time: str, max_lead_hours: int = 24) -> xr.Dataset:
    """Load one Saudi-context GraphCast forecast case into memory.

    Parameters
    ----------
    initial_time:
        UTC ISO timestamp matching a GraphCast 00/12 UTC cycle, e.g.
        ``2020-08-20T00:00:00``.
    max_lead_hours:
        Maximum lead to read. v1 accepts 24, 48, or 72 hours.
    """
    # The public WeatherBench coordinate is stored as integer hours, even though
    # its semantic meaning is a forecast timedelta.
    lead_steps = [int(step.removesuffix("h")) for step in requested_lead_steps(max_lead_hours)]
    # WeatherBench stores UTC timestamps as timezone-naive datetime64 values.
    source_time = np.datetime64(initial_time.replace("Z", "+00:00").replace("+00:00", ""))
    source = open_graphcast_2020()
    return (
        source[list(required_variables())]
        .sel(
            time=source_time,
            prediction_timedelta=lead_steps,
            lat=slice(SAUDI_CONTEXT_BBOX["lat_min"], SAUDI_CONTEXT_BBOX["lat_max"]),
            lon=slice(SAUDI_CONTEXT_BBOX["lon_min"], SAUDI_CONTEXT_BBOX["lon_max"]),
            level=PRESSURE_LEVELS_HPA,
        )
        .load()
    )
