"""Aggregate downloaded IMERG daily GIS files for Saudi candidate windows."""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import xarray as xr

from saudi_warning.verification.observations import (
    IMERGRegionGrid,
    prepare_imerg_region_grid,
    read_imerg_gis_daily_zip,
    summarize_imerg_regions,
)


SAUDI_BOUNDS = (34.0, 16.0, 56.5, 33.5)


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write an empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_daily_files(root: Path) -> dict[date, Path]:
    files: dict[date, Path] = {}
    for path in root.rglob("3B-DAY-GIS*.V07B.zip"):
        compact_date = path.name.split("3IMERG.", 1)[1][:8]
        day = datetime.strptime(compact_date, "%Y%m%d").date()
        if day in files:
            raise ValueError(f"duplicate IMERG V07B daily file for {day}")
        files[day] = path
    return files


def _regional_metrics(
    field: xr.DataArray,
    regions_path: Path,
    region_grid: IMERGRegionGrid | None = None,
) -> dict[str, dict[str, float | None]]:
    rows = summarize_imerg_regions(field, regions_path, region_grid)
    return {
        str(row["region_id"]): {
            "weighted_mean": row["weighted_mean_mm"],
            "spatial_p95": row["spatial_p95_mm"],
            "maximum": row["maximum_mm"],
            "coverage_fraction": row["coverage_fraction"],
        }
        for row in rows.to_dict(orient="records")
    }


def process(
    cases: list[dict[str, str]],
    files: dict[date, Path],
    regions_path: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    rainfall_cases = [
        row
        for row in cases
        if row["hazard"] == "heavy_rain" and row["case_role"] in {"event", "control"}
    ]
    required_dates = sorted(
        {
            day
            for case in rainfall_cases
            for day in _date_range(
                _parse_date(case["event_start_time"]),
                _parse_date(case["event_end_time"]),
            )
        }
    )
    missing = [day for day in required_dates if day not in files]
    if missing:
        raise FileNotFoundError(f"missing IMERG daily files: {missing}")

    fields: dict[date, xr.DataArray] = {}
    region_grid: IMERGRegionGrid | None = None
    daily_rows: list[dict[str, object]] = []
    file_rows: list[dict[str, object]] = []
    for day in required_dates:
        path = files[day]
        field = read_imerg_gis_daily_zip(path, SAUDI_BOUNDS)
        fields[day] = field
        if region_grid is None:
            region_grid = prepare_imerg_region_grid(field, regions_path)
        metrics = _regional_metrics(field, regions_path, region_grid)
        for region_id, values in sorted(metrics.items()):
            daily_rows.append(
                {
                    "date": day.isoformat(),
                    "region_id": region_id,
                    "weighted_mean_mm": round(float(values["weighted_mean"]), 3),
                    "spatial_p95_mm": round(float(values["spatial_p95"]), 3),
                    "maximum_mm": round(float(values["maximum"]), 3),
                    "coverage_fraction": round(float(values["coverage_fraction"]), 6),
                    "product": "IMERG Final Run daily GIS accumulation",
                    "version": "V07B",
                }
            )
        file_rows.append(
            {
                "date": day.isoformat(),
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "local_path": path.as_posix(),
                "source_url": (
                    "https://arthurhouhttps.pps.eosdis.nasa.gov/gpmdata/"
                    f"{day:%Y/%m/%d}/gis/{path.name}"
                ),
                "product": "IMERG Final Run daily GIS accumulation",
                "version": "V07B",
                "license_or_terms": "NASA GPM/PPS data policy applies",
            }
        )

    window_rows: list[dict[str, object]] = []
    for case in rainfall_cases:
        days = list(
            _date_range(
                _parse_date(case["event_start_time"]),
                _parse_date(case["event_end_time"]),
            )
        )
        stack = xr.concat([fields[day] for day in days], dim="day")
        window = stack.sum("day", skipna=False)
        window.attrs = {"units": "mm"}
        metrics = _regional_metrics(window, regions_path, region_grid)
        for region_id in case["target_region_ids"].split(";"):
            values = metrics[region_id]
            window_rows.append(
                {
                    "case_id": case["case_id"],
                    "case_role": case["case_role"],
                    "dataset_split": case["dataset_split"],
                    "region_id": region_id,
                    "window_start_date": days[0].isoformat(),
                    "window_end_date": days[-1].isoformat(),
                    "window_days": len(days),
                    "weighted_mean_mm": round(float(values["weighted_mean"]), 3),
                    "spatial_p95_mm": round(float(values["spatial_p95"]), 3),
                    "maximum_mm": round(float(values["maximum"]), 3),
                    "coverage_fraction": round(float(values["coverage_fraction"]), 6),
                    "product": "IMERG Final Run daily GIS accumulation",
                    "version": "V07B",
                }
            )
    return daily_rows, window_rows, file_rows


def build_control_screening(
    window_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Compare each control region with every event window in the same region."""

    events_by_region: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in window_rows:
        if row["case_role"] == "event":
            events_by_region[str(row["region_id"])].append(row)
    screening_rows = []
    for control in window_rows:
        if control["case_role"] != "control":
            continue
        region_id = str(control["region_id"])
        same_region = events_by_region.get(region_id, [])
        control_start = date.fromisoformat(str(control["window_start_date"]))
        references = [
            row
            for row in same_region
            if abs(
                (
                    date.fromisoformat(str(row["window_start_date"])) - control_start
                ).days
            )
            <= 31
        ]
        if not references and same_region:
            nearest_distance = min(
                abs(
                    (
                        date.fromisoformat(str(row["window_start_date"]))
                        - control_start
                    ).days
                )
                for row in same_region
            )
            references = [
                row
                for row in same_region
                if abs(
                    (
                        date.fromisoformat(str(row["window_start_date"]))
                        - control_start
                    ).days
                )
                == nearest_distance
            ]
        if not references:
            status = "no_matching_event"
            event_ids = ""
            minimum_event_p95 = None
            minimum_event_maximum = None
            ratio = None
        else:
            event_ids = ";".join(sorted({str(row["case_id"]) for row in references}))
            minimum_event_p95 = min(float(row["spatial_p95_mm"]) for row in references)
            minimum_event_maximum = min(float(row["maximum_mm"]) for row in references)
            control_p95 = float(control["spatial_p95_mm"])
            control_maximum = float(control["maximum_mm"])
            ratio = control_p95 / minimum_event_p95 if minimum_event_p95 else None
            status = (
                "imerg_screened_lower_intensity"
                if control_p95 < minimum_event_p95
                and control_maximum < minimum_event_maximum
                else "imerg_not_lower_than_event"
            )
        screening_rows.append(
            {
                "control_case_id": control["case_id"],
                "region_id": region_id,
                "comparison_event_ids": event_ids,
                "control_spatial_p95_mm": control["spatial_p95_mm"],
                "minimum_event_spatial_p95_mm": minimum_event_p95,
                "p95_ratio_to_minimum_event": (
                    "" if ratio is None else round(ratio, 4)
                ),
                "control_maximum_mm": control["maximum_mm"],
                "minimum_event_maximum_mm": minimum_event_maximum,
                "screening_status": status,
                "screening_rule": (
                    "control P95 and maximum are both below every same-region event "
                    "within 31 days; nearest event is fallback"
                ),
                "product": "IMERG Final Run daily GIS accumulation",
                "version": "V07B",
            }
        )
    return screening_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path("configs/case_catalog_candidates.csv")
    )
    parser.add_argument(
        "--input-root", type=Path, default=Path("data/external/imerg_final_v07b")
    )
    parser.add_argument(
        "--regions",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    parser.add_argument(
        "--daily-output",
        type=Path,
        default=Path("manifests/imerg_2020_saudi_daily_summary.csv"),
    )
    parser.add_argument(
        "--window-output",
        type=Path,
        default=Path("manifests/imerg_2020_candidate_window_summary.csv"),
    )
    parser.add_argument(
        "--file-output",
        type=Path,
        default=Path("manifests/imerg_v07b_daily_files.csv"),
    )
    parser.add_argument(
        "--screening-output",
        type=Path,
        default=Path("manifests/imerg_2020_control_screening.csv"),
    )
    args = parser.parse_args()

    daily_rows, window_rows, file_rows = process(
        read_csv(args.catalog), find_daily_files(args.input_root), args.regions
    )
    write_csv(args.daily_output, daily_rows)
    write_csv(args.window_output, window_rows)
    write_csv(args.file_output, file_rows)
    screening_rows = build_control_screening(window_rows)
    write_csv(args.screening_output, screening_rows)
    print(f"wrote {args.daily_output}: {len(daily_rows)} rows")
    print(f"wrote {args.window_output}: {len(window_rows)} rows")
    print(f"wrote {args.file_output}: {len(file_rows)} rows")
    print(f"wrote {args.screening_output}: {len(screening_rows)} rows")


if __name__ == "__main__":
    main()
