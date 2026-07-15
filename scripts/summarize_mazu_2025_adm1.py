"""Summarize MAZU 2025 shared indicators by Saudi ADM1 and season."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from matplotlib.path import Path as GeometryPath
from netCDF4 import Dataset

from scripts.audit_mazu_2025 import EXPECTED


_WORKER_MASKS: dict[str, np.ndarray] = {}
_WORKER_WEIGHTS: np.ndarray | None = None


def _polygon_mask(points: np.ndarray, rings: list[list[list[float]]]) -> np.ndarray:
    """Return point-in-polygon membership, respecting interior holes."""
    mask = GeometryPath(np.asarray(rings[0])).contains_points(points, radius=1e-10)
    for hole in rings[1:]:
        mask &= ~GeometryPath(np.asarray(hole)).contains_points(points, radius=1e-10)
    return mask


def build_region_masks(
    geojson_path: Path, latitudes: np.ndarray, longitudes: np.ndarray
) -> dict[str, np.ndarray]:
    """Rasterize ADM1 feature geometry onto MAZU cell centers."""
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    longitude_grid, latitude_grid = np.meshgrid(longitudes, latitudes)
    points = np.column_stack([longitude_grid.ravel(), latitude_grid.ravel()])
    masks: dict[str, np.ndarray] = {}
    for feature in data["features"]:
        region_id = feature["properties"]["region_id"]
        geometry = feature["geometry"]
        polygons = (
            [geometry["coordinates"]]
            if geometry["type"] == "Polygon"
            else geometry["coordinates"]
        )
        mask = np.zeros(points.shape[0], dtype=bool)
        for rings in polygons:
            mask |= _polygon_mask(points, rings)
        if not mask.any():
            raise ValueError(f"ADM1 region has no MAZU cell centers: {region_id}")
        masks[region_id] = mask
    return masks


def _init_worker(masks: dict[str, np.ndarray], weights: np.ndarray) -> None:
    global _WORKER_MASKS, _WORKER_WEIGHTS
    _WORKER_MASKS = masks
    _WORKER_WEIGHTS = weights


def _summarize_day(path: str) -> tuple[str, dict[tuple[str, str], tuple[float, float, float]]]:
    """Compute region mean, maximum and spatial P95 for one daily file."""
    if _WORKER_WEIGHTS is None:
        raise RuntimeError("worker was not initialized")
    date = Path(path).stem.removeprefix("saudi_indicators_")
    facts: dict[tuple[str, str], tuple[float, float, float]] = {}
    with Dataset(path) as dataset:
        for indicator in EXPECTED:
            if indicator not in dataset.variables:
                continue
            raw = dataset.variables[indicator][:]
            array = np.asarray(raw.filled(np.nan) if np.ma.isMaskedArray(raw) else raw).ravel()
            for region_id, mask in _WORKER_MASKS.items():
                values = array[mask]
                finite = np.isfinite(values)
                if not finite.any():
                    continue
                finite_values = values[finite]
                finite_weights = _WORKER_WEIGHTS[mask][finite]
                region_mean = float(np.average(finite_values, weights=finite_weights))
                facts[(region_id, indicator)] = (
                    region_mean,
                    float(finite_values.max()),
                    float(np.quantile(finite_values, 0.95)),
                )
    return date, facts


def _season(date: str) -> str:
    month = int(date[4:6])
    if month in {12, 1, 2}:
        return "DJF"
    if month in {3, 4, 5}:
        return "MAM"
    if month in {6, 7, 8}:
        return "JJA"
    return "SON"


def _quantile(values: list[float], probability: float) -> str:
    return "" if not values else f"{float(np.quantile(values, probability)):.8g}"


def summarize(
    input_dir: Path,
    geojson_path: Path,
    registry_path: Path,
    output_path: Path,
    coverage_path: Path,
    workers: int,
) -> None:
    """Run the complete region/season descriptive-statistics workflow."""
    files = sorted(input_dir.glob("saudi_indicators_*.nc"))
    if not files:
        raise FileNotFoundError(f"no daily files found in {input_dir}")
    with Dataset(files[0]) as sample:
        latitudes = np.asarray(sample.variables["latitude"][:])
        longitudes = np.asarray(sample.variables["longitude"][:])
    masks = build_region_masks(geojson_path, latitudes, longitudes)
    latitude_grid = np.broadcast_to(latitudes[:, None], (latitudes.size, longitudes.size))
    weights = np.cos(np.deg2rad(latitude_grid)).ravel()

    grouped: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker, initargs=(masks, weights)
    ) as executor:
        daily_results = executor.map(_summarize_day, map(str, files), chunksize=4)
        for index, (date, facts) in enumerate(daily_results, start=1):
            season = _season(date)
            for (region_id, indicator), (mean, maximum, spatial_p95) in facts.items():
                for period in ("annual", season):
                    grouped[(period, region_id, indicator, "mean")].append(mean)
                    grouped[(period, region_id, indicator, "max")].append(maximum)
                    grouped[(period, region_id, indicator, "spatial_p95")].append(spatial_p95)
            if index % 50 == 0 or index == len(files):
                print(f"summarized {index}/{len(files)} files", flush=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    registry = {}
    with registry_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            registry[row["region_id"]] = row["region_name_en"]
    fieldnames = [
        "period",
        "region_id",
        "region_name_en",
        "indicator",
        "unit",
        "region_cell_count",
        "valid_days",
        "daily_region_mean_p50",
        "daily_region_mean_p90",
        "daily_region_mean_p95",
        "daily_region_mean_max",
        "daily_region_max_p50",
        "daily_region_max_p90",
        "daily_region_max_p95",
        "daily_region_max_max",
        "daily_spatial_p95_p50",
        "daily_spatial_p95_p90",
        "daily_spatial_p95_p95",
        "daily_spatial_p95_max",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for period in ("annual", "DJF", "MAM", "JJA", "SON"):
            for region_id in sorted(masks):
                for indicator, expected in EXPECTED.items():
                    means = grouped[(period, region_id, indicator, "mean")]
                    maxima = grouped[(period, region_id, indicator, "max")]
                    spatial_p95 = grouped[(period, region_id, indicator, "spatial_p95")]
                    writer.writerow(
                        {
                            "period": period,
                            "region_id": region_id,
                            "region_name_en": registry[region_id],
                            "indicator": indicator,
                            "unit": expected["unit"],
                            "region_cell_count": int(masks[region_id].sum()),
                            "valid_days": len(means),
                            "daily_region_mean_p50": _quantile(means, 0.50),
                            "daily_region_mean_p90": _quantile(means, 0.90),
                            "daily_region_mean_p95": _quantile(means, 0.95),
                            "daily_region_mean_max": "" if not means else f"{max(means):.8g}",
                            "daily_region_max_p50": _quantile(maxima, 0.50),
                            "daily_region_max_p90": _quantile(maxima, 0.90),
                            "daily_region_max_p95": _quantile(maxima, 0.95),
                            "daily_region_max_max": "" if not maxima else f"{max(maxima):.8g}",
                            "daily_spatial_p95_p50": _quantile(spatial_p95, 0.50),
                            "daily_spatial_p95_p90": _quantile(spatial_p95, 0.90),
                            "daily_spatial_p95_p95": _quantile(spatial_p95, 0.95),
                            "daily_spatial_p95_max": (
                                "" if not spatial_p95 else f"{max(spatial_p95):.8g}"
                            ),
                        }
                    )

    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    with coverage_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["region_id", "region_name_en", "region_cell_count"]
        )
        writer.writeheader()
        for region_id in sorted(masks):
            writer.writerow(
                {
                    "region_id": region_id,
                    "region_name_en": registry[region_id],
                    "region_cell_count": int(masks[region_id].sum()),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument(
        "--geojson",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv"),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("configs/region_registry.csv"),
    )
    parser.add_argument(
        "--coverage-output",
        type=Path,
        default=Path("handoff/mazu_statistics/saudi_adm1_grid_coverage.csv"),
    )
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()
    summarize(
        args.input_dir,
        args.geojson,
        args.registry,
        args.output,
        args.coverage_output,
        max(1, args.workers),
    )
    print(args.output)
    print(args.coverage_output)


if __name__ == "__main__":
    main()
