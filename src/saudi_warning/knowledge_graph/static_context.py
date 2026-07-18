"""Download and aggregate truth-sealed WorldClim context for Saudi ADM1 regions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml


SCHEMA_VERSION = "static_knowledge_context_v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _weighted_quantile(
    values: np.ndarray, weights: np.ndarray, quantile: float
) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    target = quantile * cumulative[-1]
    return float(sorted_values[np.searchsorted(cumulative, target, side="left")])


def _weighted_stats(
    values: np.ndarray, weights: np.ndarray, *, elevation: bool
) -> dict[str, float | int]:
    if values.size == 0:
        raise ValueError("region mask contains no valid raster cells")
    result: dict[str, float | int] = {
        "cell_count": int(values.size),
        "mean": float(np.average(values, weights=weights)),
        "p90": _weighted_quantile(values, weights, 0.90),
        "max": float(np.max(values)),
    }
    if elevation:
        p10 = _weighted_quantile(values, weights, 0.10)
        p50 = _weighted_quantile(values, weights, 0.50)
        result.update(
            {
                "p10": p10,
                "p50": p50,
                "p90_minus_p10": float(result["p90"]) - p10,
                "share_above_1000": float(
                    np.sum(weights[values >= 1000.0]) / np.sum(weights)
                ),
            }
        )
    return result


def _masked_values(path: Path, geometry: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    try:
        import rasterio
        from rasterio.mask import mask
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError('Static-context build requires: pip install -e ".[knowledge]"') from exc

    with rasterio.open(path) as dataset:
        clipped, transform = mask(dataset, [geometry], crop=True, filled=False)
        band = clipped[0]
        valid = ~np.ma.getmaskarray(band)
        values = np.asarray(band.data[valid], dtype=np.float64)
        rows, _ = np.nonzero(valid)
        latitudes = transform.f + (rows + 0.5) * transform.e
        weights = np.cos(np.deg2rad(latitudes)).astype(np.float64)
        finite = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
        return values[finite], weights[finite]


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    temporary.replace(destination)


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    resolved_destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if resolved_destination not in target.parents and target != resolved_destination:
                raise ValueError(f"unsafe archive member: {member.filename}")
        bundle.extractall(destination)


def prepare_sources(config: dict[str, Any], data_dir: Path) -> None:
    for source in config["sources"]:
        archive = data_dir / str(source["archive_name"])
        if not archive.exists():
            _download(str(source["source_url"]), archive)
        digest = _sha256(archive)
        if digest != source["archive_sha256"]:
            raise ValueError(f"SHA-256 mismatch for {archive}: {digest}")
        role = str(source["role"])
        destination = data_dir / ("elev" if role == "terrain_context" else "prec")
        _safe_extract(archive, destination)


def validate_static_context(context: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if context.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if context.get("status") != "context_only_not_validated":
        errors.append("status must be context_only_not_validated")
    if context.get("truth_access") != "forbidden":
        errors.append("truth_access must be forbidden")
    if context.get("truth_accessed") is not False:
        errors.append("truth_accessed must be false")
    if context.get("may_change_meteorological_risk") is not False:
        errors.append("static context may not change meteorological risk")
    profiles = context.get("profiles")
    if not isinstance(profiles, list) or len(profiles) != 156:
        errors.append("profiles must contain 13 regions x 12 months")
    else:
        identifiers = {profile.get("id") for profile in profiles}
        if len(identifiers) != len(profiles):
            errors.append("profile IDs must be unique")
        for profile in profiles:
            if profile.get("prior_status") != "context_only":
                errors.append("every profile must remain context_only")
            if profile.get("knowledge_prior_risk") is not None:
                errors.append("context-only profiles cannot assign knowledge risk")
    return errors


def build_static_context(
    config_path: Path,
    data_dir: Path,
    regions_path: Path,
    boundaries_path: Path,
    generated_at: str,
) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("status") != "context_only_not_validated":
        raise ValueError("static context must remain context_only_not_validated")
    if config.get("truth_access") != "forbidden":
        raise ValueError("static context must forbid truth access")
    _parse_time(generated_at)
    prepare_sources(config, data_dir)

    with regions_path.open(encoding="utf-8-sig", newline="") as stream:
        regions = {row["region_id"]: row for row in csv.DictReader(stream)}
    geojson = json.loads(boundaries_path.read_text(encoding="utf-8"))
    geometries = {
        feature["properties"]["region_id"]: feature["geometry"]
        for feature in geojson["features"]
    }
    if set(regions) != set(geometries):
        raise ValueError("region registry and boundary IDs diverge")

    elevation_path = data_dir / "elev" / "wc2.1_10m_elev.tif"
    precipitation_paths = {
        month: data_dir / "prec" / f"wc2.1_10m_prec_{month:02d}.tif"
        for month in range(1, 13)
    }
    profiles: list[dict[str, Any]] = []
    temporal = config["temporal_policy"]
    source_ids = [str(source["id"]) for source in config["sources"]]
    for region_id in sorted(regions):
        geometry = geometries[region_id]
        elevation_values, elevation_weights = _masked_values(elevation_path, geometry)
        elevation = _weighted_stats(
            elevation_values, elevation_weights, elevation=True
        )
        for month, path in precipitation_paths.items():
            precipitation_values, precipitation_weights = _masked_values(path, geometry)
            precipitation = _weighted_stats(
                precipitation_values, precipitation_weights, elevation=False
            )
            profiles.append(
                {
                    "id": f"{region_id}:month{month:02d}:worldclim21",
                    "region_id": region_id,
                    "region_name_en": regions[region_id]["region_name_en"],
                    "month": month,
                    "prior_status": "context_only",
                    "knowledge_prior_risk": None,
                    "confidence": "low",
                    "terrain": {
                        "cell_count": elevation["cell_count"],
                        "mean_m": round(float(elevation["mean"]), 3),
                        "p10_m": round(float(elevation["p10"]), 3),
                        "p50_m": round(float(elevation["p50"]), 3),
                        "p90_m": round(float(elevation["p90"]), 3),
                        "max_m": round(float(elevation["max"]), 3),
                        "p90_minus_p10_m": round(
                            float(elevation["p90_minus_p10"]), 3
                        ),
                        "share_above_1000m": round(
                            float(elevation["share_above_1000"]), 6
                        ),
                    },
                    "precipitation_climatology": {
                        "cell_count": precipitation["cell_count"],
                        "mean_mm": round(float(precipitation["mean"]), 3),
                        "p90_mm": round(float(precipitation["p90"]), 3),
                        "max_mm": round(float(precipitation["max"]), 3),
                    },
                    "temporal": {
                        "reference_period_start": temporal["reference_period_start"],
                        "reference_period_end": temporal["reference_period_end"],
                        "available_at": temporal["available_at"],
                        "valid_from": temporal["valid_from"],
                        "valid_to": temporal["valid_to"],
                        "recorded_at": generated_at,
                    },
                    "source_ids": source_ids,
                    "resolution_arc_minutes": config["resolution"]["arc_minutes"],
                }
            )

    sources = []
    for source in config["sources"]:
        archive = data_dir / source["archive_name"]
        sources.append(
            {
                "id": source["id"],
                "role": source["role"],
                "title": source["title"],
                "source_url": source["source_url"],
                "landing_page_url": source["landing_page_url"],
                "archive_name": source["archive_name"],
                "archive_sha256": _sha256(archive),
                "available_at": temporal["available_at"],
                "reference_period_start": temporal["reference_period_start"],
                "reference_period_end": temporal["reference_period_end"],
                "recorded_at": generated_at,
                "unit": source["unit"],
                "license_or_terms": "WorldClim research and related activities; cite Fick and Hijmans (2017)",
                "citation": "Fick, S.E. and Hijmans, R.J. (2017), doi:10.1002/joc.5086",
            }
        )
    context: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": config["status"],
        "knowledge_role": config["knowledge_role"],
        "truth_access": "forbidden",
        "truth_accessed": False,
        "may_change_meteorological_risk": False,
        "sources": sources,
        "profiles": profiles,
        "limitations": list(config["limitations"]),
    }
    canonical = json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")
    context["content_sha256"] = hashlib.sha256(canonical).hexdigest()
    errors = validate_static_context(context)
    if errors:
        raise ValueError("invalid static context: " + "; ".join(errors))
    return context


def _write_csv(context: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "profile_id", "region_id", "region_name_en", "month",
        "elevation_mean_m", "elevation_p10_m", "elevation_p50_m",
        "elevation_p90_m", "elevation_max_m", "elevation_p90_minus_p10_m",
        "elevation_share_above_1000m", "precipitation_mean_mm",
        "precipitation_p90_mm", "precipitation_max_mm", "available_at",
        "prior_status", "knowledge_prior_risk", "source_ids",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for profile in context["profiles"]:
            writer.writerow(
                {
                    "profile_id": profile["id"],
                    "region_id": profile["region_id"],
                    "region_name_en": profile["region_name_en"],
                    "month": profile["month"],
                    "elevation_mean_m": profile["terrain"]["mean_m"],
                    "elevation_p10_m": profile["terrain"]["p10_m"],
                    "elevation_p50_m": profile["terrain"]["p50_m"],
                    "elevation_p90_m": profile["terrain"]["p90_m"],
                    "elevation_max_m": profile["terrain"]["max_m"],
                    "elevation_p90_minus_p10_m": profile["terrain"]["p90_minus_p10_m"],
                    "elevation_share_above_1000m": profile["terrain"]["share_above_1000m"],
                    "precipitation_mean_mm": profile["precipitation_climatology"]["mean_mm"],
                    "precipitation_p90_mm": profile["precipitation_climatology"]["p90_mm"],
                    "precipitation_max_mm": profile["precipitation_climatology"]["max_mm"],
                    "available_at": profile["temporal"]["available_at"],
                    "prior_status": profile["prior_status"],
                    "knowledge_prior_risk": "",
                    "source_ids": ";".join(profile["source_ids"]),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/static_knowledge_context_v1.yaml"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/external/worldclim_2_1_10m"))
    parser.add_argument("--regions", type=Path, default=Path("configs/region_registry.csv"))
    parser.add_argument("--boundaries", type=Path, default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"))
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, default=Path("handoff/knowledge_prior/static_context_v1.json"))
    parser.add_argument("--csv-output", type=Path, default=Path("handoff/knowledge_prior/worldclim_adm1_monthly_context.csv"))
    args = parser.parse_args()
    context = build_static_context(
        args.config, args.data_dir, args.regions, args.boundaries, args.generated_at
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(context, args.csv_output)
    print(f"wrote {args.output}")
    print(f"wrote {args.csv_output}")
    print(f"profiles={len(context['profiles'])}")
    print("truth_accessed=false")


if __name__ == "__main__":
    main()
