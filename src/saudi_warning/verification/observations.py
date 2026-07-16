"""Normalize GHCN-Daily records and aggregate local IMERG files by ADM1."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr


GHCN_BY_YEAR_COLUMNS = [
    "station_id",
    "date",
    "element",
    "data_value",
    "m_flag",
    "q_flag",
    "s_flag",
    "observation_time",
]

IMERG_GIS_MISSING_VALUE = 29999
IMERG_GIS_SCALE_FACTOR = 0.1


@dataclass(frozen=True)
class IMERGRegionGrid:
    latitude_name: str
    longitude_name: str
    latitudes: np.ndarray
    longitudes: np.ndarray
    masks: dict[str, np.ndarray]
    weights: np.ndarray


def read_imerg_gis_daily_zip(
    path: Path,
    bounds: tuple[float, float, float, float] | None = None,
) -> xr.DataArray:
    """Read the Final Run daily total accumulation GeoTIFF from a PPS ZIP.

    Bounds use ``(west, south, east, north)`` and select pixel centers. The V07 GIS
    two-byte precipitation fields use 29999 for missing data and 0.1 mm per count.
    """

    from PIL import Image

    with zipfile.ZipFile(path) as archive:
        tif_names = [
            name for name in archive.namelist() if name.endswith(".total.accum.tif")
        ]
        if len(tif_names) != 1:
            raise ValueError(
                f"expected one total accumulation GeoTIFF in {path}, found {tif_names}"
            )
        tif_name = tif_names[0]
        world_name = tif_name[:-4] + ".tfw"
        if world_name not in archive.namelist():
            raise ValueError(f"IMERG archive lacks world file: {world_name}")
        with Image.open(BytesIO(archive.read(tif_name))) as image:
            raw = np.asarray(image).copy()
        world_values = [
            float(value) for value in archive.read(world_name).decode("ascii").split()
        ]

    if len(world_values) != 6:
        raise ValueError(f"invalid IMERG world file in {path}")
    pixel_x, rotation_y, rotation_x, pixel_y, center_x, center_y = world_values
    if rotation_x != 0 or rotation_y != 0 or pixel_x <= 0 or pixel_y >= 0:
        raise ValueError(f"unsupported IMERG grid transform in {path}")
    latitudes = center_y + np.arange(raw.shape[0]) * pixel_y
    longitudes = center_x + np.arange(raw.shape[1]) * pixel_x
    if bounds is not None:
        west, south, east, north = bounds
        latitude_indices = np.flatnonzero((latitudes >= south) & (latitudes <= north))
        longitude_indices = np.flatnonzero(
            (longitudes >= west) & (longitudes <= east)
        )
        if not len(latitude_indices) or not len(longitude_indices):
            raise ValueError(f"IMERG bounds do not intersect the grid: {bounds}")
        raw = raw[np.ix_(latitude_indices, longitude_indices)]
        latitudes = latitudes[latitude_indices]
        longitudes = longitudes[longitude_indices]
    values = raw.astype(np.float32)
    values[raw == IMERG_GIS_MISSING_VALUE] = np.nan
    values *= IMERG_GIS_SCALE_FACTOR
    field = xr.DataArray(
        values,
        coords={"latitude": latitudes, "longitude": longitudes},
        dims=("latitude", "longitude"),
        name="daily_precip_total",
    )
    field.attrs = {
        "units": "mm",
        "source_file": str(path),
        "source_member": tif_name,
        "product": "IMERG Final Run daily GIS accumulation",
        "version": "V07B",
    }
    return field


def ghcn_year_url(year: int) -> str:
    """Return NOAA's official direct-download URL for one GHCN-Daily year."""
    if year < 1750 or year > datetime.now(timezone.utc).year + 1:
        raise ValueError("year is outside the supported GHCN-Daily range")
    return f"https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_year/{year}.csv.gz"


def read_ghcn_by_year(path: Path) -> pd.DataFrame:
    """Read NOAA's headerless by-year CSV and normalize TMAX/TMIN/PRCP units."""
    frame = pd.read_csv(
        path,
        names=GHCN_BY_YEAR_COLUMNS,
        dtype={"station_id": str, "date": str, "element": str, "q_flag": str},
        keep_default_na=False,
    )
    frame = frame[frame["element"].isin(["TMAX", "TMIN", "PRCP"])].copy()
    mapping = {
        "TMAX": ("tmax_c", "degC"),
        "TMIN": ("tmin_c", "degC"),
        "PRCP": ("daily_precip_total", "mm"),
    }
    frame["variable"] = frame["element"].map(lambda value: mapping[value][0])
    frame["unit"] = frame["element"].map(lambda value: mapping[value][1])
    # GHCN-Daily archive values for these three elements use tenths of degC or mm.
    frame["value"] = pd.to_numeric(frame["data_value"], errors="coerce") / 10.0
    frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
    frame["qc_status"] = np.where(frame["q_flag"].str.strip() == "", "accepted", "rejected")
    return frame[
        ["station_id", "date", "variable", "value", "unit", "qc_status", "q_flag"]
    ].reset_index(drop=True)


def read_ghcn_stations(path: Path) -> pd.DataFrame:
    """Read the official fixed-width GHCN-Daily station inventory."""
    widths = [11, 9, 10, 7, 3, 31, 4, 4, 6]
    names = [
        "station_id",
        "latitude",
        "longitude",
        "elevation_m",
        "state",
        "station_name",
        "gsn_flag",
        "hcn_crn_flag",
        "wmo_id",
    ]
    frame = pd.read_fwf(path, widths=widths, names=names)
    for column in ("latitude", "longitude", "elevation_m"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _geometry_masks(
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    geojson_path: Path,
) -> dict[str, np.ndarray]:
    from matplotlib.path import Path as GeometryPath

    points = np.column_stack([longitudes, latitudes])
    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
    masks: dict[str, np.ndarray] = {}
    for feature in geojson["features"]:
        geometry = feature["geometry"]
        polygons = (
            [geometry["coordinates"]]
            if geometry["type"] == "Polygon"
            else geometry["coordinates"]
        )
        mask = np.zeros(len(points), dtype=bool)
        for rings in polygons:
            polygon_mask = GeometryPath(np.asarray(rings[0])).contains_points(
                points, radius=1e-10
            )
            for hole in rings[1:]:
                polygon_mask &= ~GeometryPath(np.asarray(hole)).contains_points(
                    points, radius=1e-10
                )
            mask |= polygon_mask
        masks[feature["properties"]["region_id"]] = mask
    return masks


def assign_stations_to_regions(stations: pd.DataFrame, geojson_path: Path) -> pd.DataFrame:
    """Assign station points to the versioned ADM1 polygons."""
    required = {"station_id", "latitude", "longitude"}
    if not required.issubset(stations.columns):
        missing = sorted(required - set(stations.columns))
        raise ValueError(f"station table missing columns: {missing}")
    finite = np.isfinite(stations["latitude"]) & np.isfinite(stations["longitude"])
    result = stations.loc[finite].copy()
    masks = _geometry_masks(
        result["latitude"].to_numpy(), result["longitude"].to_numpy(), geojson_path
    )
    result["region_id"] = None
    for region_id, mask in masks.items():
        result.loc[mask, "region_id"] = region_id
    return result[result["region_id"].notna()].reset_index(drop=True)


def aggregate_ghcn_regions(
    observations: pd.DataFrame,
    stations_with_regions: pd.DataFrame,
    aggregation: str = "station_mean",
) -> pd.DataFrame:
    """Aggregate accepted station-day records to ADM1 without spatial interpolation."""
    if aggregation not in {"station_mean", "station_max", "station_min"}:
        raise ValueError("unsupported GHCN aggregation")
    merged = observations.merge(
        stations_with_regions[["station_id", "region_id"]], on="station_id", how="inner"
    )
    accepted = merged[merged["qc_status"] == "accepted"].copy()
    groups = ["date", "region_id", "variable", "unit"]
    method = {"station_mean": "mean", "station_max": "max", "station_min": "min"}[
        aggregation
    ]
    values = accepted.groupby(groups)["value"].agg(method).rename("observed_value")
    counts = accepted.groupby(groups)["station_id"].nunique().rename("station_count")
    result = pd.concat([values, counts], axis=1).reset_index()
    result["aggregation"] = aggregation
    result["observation_source"] = "GHCN_DAILY"
    return result


def sample_forecast_at_stations(
    forecast_path: Path,
    stations_with_regions: pd.DataFrame,
    variable: str,
    aggregation: str = "station_mean",
) -> pd.DataFrame:
    """Sample a MAZU-like forecast at GHCN locations, then aggregate like observations."""
    if aggregation not in {"station_mean", "station_max", "station_min"}:
        raise ValueError("unsupported station forecast aggregation")
    required = {"station_id", "latitude", "longitude", "region_id"}
    if not required.issubset(stations_with_regions.columns):
        missing = sorted(required - set(stations_with_regions.columns))
        raise ValueError(f"station table missing columns: {missing}")
    with xr.open_dataset(forecast_path) as dataset:
        if variable not in dataset:
            raise ValueError(f"forecast variable not found: {variable}")
        latitude_name = "lat" if "lat" in dataset.coords else "latitude"
        longitude_name = "lon" if "lon" in dataset.coords else "longitude"
        station_dimension = "station"
        sampled = dataset[variable].sel(
            {
                latitude_name: xr.DataArray(
                    stations_with_regions["latitude"].to_numpy(), dims=station_dimension
                ),
                longitude_name: xr.DataArray(
                    stations_with_regions["longitude"].to_numpy(), dims=station_dimension
                ),
            },
            method="nearest",
        )
        values = np.asarray(sampled.values, dtype=float)
        unit = str(dataset[variable].attrs.get("units", ""))
    samples = stations_with_regions[
        ["station_id", "region_id"]
    ].copy()
    samples["value"] = values
    method = {"station_mean": "mean", "station_max": "max", "station_min": "min"}[
        aggregation
    ]
    forecast = samples.groupby("region_id")["value"].agg(method).rename("forecast_value")
    counts = samples.groupby("region_id")["station_id"].nunique().rename("station_count")
    result = pd.concat([forecast, counts], axis=1).reset_index()
    result["aggregation"] = aggregation
    result["variable"] = variable
    result["unit"] = unit
    return result


def accumulate_imerg_window(
    path: Path,
    valid_start: str,
    valid_end: str,
    variable: str = "precipitation",
) -> xr.DataArray:
    """Accumulate a local IMERG rate/amount field over a UTC half-open window."""
    dataset = xr.open_dataset(path)
    if variable not in dataset:
        dataset.close()
        raise ValueError(f"IMERG variable not found: {variable}")
    field = dataset[variable]
    if "time" not in field.dims:
        dataset.close()
        raise ValueError("IMERG field must have a time dimension")
    selected = field.sel(time=slice(valid_start, valid_end))
    selected = selected.where(selected["time"] < np.datetime64(valid_end), drop=True)
    if selected.sizes.get("time", 0) == 0:
        dataset.close()
        raise ValueError("IMERG window contains no time samples")
    units = str(field.attrs.get("units", "")).lower().replace(" ", "")
    if units in {"mm/hr", "mmh-1", "mmhour-1"}:
        times = selected["time"].values.astype("datetime64[s]").astype(np.int64)
        if len(times) < 2:
            dataset.close()
            raise ValueError("at least two IMERG rate samples are required to infer interval")
        intervals = np.diff(times) / 3600.0
        interval_hours = float(np.median(intervals))
        if not np.allclose(intervals, interval_hours):
            dataset.close()
            raise ValueError("IMERG time steps are not uniform")
        accumulated = selected.sum("time", skipna=True) * interval_hours
    elif units in {"mm", "millimeter", "millimeters"}:
        accumulated = selected.sum("time", skipna=True)
    else:
        dataset.close()
        raise ValueError(f"unsupported IMERG precipitation units: {field.attrs.get('units')!r}")
    accumulated.attrs = {
        "units": "mm",
        "valid_start_time": valid_start,
        "valid_end_time": valid_end,
        "source_file": str(path),
    }
    accumulated.load()
    dataset.close()
    return accumulated


def aggregate_imerg_regions(
    precipitation: xr.DataArray,
    geojson_path: Path,
    aggregation: str = "spatial_p95",
) -> pd.DataFrame:
    """Aggregate a 2-D IMERG precipitation field to versioned ADM1 regions."""
    if aggregation not in {"weighted_mean", "spatial_p95", "maximum"}:
        raise ValueError("unsupported IMERG aggregation")
    summaries = summarize_imerg_regions(precipitation, geojson_path)
    result = summaries[
        ["region_id", f"{aggregation}_mm", "coverage_fraction"]
    ].rename(columns={f"{aggregation}_mm": "observed_value"})
    result["unit"] = "mm"
    result["aggregation"] = aggregation
    result["observation_source"] = "IMERG"
    return result


def summarize_imerg_regions(
    precipitation: xr.DataArray,
    geojson_path: Path,
    region_grid: IMERGRegionGrid | None = None,
) -> pd.DataFrame:
    """Calculate all standard ADM1 precipitation statistics with one mask pass."""

    if region_grid is None:
        region_grid = prepare_imerg_region_grid(precipitation, geojson_path)
    latitude_name = region_grid.latitude_name
    longitude_name = region_grid.longitude_name
    if not np.array_equal(
        precipitation[latitude_name].values, region_grid.latitudes
    ) or not np.array_equal(
        precipitation[longitude_name].values, region_grid.longitudes
    ):
        raise ValueError("IMERG field coordinates do not match the prepared region grid")
    values = np.asarray(
        precipitation.transpose(latitude_name, longitude_name).values, dtype=float
    ).ravel()
    rows: list[dict[str, Any]] = []
    for region_id, mask in region_grid.masks.items():
        region_values = values[mask]
        finite = np.isfinite(region_values)
        if not finite.any():
            weighted_mean = None
            spatial_p95 = None
            maximum = None
        else:
            weighted_mean = float(
                np.average(
                    region_values[finite],
                    weights=region_grid.weights[mask][finite],
                )
            )
            spatial_p95 = float(np.quantile(region_values[finite], 0.95))
            maximum = float(np.max(region_values[finite]))
        rows.append(
            {
                "region_id": region_id,
                "weighted_mean_mm": weighted_mean,
                "spatial_p95_mm": spatial_p95,
                "maximum_mm": maximum,
                "coverage_fraction": float(finite.mean()),
            }
        )
    return pd.DataFrame(rows)


def prepare_imerg_region_grid(
    precipitation: xr.DataArray,
    geojson_path: Path,
) -> IMERGRegionGrid:
    """Prepare reusable ADM1 masks and latitude weights for a fixed IMERG grid."""

    latitude_name = "lat" if "lat" in precipitation.coords else "latitude"
    longitude_name = "lon" if "lon" in precipitation.coords else "longitude"
    latitudes = np.asarray(precipitation[latitude_name].values)
    longitudes = np.asarray(precipitation[longitude_name].values)
    longitude_grid, latitude_grid = np.meshgrid(longitudes, latitudes)
    return IMERGRegionGrid(
        latitude_name=latitude_name,
        longitude_name=longitude_name,
        latitudes=latitudes,
        longitudes=longitudes,
        masks=_geometry_masks(
            latitude_grid.ravel(), longitude_grid.ravel(), geojson_path
        ),
        weights=np.cos(np.deg2rad(latitude_grid)).ravel(),
    )
