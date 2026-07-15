"""Normalize a pinned geoBoundaries Saudi ADM1 GeoJSON for project use."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


SOURCE_METADATA = {
    "boundary_id": "SAU-ADM1-25081817",
    "boundary_year_represented": "2017",
    "boundary_source": "OpenStreetMap, Wambacher",
    "boundary_license": "Open Data Commons Open Database License 1.0",
    "source_commit": "9469f09",
    "source_sha256": "75abcfd5a61790e5e505974f04cbd1d869e58d81b6faba039b000987e659e840",
    "api_url": "https://www.geoboundaries.org/api/current/gbOpen/SAU/ADM1/",
    "download_url": (
        "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/"
        "releaseData/gbOpen/SAU/ADM1/geoBoundaries-SAU-ADM1.geojson"
    ),
}

NAME_SOURCE_URL = "https://ncar.gov.sa/regions-coding"
HEADQUARTERS_SOURCE_URL = (
    "https://www.moi.gov.sa/wps/portal/Home/sectors/moidiwan/regions/contents/"
)
REGION_METADATA = {
    "SA-01": ("Riyadh Region", "منطقة الرياض", "Riyadh", "الرياض"),
    "SA-02": ("Makkah Region", "منطقة مكة المكرمة", "Makkah", "مكة المكرمة"),
    "SA-03": ("Al Madinah Region", "منطقة المدينة المنورة", "Al Madinah", "المدينة المنورة"),
    "SA-04": ("Eastern Region", "المنطقة الشرقية", "Dammam", "الدمام"),
    "SA-05": ("Al-Qassim Region", "منطقة القصيم", "Buraidah", "بريدة"),
    "SA-06": ("Hail Region", "منطقة حائل", "Hail", "حائل"),
    "SA-07": ("Tabuk Region", "منطقة تبوك", "Tabuk", "تبوك"),
    "SA-08": ("Northern Borders Region", "منطقة الحدود الشمالية", "Arar", "عرعر"),
    "SA-09": ("Jazan Region", "منطقة جازان", "Jazan", "جازان"),
    "SA-10": ("Najran Region", "منطقة نجران", "Najran", "نجران"),
    "SA-11": ("Al Bahah Region", "منطقة الباحة", "Al Bahah", "الباحة"),
    "SA-12": ("Al Jawf Region", "منطقة الجوف", "Sakaka", "سكاكا"),
    "SA-14": ("Asir Region", "منطقة عسير", "Abha", "أبها"),
}


def normalize(source: Path) -> dict[str, object]:
    """Validate the source and return stable project properties with unchanged geometry."""
    data = json.loads(source.read_text(encoding="utf-8"))
    features = data.get("features", [])
    if data.get("type") != "FeatureCollection" or len(features) != 13:
        raise ValueError("expected a 13-feature Saudi ADM1 FeatureCollection")

    normalized = []
    region_ids: set[str] = set()
    for feature in features:
        properties = feature.get("properties", {})
        region_id = properties.get("shapeISO")
        if (
            not isinstance(region_id, str)
            or not region_id.startswith("SA-")
            or properties.get("shapeGroup") != "SAU"
            or properties.get("shapeType") != "ADM1"
        ):
            raise ValueError(f"invalid Saudi ADM1 properties: {properties}")
        if region_id in region_ids:
            raise ValueError(f"duplicate region_id: {region_id}")
        region_ids.add(region_id)
        region_name_en, region_name_ar, headquarters_en, headquarters_ar = REGION_METADATA[
            region_id
        ]
        normalized.append(
            {
                "type": "Feature",
                "properties": {
                    "region_id": region_id,
                    "region_name_en": region_name_en,
                    "region_name_ar": region_name_ar,
                    "admin_level": "ADM1",
                    "country_iso3": "SAU",
                    "headquarters_en": headquarters_en,
                    "headquarters_ar": headquarters_ar,
                    "source_shape_id": properties["shapeID"],
                },
                "geometry": feature["geometry"],
            }
        )
    normalized.sort(key=lambda item: item["properties"]["region_id"])
    return {
        "type": "FeatureCollection",
        "name": "Saudi Arabia ADM1 project reference",
        "source_metadata": SOURCE_METADATA,
        "features": normalized,
    }


def write_outputs(data: dict[str, object], geojson_path: Path, registry_path: Path) -> None:
    """Write normalized geometry and a lightweight region registry."""
    geojson_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    geojson_path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with registry_path.open("w", encoding="utf-8", newline="") as stream:
        fieldnames = [
            "region_id",
            "region_name_en",
            "region_name_ar",
            "admin_level",
            "country_iso3",
            "headquarters_en",
            "headquarters_ar",
            "source_shape_id",
            "boundary_year_represented",
            "source_license",
            "name_source_url",
            "headquarters_source_url",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for feature in data["features"]:
            properties = feature["properties"]
            writer.writerow(
                {
                    **properties,
                    "boundary_year_represented": SOURCE_METADATA["boundary_year_represented"],
                    "source_license": SOURCE_METADATA["boundary_license"],
                    "name_source_url": NAME_SOURCE_URL,
                    "headquarters_source_url": HEADQUARTERS_SOURCE_URL,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--geojson-output",
        type=Path,
        default=Path("data/reference/saudi_adm1_geoboundaries_2017.geojson"),
    )
    parser.add_argument(
        "--registry-output",
        type=Path,
        default=Path("configs/region_registry.csv"),
    )
    args = parser.parse_args()
    write_outputs(normalize(args.source), args.geojson_output, args.registry_output)
    print(args.geojson_output)
    print(args.registry_output)


if __name__ == "__main__":
    main()
