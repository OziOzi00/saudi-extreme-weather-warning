"""Create ADM1 indicator summaries from MAZU-like forecast NetCDF files."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import xarray as xr

from scripts.audit_mazu_2025 import EXPECTED
from scripts.summarize_mazu_2025_adm1 import build_region_masks


def summarize_file(
    path: Path, geojson_path: Path, registry: dict[str, str]
) -> list[dict[str, object]]:
    """Return long-form region/indicator rows for one contract-compliant forecast file."""
    rows: list[dict[str, object]] = []
    with xr.open_dataset(path, engine="scipy") as opened:
        dataset = opened.load()
        latitudes = np.asarray(dataset["latitude"].values)
        longitudes = np.asarray(dataset["longitude"].values)
        masks = build_region_masks(geojson_path, latitudes, longitudes)
        latitude_grid = np.broadcast_to(latitudes[:, None], (latitudes.size, longitudes.size))
        weights = np.cos(np.deg2rad(latitude_grid)).ravel()
        for region_id in sorted(masks):
            mask = masks[region_id]
            for indicator in EXPECTED:
                if indicator not in dataset:
                    raise ValueError(f"missing contract indicator {indicator} in {path}")
                variable = dataset[indicator]
                array = np.asarray(variable.values, dtype=float).ravel()
                values = array[mask]
                finite = np.isfinite(values)
                if finite.any():
                    finite_values = values[finite]
                    finite_weights = weights[mask][finite]
                    minimum = float(finite_values.min())
                    mean = float(np.average(finite_values, weights=finite_weights))
                    p95 = float(np.quantile(finite_values, 0.95))
                    maximum = float(finite_values.max())
                else:
                    minimum = mean = p95 = maximum = np.nan
                rows.append(
                    {
                        "source_file": f"handoff/mazu_like/{path.name}",
                        "initial_time": dataset.attrs["initial_time"],
                        "lead_time_hours": dataset.attrs["lead_time_hours"],
                        "valid_start_time": dataset.attrs["valid_start_time"],
                        "valid_end_time": dataset.attrs["valid_end_time"],
                        "region_id": region_id,
                        "region_name_en": registry[region_id],
                        "indicator": indicator,
                        "unit": variable.attrs.get("units", ""),
                        "region_cell_count": int(mask.sum()),
                        "valid_cell_count": int(finite.sum()),
                        "minimum": f"{minimum:.8g}",
                        "weighted_mean": f"{mean:.8g}",
                        "spatial_p95": f"{p95:.8g}",
                        "maximum": f"{maximum:.8g}",
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument(
        "--pattern",
        default="mazu_like_*.nc",
        help="Input filename glob. Use a narrower pattern for a sealed evaluation batch.",
    )
    parser.add_argument(
        "--geojson",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("configs/region_registry.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv"),
    )
    args = parser.parse_args()

    with args.registry.open(encoding="utf-8", newline="") as stream:
        registry = {row["region_id"]: row["region_name_en"] for row in csv.DictReader(stream)}
    files = sorted(args.input_dir.glob(args.pattern))
    if not files:
        raise FileNotFoundError(
            f"no files matching {args.pattern!r} found in {args.input_dir}"
        )
    rows = []
    for path in files:
        rows.extend(summarize_file(path, args.geojson, registry))
        print(path, flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(args.output)


if __name__ == "__main__":
    main()
