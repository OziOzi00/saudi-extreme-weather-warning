"""Read the minimal GraphCast 2020 subset required by MAZU-like v1."""

from collections.abc import Sequence
from pathlib import Path

import gcsfs
import numpy as np
import xarray as xr


GRAPHCAST_2020_ZARR = (
    "https://storage.googleapis.com/weatherbench2/datasets/graphcast/2020/"
    "date_range_2019-11-16_2021-02-01_12_hours_derived.zarr"
)
GRAPHCAST_2020_GCS_PATH = (
    "weatherbench2/datasets/graphcast/2020/"
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

    The anonymous GCS mapper accesses WeatherBench directly. Array chunks are fetched
    only when a selected subset is loaded by :func:`load_case_subset`.
    """
    mapper = gcsfs.GCSFileSystem(token="anon").get_mapper(GRAPHCAST_2020_GCS_PATH)
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
    return load_case_with_cache(initial_time, lead_steps)


def _case_stamp(initial_time: str) -> str:
    """Create the stable filename portion for one UTC initialization time."""
    return initial_time.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")


def _cache_path(cache_dir: Path, initial_time: str, lead_step_hours: int) -> Path:
    return cache_dir / f"graphcast_{_case_stamp(initial_time)}_step{lead_step_hours:03d}.nc"


def cache_file_is_valid(path: Path) -> bool:
    """Return whether one derived step cache is readable and structurally complete."""
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with xr.open_dataset(path, engine="scipy") as dataset:
            if not set(required_variables()).issubset(dataset.data_vars):
                return False
            if not {"lat", "lon", "level"}.issubset(dataset.coords):
                return False
            if any(dataset.sizes.get(name, 0) == 0 for name in ("lat", "lon", "level")):
                return False
            if not set(PRESSURE_LEVELS_HPA).issubset(
                {int(value) for value in dataset["level"].values}
            ):
                return False
    except Exception:
        return False
    return True


def _quarantine_invalid_cache(path: Path) -> Path:
    """Preserve an invalid derived cache beside its original path before refetching."""
    candidate = path.with_suffix(path.suffix + ".invalid")
    index = 1
    while candidate.exists():
        candidate = path.with_suffix(path.suffix + f".invalid.{index}")
        index += 1
    path.replace(candidate)
    return candidate


def load_case_with_cache(
    initial_time: str,
    lead_steps: Sequence[int],
    cache_dir: Path = Path("data/raw/graphcast_2020"),
) -> xr.Dataset:
    """Load selected forecast steps, caching each cropped step locally.

    WeatherBench's 3-D arrays use global chunks. Caching after the first remote
    read makes conversion and rule-development iterations local and fast, while
    retaining only the Saudi-context crop rather than global fields.
    """
    # WeatherBench stores UTC timestamps as timezone-naive datetime64 values.
    source_time = np.datetime64(initial_time.replace("Z", "+00:00").replace("+00:00", ""))
    cache_dir.mkdir(parents=True, exist_ok=True)
    source: xr.Dataset | None = None
    cached_steps: list[xr.Dataset] = []
    for step in lead_steps:
        path = _cache_path(cache_dir, initial_time, step)
        if cache_file_is_valid(path):
            cropped = xr.open_dataset(path, engine="scipy").load()
        else:
            if path.exists():
                _quarantine_invalid_cache(path)
            source = source if source is not None else open_graphcast_2020()
            cropped = (
                source[list(required_variables())]
                .sel(
                    time=source_time,
                    prediction_timedelta=step,
                    lat=slice(SAUDI_CONTEXT_BBOX["lat_min"], SAUDI_CONTEXT_BBOX["lat_max"]),
                    lon=slice(SAUDI_CONTEXT_BBOX["lon_min"], SAUDI_CONTEXT_BBOX["lon_max"]),
                    level=PRESSURE_LEVELS_HPA,
                )
                .drop_vars(["time", "prediction_timedelta"])
                .load()
            )
            temporary = path.with_suffix(path.suffix + ".partial")
            cropped.to_netcdf(temporary, engine="scipy")
            if not cache_file_is_valid(temporary):
                raise RuntimeError(f"generated cache failed validation: {temporary}")
            temporary.replace(path)
        cached_steps.append(cropped.expand_dims(prediction_timedelta=[step]))
    return xr.concat(cached_steps, dim="prediction_timedelta")
