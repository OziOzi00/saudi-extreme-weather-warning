"""Prepare local GHCN-Daily or IMERG files as small ADM1 observation summaries."""

from __future__ import annotations

import argparse
from pathlib import Path

from saudi_warning.verification.observations import (
    accumulate_imerg_window,
    aggregate_ghcn_regions,
    aggregate_imerg_regions,
    assign_stations_to_regions,
    read_ghcn_by_year,
    read_ghcn_stations,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="source", required=True)

    ghcn = subparsers.add_parser("ghcn", help="normalize a local GHCN by-year archive")
    ghcn.add_argument("--year-file", type=Path, required=True)
    ghcn.add_argument("--stations-file", type=Path, required=True)
    ghcn.add_argument(
        "--geojson",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    ghcn.add_argument(
        "--aggregation",
        choices=["station_mean", "station_max", "station_min"],
        default="station_mean",
    )
    ghcn.add_argument("--output", type=Path, required=True)

    imerg = subparsers.add_parser("imerg", help="aggregate one local IMERG file/window")
    imerg.add_argument("--input", type=Path, required=True)
    imerg.add_argument("--valid-start", required=True)
    imerg.add_argument("--valid-end", required=True)
    imerg.add_argument("--variable", default="precipitation")
    imerg.add_argument(
        "--geojson",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    imerg.add_argument(
        "--aggregation",
        choices=["weighted_mean", "spatial_p95", "maximum"],
        default="spatial_p95",
    )
    imerg.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.source == "ghcn":
        observations = read_ghcn_by_year(args.year_file)
        stations = assign_stations_to_regions(
            read_ghcn_stations(args.stations_file), args.geojson
        )
        result = aggregate_ghcn_regions(observations, stations, args.aggregation)
    else:
        precipitation = accumulate_imerg_window(
            args.input, args.valid_start, args.valid_end, args.variable
        )
        result = aggregate_imerg_regions(precipitation, args.geojson, args.aggregation)
        result["valid_start_time"] = args.valid_start
        result["valid_end_time"] = args.valid_end
        result["observation_id"] = args.input.name
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(args.output)


if __name__ == "__main__":
    main()
