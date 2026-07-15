"""Audit coverage and metadata of the 11 shared MAZU 2025 indicators."""

from __future__ import annotations

import argparse
import csv
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


EXPECTED: dict[str, dict[str, object]] = {
    "daily_precip_total": {"unit": "mm", "min": 0.0, "max": 1000.0},
    "t2m_c": {"unit": "degC", "min": -80.0, "max": 70.0},
    "tmax_c": {"unit": "degC", "min": -80.0, "max": 70.0},
    "tmin_c": {"unit": "degC", "min": -80.0, "max": 70.0},
    "wind10_speed": {"unit": "m s-1", "min": 0.0, "max": 150.0},
    "pwat": {"unit": "kg m-2", "min": 0.0, "max": 100.0},
    "ivt": {"unit": "kg m-1 s-1", "min": 0.0, "max": 2000.0},
    "wind850_speed": {"unit": "m s-1", "min": 0.0, "max": 150.0},
    "wind_shear_850_200": {"unit": "m s-1", "min": 0.0, "max": 150.0},
    "omega500": {"unit": "Pa s-1", "min": -20.0, "max": 20.0},
    "geopotential_height500": {"unit": "gpm", "min": 4000.0, "max": 6500.0},
}


@dataclass
class FieldAudit:
    """Accumulate daily coverage and lightweight quality-control facts."""

    files_present: int = 0
    valid_days: int = 0
    valid_cells: int = 0
    total_cells: int = 0
    out_of_range_cells: int = 0
    units: set[str] = field(default_factory=set)
    dimensions: set[str] = field(default_factory=set)
    minimum: float | None = None
    maximum: float | None = None
    missing_or_empty_dates: list[str] = field(default_factory=list)


def _audit_file(path: str) -> tuple[str, dict[str, dict[str, object]]]:
    """Return compact audit facts for one daily file."""
    facts: dict[str, dict[str, object]] = {}
    with Dataset(path) as dataset:
        for name, expected in EXPECTED.items():
            if name not in dataset.variables:
                continue
            variable = dataset.variables[name]
            raw = variable[:]
            array = np.asarray(raw.filled(np.nan) if np.ma.isMaskedArray(raw) else raw)
            finite = np.isfinite(array)
            values = array[finite]
            lower = float(expected["min"])
            upper = float(expected["max"])
            facts[name] = {
                "valid_cells": int(finite.sum()),
                "total_cells": int(array.size),
                "out_of_range_cells": int(((values < lower) | (values > upper)).sum()),
                "unit": str(getattr(variable, "units", "")),
                "dimensions": ",".join(variable.dimensions),
                "minimum": float(values.min()) if values.size else None,
                "maximum": float(values.max()) if values.size else None,
            }
    date = Path(path).stem.removeprefix("saudi_indicators_")
    return date, facts


def audit(input_dir: Path, workers: int) -> tuple[int, dict[str, FieldAudit]]:
    """Scan all daily NetCDF files in parallel and retain only summary facts."""
    files = sorted(input_dir.glob("saudi_indicators_*.nc"))
    if not files:
        raise FileNotFoundError(f"no saudi_indicators_*.nc files found in {input_dir}")

    results = {name: FieldAudit() for name in EXPECTED}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        daily_results = executor.map(_audit_file, map(str, files), chunksize=4)
        for index, (date, facts) in enumerate(daily_results, start=1):
            for name in EXPECTED:
                fact = facts.get(name)
                if fact is None or int(fact["valid_cells"]) == 0:
                    results[name].missing_or_empty_dates.append(date)
                if fact is None:
                    continue
                result = results[name]
                result.files_present += 1
                valid_cells = int(fact["valid_cells"])
                result.valid_cells += valid_cells
                result.total_cells += int(fact["total_cells"])
                result.out_of_range_cells += int(fact["out_of_range_cells"])
                result.units.add(str(fact["unit"]))
                result.dimensions.add(str(fact["dimensions"]))
                if valid_cells:
                    result.valid_days += 1
                    day_minimum = float(fact["minimum"])
                    day_maximum = float(fact["maximum"])
                    result.minimum = (
                        day_minimum if result.minimum is None else min(result.minimum, day_minimum)
                    )
                    result.maximum = (
                        day_maximum if result.maximum is None else max(result.maximum, day_maximum)
                    )
            if index % 50 == 0 or index == len(files):
                print(f"audited {index}/{len(files)} files", flush=True)
    return len(files), results


def write_summary(output: Path, files_total: int, results: dict[str, FieldAudit]) -> None:
    """Write the small collaboration-safe coverage summary."""
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "indicator",
        "expected_unit",
        "observed_units",
        "dimensions",
        "files_total",
        "files_present",
        "valid_days",
        "missing_or_empty_days",
        "missing_or_empty_dates",
        "valid_cells",
        "total_cells",
        "valid_cell_ratio",
        "minimum",
        "maximum",
        "qc_range",
        "out_of_range_cells",
        "mapping_status",
    ]
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for name, expected in EXPECTED.items():
            result = results[name]
            observed_units = "|".join(sorted(result.units))
            unit_ok = result.units == {str(expected["unit"])}
            present_ok = result.files_present == files_total
            writer.writerow(
                {
                    "indicator": name,
                    "expected_unit": expected["unit"],
                    "observed_units": observed_units,
                    "dimensions": "|".join(sorted(result.dimensions)),
                    "files_total": files_total,
                    "files_present": result.files_present,
                    "valid_days": result.valid_days,
                    "missing_or_empty_days": files_total - result.valid_days,
                    "missing_or_empty_dates": "|".join(result.missing_or_empty_dates),
                    "valid_cells": result.valid_cells,
                    "total_cells": result.total_cells,
                    "valid_cell_ratio": (
                        f"{result.valid_cells / result.total_cells:.6f}"
                        if result.total_cells
                        else "0.000000"
                    ),
                    "minimum": "" if result.minimum is None else f"{result.minimum:.6g}",
                    "maximum": "" if result.maximum is None else f"{result.maximum:.6g}",
                    "qc_range": f"[{expected['min']}, {expected['max']}]",
                    "out_of_range_cells": result.out_of_range_cells,
                    "mapping_status": (
                        "unit_mismatch"
                        if not unit_ok
                        else (
                            "exact_name_unit_full_coverage"
                            if present_ok and result.valid_days == files_total
                            else "exact_name_unit_partial_coverage"
                        )
                    ),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("manifests/mazu_2025_indicator_coverage.csv"),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(8, os.cpu_count() or 1),
        help="Number of daily files decoded in parallel.",
    )
    args = parser.parse_args()
    files_total, results = audit(args.input_dir, max(1, args.workers))
    write_summary(args.output, files_total, results)
    print(args.output)


if __name__ == "__main__":
    main()
