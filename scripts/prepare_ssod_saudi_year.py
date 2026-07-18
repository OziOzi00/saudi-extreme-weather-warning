"""Verify and aggregate one local NOAA SSODv2 Saudi station-year collection."""

from __future__ import annotations

import argparse
from pathlib import Path

from saudi_warning.verification.ssod import (
    aggregate_ssod_regions,
    load_ssod_observations,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("manifests/ssod_v2_saudi_2020_files.csv")
    )
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data/external/ssod_v2/2020")
    )
    parser.add_argument(
        "--regions",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    parser.add_argument(
        "--daily-output",
        type=Path,
        default=Path("manifests/ssod_v2_saudi_2020_daily_summary.csv"),
    )
    parser.add_argument(
        "--station-output",
        type=Path,
        default=Path("manifests/ssod_v2_saudi_2020_station_regions.csv"),
    )
    args = parser.parse_args()
    observations, stations = load_ssod_observations(
        args.manifest, args.data_dir, args.regions
    )
    daily = aggregate_ssod_regions(observations)
    args.daily_output.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(args.daily_output, index=False)
    stations.to_csv(args.station_output, index=False)
    print(f"SSOD stations assigned to ADM1: {stations['station_id'].nunique()}")
    print(f"SSOD regional daily aggregation rows: {len(daily)}")
    print(args.daily_output)


if __name__ == "__main__":
    main()
