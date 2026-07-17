"""Read and aggregate NOAA SSODv2 synchronous UTC daily station summaries."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from saudi_warning.verification.observations import assign_stations_to_regions


SSOD_VARIABLES = {
    "max_temperature": ("tmax_c", "degC"),
    "min_temperature": ("tmin_c", "degC"),
}
SSOD_MISSING = -9999.9
AGGREGATIONS = {
    "station_mean": "mean",
    "station_max": "max",
    "station_min": "min",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(manifest_path: Path, data_dir: Path) -> list[dict[str, str]]:
    with manifest_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("SSOD manifest is empty")
    for row in rows:
        path = data_dir / row["filename"]
        if not path.exists():
            raise FileNotFoundError(path)
        if path.stat().st_size != int(row["size_bytes"]):
            raise ValueError(f"SSOD size mismatch: {path}")
        if _sha256(path) != row["sha256"]:
            raise ValueError(f"SSOD SHA-256 mismatch: {path}")
    return rows


def load_ssod_observations(
    manifest_path: Path,
    data_dir: Path,
    regions_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return normalized station-day values and a station-to-ADM1 registry."""
    manifest = verify_manifest(manifest_path, data_dir)
    frames = []
    stations = []
    for item in manifest:
        path = data_dir / item["filename"]
        frame = pd.read_csv(path, dtype={"STATION": str, "DATE": str})
        if frame.empty:
            continue
        stations.append(
            {
                "station_id": str(frame.iloc[0]["STATION"]),
                "station_name": str(frame.iloc[0]["Station_name"]),
                "latitude": float(frame.iloc[0]["LATITUDE"]),
                "longitude": float(frame.iloc[0]["LONGITUDE"]),
            }
        )
        for source_column, (variable, unit) in SSOD_VARIABLES.items():
            values = pd.to_numeric(frame[source_column], errors="coerce")
            valid = np.isfinite(values) & (values != SSOD_MISSING)
            subset = frame.loc[valid, ["STATION", "DATE"]].copy()
            subset.columns = ["station_id", "date"]
            subset["variable"] = variable
            subset["value"] = values.loc[valid].astype(float).to_numpy()
            subset["unit"] = unit
            frames.append(subset)
    if not frames:
        raise ValueError("no valid SSOD temperature observations")
    station_frame = pd.DataFrame(stations).drop_duplicates("station_id")
    station_frame = assign_stations_to_regions(station_frame, regions_path)
    observations = pd.concat(frames, ignore_index=True)
    observations = observations.merge(
        station_frame[["station_id", "region_id"]], on="station_id", how="inner"
    )
    observations["date"] = pd.to_datetime(observations["date"], errors="raise")
    return observations, station_frame


def aggregate_ssod_regions(observations: pd.DataFrame) -> pd.DataFrame:
    """Aggregate station extrema for each synchronous 00--23 UTC day and ADM1."""
    groups = ["region_id", "date", "variable", "unit"]
    rows: list[dict[str, Any]] = []
    for key, group in observations.groupby(groups, sort=True):
        station_count = int(group["station_id"].nunique())
        for aggregation, function in AGGREGATIONS.items():
            rows.append(
                {
                    "region_id": key[0],
                    "date": key[1].strftime("%Y-%m-%d"),
                    "variable": key[2],
                    "unit": key[3],
                    "aggregation": aggregation,
                    "observed_value": float(getattr(group["value"], function)()),
                    "station_count": station_count,
                    "station_ids": ";".join(sorted(group["station_id"].unique())),
                    "observation_source": "NOAA_SSOD_V2",
                    "utc_window": "00:00-23:59 UTC",
                }
            )
    return pd.DataFrame(rows)
