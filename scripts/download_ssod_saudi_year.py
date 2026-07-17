"""Download NOAA SSODv2 Saudi station-year CSV files with a SHA-256 manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


LIST_URL = "https://www.ncei.noaa.gov/oa/synoptic-summary-of-the-day"
OBJECT_ROOT = "https://www.ncei.noaa.gov/oa/synoptic-summary-of-the-day"
NAMESPACE = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def _prefix(year: int) -> str:
    return f"v2/access/by-year/{year}/csv/SSOD_SA"


def list_saudi_objects(year: int) -> list[dict[str, str]]:
    url = f"{LIST_URL}?list-type=2&prefix={urllib.parse.quote(_prefix(year), safe='')}"
    with urllib.request.urlopen(url, timeout=60) as response:
        root = ET.fromstring(response.read())
    if root.findtext("s3:IsTruncated", default="false", namespaces=NAMESPACE) == "true":
        raise RuntimeError("Saudi SSOD object listing unexpectedly requires pagination")
    rows = []
    for item in root.findall("s3:Contents", NAMESPACE):
        key = item.findtext("s3:Key", namespaces=NAMESPACE)
        if not key or not key.endswith(".csv"):
            continue
        rows.append(
            {
                "key": key,
                "last_modified": item.findtext(
                    "s3:LastModified", default="", namespaces=NAMESPACE
                ),
                "source_size_bytes": item.findtext(
                    "s3:Size", default="", namespaces=NAMESPACE
                ),
            }
        )
    if not rows:
        raise RuntimeError(f"no Saudi SSOD CSV objects found for {year}")
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, destination: Path, attempts: int = 4) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "saudi-warning/0.1"})
            with urllib.request.urlopen(request, timeout=90) as response:
                temporary.write_bytes(response.read())
            temporary.replace(destination)
            return
        except Exception:
            temporary.unlink(missing_ok=True)
            if attempt == attempts:
                raise
            time.sleep(attempt * 2)


def _inspect_csv(path: Path) -> dict[str, str | int]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "STATION",
            "Station_name",
            "DATE",
            "LATITUDE",
            "LONGITUDE",
            "max_temperature",
            "min_temperature",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"unexpected SSOD columns in {path}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"empty SSOD file: {path}")
    first = rows[0]
    return {
        "station_id": first["STATION"],
        "station_name": first["Station_name"],
        "latitude": first["LATITUDE"],
        "longitude": first["LONGITUDE"],
        "row_count": len(rows),
        "first_date": rows[0]["DATE"],
        "last_date": rows[-1]["DATE"],
    }


def run(year: int, output_dir: Path, manifest: Path) -> list[dict[str, str | int]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for item in list_saudi_objects(year):
        filename = Path(item["key"]).name
        destination = output_dir / filename
        url = f"{OBJECT_ROOT}/{item['key']}"
        expected_size = int(item["source_size_bytes"])
        if not destination.exists() or destination.stat().st_size != expected_size:
            _download(url, destination)
        if destination.stat().st_size != expected_size:
            raise ValueError(f"SSOD size mismatch: {destination}")
        details = _inspect_csv(destination)
        records.append(
            {
                **details,
                "year": year,
                "filename": filename,
                "size_bytes": destination.stat().st_size,
                "sha256": _sha256(destination),
                "source_url": url,
                "source_last_modified": item["last_modified"],
            }
        )
    manifest.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0])
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2020)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/external/ssod_v2/2020")
    )
    parser.add_argument(
        "--manifest", type=Path, default=Path("manifests/ssod_v2_saudi_2020_files.csv")
    )
    args = parser.parse_args()
    records = run(args.year, args.output_dir, args.manifest)
    print(f"downloaded/verified SSOD station files: {len(records)}")
    print(args.manifest)


if __name__ == "__main__":
    main()
