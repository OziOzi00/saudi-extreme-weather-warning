import csv
import json
from pathlib import Path


def test_saudi_adm1_geojson_matches_region_registry() -> None:
    root = Path(__file__).resolve().parents[1]
    geojson = json.loads(
        (root / "data" / "reference" / "saudi_adm1_geoboundaries_2017.geojson").read_text(
            encoding="utf-8"
        )
    )
    with (root / "configs" / "region_registry.csv").open(encoding="utf-8", newline="") as stream:
        registry = list(csv.DictReader(stream))

    feature_ids = {feature["properties"]["region_id"] for feature in geojson["features"]}
    registry_ids = {row["region_id"] for row in registry}
    assert len(feature_ids) == 13
    assert feature_ids == registry_ids
    assert all(row["admin_level"] == "ADM1" for row in registry)
