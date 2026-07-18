"""Extract truth-sealed fine-spatial diagnostics from MAZU-like forecast grids."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
import yaml


SCHEMA_VERSION = "forecast_spatial_diagnostics_v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _region_mask(
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    geometry: dict[str, Any],
) -> np.ndarray:
    from matplotlib.path import Path as GeometryPath

    lon_grid, lat_grid = np.meshgrid(longitudes, latitudes)
    points = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    mask = np.zeros(points.shape[0], dtype=bool)
    for rings in polygons:
        polygon_mask = GeometryPath(np.asarray(rings[0])).contains_points(
            points, radius=1e-10
        )
        for hole in rings[1:]:
            polygon_mask &= ~GeometryPath(np.asarray(hole)).contains_points(
                points, radius=1e-10
            )
        mask |= polygon_mask
    return mask.reshape(lat_grid.shape)


def _top_area_precip_share(
    values: np.ndarray, weights: np.ndarray, area_fraction: float
) -> float:
    positive_total = float(np.sum(np.maximum(values, 0.0) * weights))
    if positive_total <= 0:
        return 0.0
    order = np.argsort(values)[::-1]
    ordered_weights = weights[order]
    cumulative_area = np.cumsum(ordered_weights) / np.sum(ordered_weights)
    selected = cumulative_area <= area_fraction
    if not np.any(selected):
        selected[0] = True
    indices = order[selected]
    return float(np.sum(np.maximum(values[indices], 0.0) * weights[indices]) / positive_total)


def _weighted_correlation(
    left: np.ndarray, right: np.ndarray, weights: np.ndarray
) -> float | None:
    left_mean = float(np.average(left, weights=weights))
    right_mean = float(np.average(right, weights=weights))
    left_delta = left - left_mean
    right_delta = right - right_mean
    covariance = float(np.average(left_delta * right_delta, weights=weights))
    left_variance = float(np.average(left_delta**2, weights=weights))
    right_variance = float(np.average(right_delta**2, weights=weights))
    if left_variance <= 0 or right_variance <= 0:
        return None
    return covariance / np.sqrt(left_variance * right_variance)


def _sample_elevation(
    path: Path, latitudes: np.ndarray, longitudes: np.ndarray
) -> np.ndarray:
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError('Spatial diagnostics require: pip install -e ".[knowledge]"') from exc
    with rasterio.open(path) as dataset:
        samples = np.asarray(
            [item[0] for item in dataset.sample(zip(longitudes, latitudes))],
            dtype=np.float64,
        )
        if dataset.nodata is not None:
            samples[samples == dataset.nodata] = np.nan
    return samples


def _load_forecast(path: Path) -> xr.Dataset:
    # The versioned MAZU-like fixtures are NetCDF3. scipy handles Unicode workspace
    # paths more reliably than netCDF4 on Windows.
    return xr.open_dataset(path, engine="scipy").load()


def extract_spatial_diagnostic(
    risk_path: Path,
    config: dict[str, Any],
    geometries: dict[str, dict[str, Any]],
    elevation_path: Path,
) -> dict[str, Any]:
    risk = json.loads(risk_path.read_text(encoding="utf-8"))
    if risk.get("hazard") != "heavy_rain":
        raise ValueError("spatial diagnostic v1 currently supports heavy_rain only")
    if risk.get("rule_status") != "frozen":
        raise ValueError("spatial diagnostic requires a frozen Risk JSON")
    region_id = str(risk["region_id"])
    if region_id not in geometries:
        raise ValueError(f"missing boundary for {region_id}")
    forecast_path = Path(str(risk["source_file"]))
    with _load_forecast(forecast_path) as dataset:
        values_2d = np.asarray(dataset["daily_precip_total"].values, dtype=np.float64)
        latitudes = np.asarray(dataset["latitude"].values, dtype=np.float64)
        longitudes = np.asarray(dataset["longitude"].values, dtype=np.float64)
    mask = _region_mask(latitudes, longitudes, geometries[region_id])
    lon_grid, lat_grid = np.meshgrid(longitudes, latitudes)
    finite = mask & np.isfinite(values_2d)
    values = values_2d[finite]
    point_latitudes = lat_grid[finite]
    point_longitudes = lon_grid[finite]
    weights = np.cos(np.deg2rad(point_latitudes))
    if values.size < 5:
        raise ValueError(f"too few forecast cells for {region_id}: {values.size}")

    medium_threshold = float(risk["indicator_summary"]["precip_medium_threshold_mm"])
    high_threshold = float(risk["indicator_summary"]["precip_high_threshold_mm"])
    p95 = float(np.quantile(values, 0.95))
    p99 = float(np.quantile(values, 0.99))
    maximum = float(np.max(values))
    area_fraction_medium = float(np.sum(weights[values >= medium_threshold]) / np.sum(weights))
    area_fraction_high = float(np.sum(weights[values >= high_threshold]) / np.sum(weights))
    elevations = _sample_elevation(elevation_path, point_latitudes, point_longitudes)
    elevation_finite = np.isfinite(elevations)
    positive_precip = np.maximum(values, 0.0)
    precip_mass = float(np.sum(positive_precip[elevation_finite] * weights[elevation_finite]))
    if precip_mass > 0:
        precip_weighted_elevation = float(
            np.sum(
                positive_precip[elevation_finite]
                * elevations[elevation_finite]
                * weights[elevation_finite]
            )
            / precip_mass
        )
        high_terrain = elevation_finite & (elevations >= 1000.0)
        precip_share_above_1000 = float(
            np.sum(positive_precip[high_terrain] * weights[high_terrain]) / precip_mass
        )
    else:
        precip_weighted_elevation = None
        precip_share_above_1000 = None
    terrain_correlation = (
        _weighted_correlation(
            values[elevation_finite],
            elevations[elevation_finite],
            weights[elevation_finite],
        )
        if np.count_nonzero(elevation_finite) >= 5
        else None
    )
    candidate = config["localized_hotspot_candidate"]
    triggered = (
        risk["risk_level"] == candidate["required_risk_level"]
        and p99 >= medium_threshold
        and maximum >= high_threshold
        and area_fraction_medium >= float(candidate["minimum_area_fraction_ge_medium"])
    )
    return {
        "id": f"{risk['case_id']}:{region_id}:spatial-v1",
        "case_id": risk["case_id"],
        "region_id": region_id,
        "hazard": risk["hazard"],
        "initial_time": risk["initial_time"],
        "valid_start_time": risk["valid_start_time"],
        "valid_end_time": risk["valid_end_time"],
        "lead_time_hours": risk["lead_time_hours"],
        "risk_level": risk["risk_level"],
        "risk_score": risk["risk_score"],
        "grid_cell_count": int(values.size),
        "precip_spatial_p95_mm": round(p95, 6),
        "risk_json_p95_mm": risk["indicator_summary"]["precip_spatial_p95_mm"],
        "precip_spatial_p99_mm": round(p99, 6),
        "precip_spatial_max_mm": round(maximum, 6),
        "area_fraction_ge_medium": round(area_fraction_medium, 6),
        "area_fraction_ge_high": round(area_fraction_high, 6),
        "top_5pct_precip_share": round(_top_area_precip_share(values, weights, 0.05), 6),
        "p99_to_p95_ratio": round(p99 / p95, 6) if p95 > 0 else None,
        "precip_weighted_elevation_m": (
            round(precip_weighted_elevation, 3)
            if precip_weighted_elevation is not None
            else None
        ),
        "precip_share_above_1000m": (
            round(precip_share_above_1000, 6)
            if precip_share_above_1000 is not None
            else None
        ),
        "precip_elevation_correlation": (
            round(terrain_correlation, 6) if terrain_correlation is not None else None
        ),
        "candidate_triggered": triggered,
        "candidate_conflict_flag": candidate["conflict_flag"] if triggered else "none",
        "candidate_attention_level": candidate["attention_level"] if triggered else "routine",
        "candidate_status": config["status"],
        "may_change_meteorological_risk": False,
        "rationale_zh": candidate["rationale_zh"] if triggered else "未触发预注册局地热点条件。",
        "source_file": forecast_path.as_posix(),
        "source_sha256": _sha256(forecast_path),
    }


def validate_spatial_diagnostics(bundle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if bundle.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if bundle.get("truth_access") != "forbidden" or bundle.get("truth_accessed") is not False:
        errors.append("spatial diagnostics must be truth-sealed")
    if bundle.get("may_change_meteorological_risk") is not False:
        errors.append("spatial diagnostics may not change meteorological risk")
    diagnostics = bundle.get("diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        errors.append("diagnostics must be a non-empty array")
    else:
        ids = {item.get("id") for item in diagnostics}
        if len(ids) != len(diagnostics):
            errors.append("diagnostic IDs must be unique")
        for item in diagnostics:
            if item.get("may_change_meteorological_risk") is not False:
                errors.append("diagnostic item may not change risk")
    return errors


def build_spatial_diagnostics(
    risk_dir: Path,
    config_path: Path,
    boundaries_path: Path,
    elevation_path: Path,
    generated_at: str,
) -> dict[str, Any]:
    if "development" not in risk_dir.as_posix().lower():
        raise ValueError("v1 build accepts development Risk JSON only")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("status") != "preregistered_before_spatial_metric_evaluation":
        raise ValueError("spatial diagnostic configuration is not preregistered")
    if config.get("truth_access") != "forbidden":
        raise ValueError("spatial diagnostic configuration must forbid truth")
    geojson = json.loads(boundaries_path.read_text(encoding="utf-8"))
    geometries = {
        feature["properties"]["region_id"]: feature["geometry"]
        for feature in geojson["features"]
    }
    diagnostics = [
        extract_spatial_diagnostic(path, config, geometries, elevation_path)
        for path in sorted(risk_dir.glob("*.json"))
    ]
    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "rule_version": config["version"],
        "rule_status": config["status"],
        "truth_access": "forbidden",
        "truth_accessed": False,
        "may_change_meteorological_risk": False,
        "diagnostics": diagnostics,
        "provenance": {
            "risk_dir": risk_dir.as_posix(),
            "risk_file_count": len(diagnostics),
            "config_path": config_path.as_posix(),
            "config_sha256": _sha256(config_path),
            "boundaries_path": boundaries_path.as_posix(),
            "boundaries_sha256": _sha256(boundaries_path),
            "elevation_path": elevation_path.as_posix(),
            "elevation_sha256": _sha256(elevation_path),
        },
    }
    canonical = json.dumps(bundle, ensure_ascii=False, sort_keys=True).encode("utf-8")
    bundle["content_sha256"] = hashlib.sha256(canonical).hexdigest()
    errors = validate_spatial_diagnostics(bundle)
    if errors:
        raise ValueError("invalid spatial diagnostics: " + "; ".join(errors))
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--risk-dir",
        type=Path,
        default=Path("handoff/risk_results/development_heavy_rain"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/forecast_spatial_diagnostics_v1.yaml"),
    )
    parser.add_argument(
        "--boundaries",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    parser.add_argument(
        "--elevation",
        type=Path,
        default=Path("data/external/worldclim_2_1_10m/elev/wc2.1_10m_elev.tif"),
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("handoff/knowledge_prior/development_spatial_diagnostics_v1.json"),
    )
    args = parser.parse_args()
    bundle = build_spatial_diagnostics(
        args.risk_dir,
        args.config,
        args.boundaries,
        args.elevation,
        args.generated_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output}")
    print(f"diagnostics={len(bundle['diagnostics'])}")
    print("truth_accessed=false")


if __name__ == "__main__":
    main()
