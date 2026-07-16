"""Screen GHCN-Daily station and element coverage for candidate case windows."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ELEMENT_SCALE = {"PRCP": 0.1, "TMAX": 0.1, "TMIN": 0.1}


def point_in_ring(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    """Return whether a point lies inside a GeoJSON linear ring."""

    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous[:2]
        x2, y2 = current[:2]
        crosses = (y1 > latitude) != (y2 > latitude)
        if crosses:
            boundary_x = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < boundary_x:
                inside = not inside
        previous = current
    return inside


def point_in_geometry(longitude: float, latitude: float, geometry: dict) -> bool:
    """Support Polygon and MultiPolygon without optional GIS dependencies."""

    coordinates = geometry["coordinates"]
    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    for polygon in polygons:
        if not point_in_ring(longitude, latitude, polygon[0]):
            continue
        if any(point_in_ring(longitude, latitude, hole) for hole in polygon[1:]):
            continue
        return True
    return False


def load_stations(path: Path, regions_path: Path) -> tuple[dict[str, dict], dict[str, int]]:
    """Load Saudi stations and assign them to the pinned ADM1 polygons."""

    geojson = json.loads(regions_path.read_text(encoding="utf-8"))
    features = geojson["features"]
    stations: dict[str, dict] = {}
    region_counts: dict[str, int] = defaultdict(int)
    with path.open(encoding="latin-1") as stream:
        for line in stream:
            station_id = line[0:11].strip()
            if not station_id.startswith("SA"):
                continue
            latitude = float(line[12:20])
            longitude = float(line[21:30])
            region_id = next(
                (
                    feature["properties"]["region_id"]
                    for feature in features
                    if point_in_geometry(longitude, latitude, feature["geometry"])
                ),
                None,
            )
            if region_id is None:
                continue
            stations[station_id] = {
                "station_id": station_id,
                "latitude": latitude,
                "longitude": longitude,
                "name": line[41:71].strip(),
                "region_id": region_id,
            }
            region_counts[region_id] += 1
    return stations, dict(region_counts)


def _utc_date(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.strftime("%Y%m%d")


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def collect_observations(
    archive_path: Path,
    station_ids: set[str],
    first_date: str,
    last_date: str,
) -> dict[tuple[str, str, str], float]:
    """Stream the global yearly archive and retain relevant quality-controlled rows."""

    observations: dict[tuple[str, str, str], float] = {}
    with gzip.open(archive_path, "rt", encoding="ascii", newline="") as stream:
        reader = csv.reader(stream)
        for row in reader:
            station_id, date, element = row[0], row[1], row[2]
            if station_id not in station_ids or not first_date <= date <= last_date:
                continue
            if element not in ELEMENT_SCALE or row[5]:
                continue
            observations[(station_id, date, element)] = int(row[3]) * ELEMENT_SCALE[element]
    return observations


def _element_summary(
    observations: dict[tuple[str, str, str], float],
    station_region: dict[str, str],
    region_id: str,
    first_date: str,
    last_date: str,
    element: str,
) -> tuple[int, int, float | None, float | None]:
    values = [
        (station_id, date, value)
        for (station_id, date, item_element), value in observations.items()
        if item_element == element
        and station_region[station_id] == region_id
        and first_date <= date <= last_date
    ]
    stations = {station_id for station_id, _, _ in values}
    dates = {date for _, date, _ in values}
    numbers = [value for _, _, value in values]
    return (
        len(stations),
        len(dates),
        min(numbers) if numbers else None,
        max(numbers) if numbers else None,
    )


def build_rows(
    cases: list[dict[str, str]],
    stations: dict[str, dict],
    region_counts: dict[str, int],
    observations: dict[tuple[str, str, str], float],
) -> list[dict[str, object]]:
    station_region = {station_id: item["region_id"] for station_id, item in stations.items()}
    rows = []
    for case in cases:
        first_date = _utc_date(case["event_start_time"])
        last_date = _utc_date(case["event_end_time"])
        for region_id in case["target_region_ids"].split(";"):
            row: dict[str, object] = {
                "case_id": case["case_id"],
                "case_role": case["case_role"],
                "hazard": case["hazard"],
                "region_id": region_id,
                "window_start_date": first_date,
                "window_end_date": last_date,
                "ghcn_stations_in_region": region_counts.get(region_id, 0),
            }
            for element in ELEMENT_SCALE:
                count, dates, minimum, maximum = _element_summary(
                    observations,
                    station_region,
                    region_id,
                    first_date,
                    last_date,
                    element,
                )
                prefix = element.lower()
                row[f"{prefix}_stations"] = count
                row[f"{prefix}_valid_days"] = dates
                row[f"{prefix}_min"] = "" if minimum is None else round(minimum, 2)
                row[f"{prefix}_max"] = "" if maximum is None else round(maximum, 2)
            rows.append(row)
    return rows


def build_daily_rows(
    observations: dict[tuple[str, str, str], float],
    stations: dict[str, dict],
) -> list[dict[str, object]]:
    """Aggregate daily regional extrema to support transparent control selection."""

    grouped: dict[tuple[str, str, str], list[tuple[str, float]]] = defaultdict(list)
    for (station_id, date, element), value in observations.items():
        region_id = stations[station_id]["region_id"]
        grouped[(region_id, date, element)].append((station_id, value))
    rows = []
    for (region_id, date, element), values in sorted(grouped.items()):
        numbers = [value for _, value in values]
        rows.append(
            {
                "region_id": region_id,
                "date": date,
                "element": element,
                "station_count": len({station_id for station_id, _ in values}),
                "minimum": round(min(numbers), 2),
                "maximum": round(max(numbers), 2),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, default=Path("data/external/ghcn_daily/2020.csv.gz")
    )
    parser.add_argument(
        "--stations",
        type=Path,
        default=Path("data/external/ghcn_daily/ghcnd-stations.txt"),
    )
    parser.add_argument(
        "--regions",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    parser.add_argument(
        "--cases", type=Path, default=Path("configs/case_catalog_candidates.csv")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("manifests/ghcn_2020_candidate_coverage.csv")
    )
    parser.add_argument(
        "--daily-output",
        type=Path,
        default=Path("manifests/ghcn_2020_saudi_daily_summary.csv"),
    )
    args = parser.parse_args()

    cases = load_cases(args.cases)
    stations, region_counts = load_stations(args.stations, args.regions)
    first_date = min(_utc_date(row["event_start_time"]) for row in cases)
    last_date = max(_utc_date(row["event_end_time"]) for row in cases)
    observations = collect_observations(
        args.archive,
        set(stations),
        first_date,
        last_date,
    )
    rows = build_rows(cases, stations, region_counts, observations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    daily_rows = build_daily_rows(observations, stations)
    with args.daily_output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(daily_rows[0]))
        writer.writeheader()
        writer.writerows(daily_rows)
    print(f"Saudi stations in inventory: {len(stations)}")
    print(f"candidate-region rows: {len(rows)}")
    print(args.output)
    print(args.daily_output)


if __name__ == "__main__":
    main()
