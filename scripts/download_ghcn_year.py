"""Download one explicitly requested GHCN-Daily year and record its SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path

from saudi_warning.verification.observations import ghcn_year_url


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, output: Path) -> str:
    """Download atomically and return SHA-256, recovering empty failed outputs."""

    if output.exists() and output.stat().st_size > 0:
        raise SystemExit(f"refusing to overwrite existing file: {output}")
    if output.exists():
        output.unlink()
    partial = output.with_suffix(output.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    try:
        urllib.request.urlretrieve(url, partial)
        if partial.stat().st_size == 0:
            raise RuntimeError(f"download returned an empty file: {url}")
        partial.replace(output)
    finally:
        if partial.exists():
            partial.unlink()
    checksum = _sha256(output)
    (output.with_suffix(output.suffix + ".sha256")).write_text(
        f"{checksum}  {output.name}\n", encoding="ascii"
    )
    return checksum


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("year", type=int)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/external/ghcn_daily")
    )
    parser.add_argument(
        "--include-stations",
        action="store_true",
        help="also download the current official station inventory",
    )
    parser.add_argument(
        "--skip-year",
        action="store_true",
        help="skip the yearly archive; useful for recovering the station inventory",
    )
    args = parser.parse_args()
    url = ghcn_year_url(args.year)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_year:
        output = args.output_dir / f"{args.year}.csv.gz"
        checksum = _download(url, output)
        print(output)
        print(checksum)
    if args.include_stations:
        station_url = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
        station_output = args.output_dir / "ghcnd-stations.txt"
        station_checksum = _download(station_url, station_output)
        print(station_output)
        print(station_checksum)


if __name__ == "__main__":
    main()
