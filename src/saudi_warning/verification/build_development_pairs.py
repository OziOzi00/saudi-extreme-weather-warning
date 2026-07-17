"""Build development-only forecast/observation pairs and a coverage audit."""

from __future__ import annotations

import argparse
import csv
import gzip
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from saudi_warning.verification.metrics import PAIR_COLUMNS, validate_pairs
from saudi_warning.verification.observations import (
    assign_stations_to_regions,
    read_ghcn_stations,
)


LEADS = (24, 48, 72)
GRID_AGGREGATIONS = {
    "weighted_mean": "weighted_mean_mm",
    "spatial_p95": "spatial_p95_mm",
    "maximum": "maximum_mm",
}
STATION_AGGREGATIONS = {
    "station_mean": np.mean,
    "station_max": np.max,
    "station_min": np.min,
}
PAIR_FIELDS = [
    "case_id",
    "initial_time",
    "lead_time_hours",
    "valid_start_time",
    "valid_end_time",
    "region_id",
    "variable",
    "aggregation",
    "forecast_value",
    "observed_value",
    "unit",
    "event_threshold",
    "observation_source",
    "observation_id",
    "coverage_fraction",
    "station_count",
    "qc_status",
]
COVERAGE_FIELDS = [
    "case_id",
    "dataset_split",
    "hazard",
    "region_id",
    "lead_time_hours",
    "valid_start_time",
    "valid_end_time",
    "variable",
    "aggregation",
    "observation_source",
    "pair_status",
    "coverage_fraction",
    "station_count",
    "reason",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def development_cases(path: Path) -> list[dict[str, str]]:
    """Select only approved development cases and never expose independent test rows."""

    cases = [
        row
        for row in read_csv(path)
        if row["selection_status"] == "approved" and row["dataset_split"] == "development"
    ]
    if not cases:
        raise ValueError("catalog contains no approved development cases")
    if any(row["dataset_split"] != "development" for row in cases):
        raise AssertionError("independent test case entered development pairing")
    return cases


def _forecast_lookup(
    rows: list[dict[str, str]],
) -> dict[tuple[str, int, str, str], dict[str, str]]:
    lookup: dict[tuple[str, int, str, str], dict[str, str]] = {}
    for row in rows:
        key = (
            row["initial_time"],
            int(row["lead_time_hours"]),
            row["region_id"],
            row["indicator"],
        )
        if key in lookup:
            raise ValueError(f"duplicate forecast summary identity: {key}")
        lookup[key] = row
    return lookup


def _audit_row(
    case: dict[str, str],
    region_id: str,
    lead: int,
    forecast: dict[str, str],
    variable: str,
    aggregation: str,
    source: str,
    status: str,
    coverage: float,
    station_count: int | str,
    reason: str,
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "dataset_split": case["dataset_split"],
        "hazard": case["hazard"],
        "region_id": region_id,
        "lead_time_hours": lead,
        "valid_start_time": forecast["valid_start_time"],
        "valid_end_time": forecast["valid_end_time"],
        "variable": variable,
        "aggregation": aggregation,
        "observation_source": source,
        "pair_status": status,
        "coverage_fraction": coverage,
        "station_count": station_count,
        "reason": reason,
    }


def build_imerg_pairs(
    cases: list[dict[str, str]],
    forecast_rows: list[dict[str, str]],
    imerg_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    forecast_lookup = _forecast_lookup(forecast_rows)
    observation_lookup = {
        (row["date"], row["region_id"]): row for row in imerg_rows
    }
    pairs: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for case in cases:
        if case["hazard"] != "heavy_rain":
            continue
        for region_id in case["target_region_ids"].split(";"):
            for lead in LEADS:
                key = (case["initial_time"], lead, region_id, "daily_precip_total")
                if key not in forecast_lookup:
                    raise ValueError(f"missing forecast summary: {key}")
                forecast = forecast_lookup[key]
                day = forecast["valid_start_time"][:10]
                observation = observation_lookup.get((day, region_id))
                for aggregation, observed_column in GRID_AGGREGATIONS.items():
                    if observation is None:
                        audit.append(
                            _audit_row(
                                case,
                                region_id,
                                lead,
                                forecast,
                                "daily_precip_total",
                                aggregation,
                                "IMERG",
                                "missing",
                                0.0,
                                "",
                                "IMERG daily file not downloaded for forecast UTC window",
                            )
                        )
                        continue
                    coverage = float(observation["coverage_fraction"])
                    qc_status = "accepted" if coverage >= 0.95 else "provisional"
                    reason = (
                        "exact UTC daily window and coverage >= 0.95"
                        if qc_status == "accepted"
                        else "IMERG coverage below 0.95"
                    )
                    pairs.append(
                        {
                            "case_id": case["case_id"],
                            "initial_time": case["initial_time"],
                            "lead_time_hours": lead,
                            "valid_start_time": forecast["valid_start_time"],
                            "valid_end_time": forecast["valid_end_time"],
                            "region_id": region_id,
                            "variable": "daily_precip_total",
                            "aggregation": aggregation,
                            "forecast_value": float(forecast[aggregation]),
                            "observed_value": float(observation[observed_column]),
                            "unit": "mm",
                            "event_threshold": "",
                            "observation_source": "IMERG",
                            "observation_id": (
                                f"IMERG_FINAL_V07B_{day}_{region_id}_{aggregation}"
                            ),
                            "coverage_fraction": coverage,
                            "station_count": "",
                            "qc_status": qc_status,
                        }
                    )
                    audit.append(
                        _audit_row(
                            case,
                            region_id,
                            lead,
                            forecast,
                            "daily_precip_total",
                            aggregation,
                            "IMERG",
                            f"paired_{qc_status}",
                            coverage,
                            "",
                            reason,
                        )
                    )
    return pairs, audit


def _load_target_ghcn(
    path: Path,
    station_ids: set[str],
    dates: set[str],
) -> dict[tuple[str, str, str], float]:
    values: dict[tuple[str, str, str], float] = {}
    element_to_variable = {"TMAX": "tmax_c", "TMIN": "tmin_c"}
    with gzip.open(path, "rt", encoding="ascii", newline="") as stream:
        for row in csv.reader(stream):
            if (
                row[0] not in station_ids
                or row[1] not in dates
                or row[2] not in element_to_variable
                or row[5].strip()
            ):
                continue
            values[(row[0], row[1], element_to_variable[row[2]])] = int(row[3]) / 10
    return values


def _sample_station_values(
    path: Path, variable: str, stations: pd.DataFrame
) -> np.ndarray:
    with xr.open_dataset(path, engine="scipy") as dataset:
        sampled = dataset[variable].sel(
            latitude=xr.DataArray(stations["latitude"].to_numpy(), dims="station"),
            longitude=xr.DataArray(stations["longitude"].to_numpy(), dims="station"),
            method="nearest",
        )
        return np.asarray(sampled.values, dtype=float)


def build_ghcn_pairs(
    cases: list[dict[str, str]],
    forecast_rows: list[dict[str, str]],
    forecast_dir: Path,
    archive_path: Path,
    stations_path: Path,
    regions_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    heat_cases = [row for row in cases if row["hazard"] == "heatwave"]
    if not heat_cases:
        return [], []
    forecast_lookup = _forecast_lookup(forecast_rows)
    stations = read_ghcn_stations(stations_path)
    stations = stations[stations["station_id"].astype(str).str.startswith("SA")]
    stations = assign_stations_to_regions(stations, regions_path)
    target_regions = {
        region
        for case in heat_cases
        for region in case["target_region_ids"].split(";")
    }
    stations = stations[stations["region_id"].isin(target_regions)].copy()
    dates = {
        forecast_lookup[(case["initial_time"], lead, region, "tmax_c")][
            "valid_start_time"
        ][:10].replace("-", "")
        for case in heat_cases
        for region in case["target_region_ids"].split(";")
        for lead in LEADS
    }
    observations = _load_target_ghcn(
        archive_path, set(stations["station_id"].astype(str)), dates
    )
    pairs: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for case in heat_cases:
        for region_id in case["target_region_ids"].split(";"):
            region_stations = stations[stations["region_id"] == region_id]
            denominator = int(region_stations["station_id"].nunique())
            for lead in LEADS:
                for variable in ("tmax_c", "tmin_c"):
                    key = (case["initial_time"], lead, region_id, variable)
                    if key not in forecast_lookup:
                        raise ValueError(f"missing forecast summary: {key}")
                    forecast = forecast_lookup[key]
                    day = forecast["valid_start_time"][:10].replace("-", "")
                    available = region_stations[
                        region_stations["station_id"].map(
                            lambda station_id: (str(station_id), day, variable)
                            in observations
                        )
                    ].copy()
                    count = int(available["station_id"].nunique())
                    coverage = 0.0 if denominator == 0 else count / denominator
                    if count:
                        available["observed_value"] = available["station_id"].map(
                            lambda station_id: observations[(str(station_id), day, variable)]
                        )
                        forecast_path = forecast_dir / Path(forecast["source_file"]).name
                        available["forecast_value"] = _sample_station_values(
                            forecast_path, variable, available
                        )
                    for aggregation, function in STATION_AGGREGATIONS.items():
                        if not count:
                            audit.append(
                                _audit_row(
                                    case,
                                    region_id,
                                    lead,
                                    forecast,
                                    variable,
                                    aggregation,
                                    "GHCN_DAILY",
                                    "missing",
                                    coverage,
                                    0,
                                    "no quality-controlled GHCN station value",
                                )
                            )
                            continue
                        pairs.append(
                            {
                                "case_id": case["case_id"],
                                "initial_time": case["initial_time"],
                                "lead_time_hours": lead,
                                "valid_start_time": forecast["valid_start_time"],
                                "valid_end_time": forecast["valid_end_time"],
                                "region_id": region_id,
                                "variable": variable,
                                "aggregation": aggregation,
                                "forecast_value": float(
                                    function(available["forecast_value"].to_numpy())
                                ),
                                "observed_value": float(
                                    function(available["observed_value"].to_numpy())
                                ),
                                "unit": "degC",
                                "event_threshold": "",
                                "observation_source": "GHCN_DAILY",
                                "observation_id": (
                                    f"GHCN_DAILY_2020_{day}_{region_id}_{variable}_{aggregation}"
                                ),
                                "coverage_fraction": coverage,
                                "station_count": count,
                                "qc_status": "provisional",
                            }
                        )
                        audit.append(
                            _audit_row(
                                case,
                                region_id,
                                lead,
                                forecast,
                                variable,
                                aggregation,
                                "GHCN_DAILY",
                                "paired_provisional",
                                coverage,
                                count,
                                "GHCN observation time is missing; UTC daily alignment unverified",
                            )
                        )
    return pairs, audit


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("configs/case_catalog_candidates.csv"))
    parser.add_argument(
        "--forecast-summary",
        type=Path,
        default=Path("handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv"),
    )
    parser.add_argument("--forecast-dir", type=Path, default=Path("handoff/mazu_like"))
    parser.add_argument(
        "--imerg-summary",
        type=Path,
        default=Path("manifests/imerg_2020_saudi_daily_summary.csv"),
    )
    parser.add_argument(
        "--ghcn-archive", type=Path, default=Path("data/external/ghcn_daily/2020.csv.gz")
    )
    parser.add_argument(
        "--ghcn-stations",
        type=Path,
        default=Path("data/external/ghcn_daily/ghcnd-stations.txt"),
    )
    parser.add_argument(
        "--regions",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("handoff/weather_verification/development_pairs.csv"),
    )
    parser.add_argument(
        "--coverage-output",
        type=Path,
        default=Path("manifests/development_pairing_coverage.csv"),
    )
    args = parser.parse_args()

    cases = development_cases(args.catalog)
    forecast_rows = read_csv(args.forecast_summary)
    imerg_pairs, imerg_audit = build_imerg_pairs(
        cases, forecast_rows, read_csv(args.imerg_summary)
    )
    ghcn_pairs, ghcn_audit = build_ghcn_pairs(
        cases,
        forecast_rows,
        args.forecast_dir,
        args.ghcn_archive,
        args.ghcn_stations,
        args.regions,
    )
    pairs = imerg_pairs + ghcn_pairs
    audit = imerg_audit + ghcn_audit
    if not pairs or not audit:
        raise ValueError("pairing produced no output")
    frame = pd.DataFrame(pairs)
    errors = validate_pairs(frame)
    if errors:
        raise ValueError("; ".join(errors))
    if set(frame.columns) != PAIR_COLUMNS:
        raise AssertionError("pair output columns diverge from verification contract")
    if any(row["dataset_split"] != "development" for row in audit):
        raise AssertionError("independent test data leaked into development audit")
    write_csv(args.output, pairs, PAIR_FIELDS)
    write_csv(args.coverage_output, audit, COVERAGE_FIELDS)
    status_counts = pd.Series([row["pair_status"] for row in audit]).value_counts()
    print(args.output)
    print(args.coverage_output)
    print(f"development_cases={len(cases)} pairs={len(pairs)} expected={len(audit)}")
    print(" ".join(f"{key}={value}" for key, value in status_counts.items()))


if __name__ == "__main__":
    main()
