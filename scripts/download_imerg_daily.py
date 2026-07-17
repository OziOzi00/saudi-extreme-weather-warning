"""Plan or download IMERG Final Run daily GIS files for rainfall candidates."""

from __future__ import annotations

import argparse
import base64
import csv
import getpass
import hashlib
import os
import re
import time
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import yaml


PPS_ROOT = "https://arthurhouhttps.pps.eosdis.nasa.gov/gpmdata"
PLAN_FIELDS = [
    "date",
    "case_ids",
    "case_roles",
    "dataset_splits",
    "directory_url",
    "product",
    "version",
    "status",
]


class _LinksParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href.rsplit("/", 1)[-1])


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def read_cases(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def build_plan(cases: list[dict[str, str]], version: str = "V07B") -> list[dict[str, str]]:
    """Expand heavy-rain event/control windows into deduplicated UTC calendar dates."""

    by_date: dict[date, list[dict[str, str]]] = defaultdict(list)
    for case in cases:
        if case["hazard"] != "heavy_rain" or case["case_role"] not in {"event", "control"}:
            continue
        for day in _date_range(
            _parse_date(case["event_start_time"]),
            _parse_date(case["event_end_time"]),
        ):
            by_date[day].append(case)

    rows = []
    for day, matching_cases in sorted(by_date.items()):
        day_text = day.isoformat()
        directory = f"{PPS_ROOT}/{day:%Y/%m/%d}/gis/"
        rows.append(
            {
                "date": day_text,
                "case_ids": ";".join(sorted({item["case_id"] for item in matching_cases})),
                "case_roles": ";".join(
                    sorted({item["case_role"] for item in matching_cases})
                ),
                "dataset_splits": ";".join(
                    sorted({item["dataset_split"] for item in matching_cases})
                ),
                "directory_url": directory,
                "product": "IMERG Final Run daily GIS accumulation",
                "version": version,
                "status": "planned_requires_pps_registration",
            }
        )
    if not rows:
        raise ValueError("catalog contains no heavy-rain event/control windows")
    return rows


def build_gap_plan(
    cases: list[dict[str, str]],
    coverage_rows: list[dict[str, str]],
    version: str = "V07B",
    allowed_split: str = "development",
) -> list[dict[str, str]]:
    """Build a deduplicated download plan from missing IMERG pairing rows."""

    case_lookup = {row["case_id"]: row for row in cases}
    by_date: dict[str, set[str]] = defaultdict(set)
    for row in coverage_rows:
        if row["observation_source"] != "IMERG" or row["pair_status"] != "missing":
            continue
        case_id = row["case_id"]
        if case_id not in case_lookup:
            raise ValueError(f"coverage gap references unknown case: {case_id}")
        if case_lookup[case_id]["dataset_split"] != allowed_split:
            raise ValueError(f"gap plan may only expose {allowed_split} cases")
        day = row["valid_start_time"][:10]
        date.fromisoformat(day)
        by_date[day].add(case_id)
    rows = []
    for day, case_ids in sorted(by_date.items()):
        matching_cases = [case_lookup[case_id] for case_id in sorted(case_ids)]
        parsed = date.fromisoformat(day)
        rows.append(
            {
                "date": day,
                "case_ids": ";".join(sorted(case_ids)),
                "case_roles": ";".join(
                    sorted({item["case_role"] for item in matching_cases})
                ),
                "dataset_splits": ";".join(
                    sorted({item["dataset_split"] for item in matching_cases})
                ),
                "directory_url": f"{PPS_ROOT}/{parsed:%Y/%m/%d}/gis/",
                "product": "IMERG Final Run daily GIS accumulation",
                "version": version,
                "status": (
                    "planned_development_pairing_gap"
                    if allowed_split == "development"
                    else "planned_independent_after_rule_freeze"
                ),
            }
        )
    if not rows:
        raise ValueError("coverage audit contains no missing IMERG development rows")
    return rows


def write_plan(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PLAN_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def find_daily_zip(html: str, day: str, version: str) -> str:
    """Find the exact Final Run daily GIS archive in an authenticated listing."""

    parser = _LinksParser()
    parser.feed(html)
    compact_date = day.replace("-", "")
    pattern = re.compile(
        rf"^3B-DAY-GIS\.MS\.MRG\.3IMERG\.{compact_date}"
        rf"-S000000-E235959\.\d{{4}}\.{re.escape(version)}\.zip$"
    )
    matches = sorted({link for link in parser.links if pattern.fullmatch(link)})
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one {version} daily GIS archive for {day}, found {matches}"
        )
    return matches[0]


def _authorization_header(email: str, password: str) -> str:
    encoded = base64.b64encode(f"{email}:{password}".encode()).decode("ascii")
    return f"Basic {encoded}"


def _request(url: str, authorization: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"Authorization": authorization})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not any(name.lower().endswith(".tif") for name in names):
            raise RuntimeError(f"archive lacks a GeoTIFF member: {path}")
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"corrupt member {bad_member!r} in {path}")


def _download_with_retries(
    source_url: str,
    target: Path,
    authorization: str,
    attempts: int = 3,
) -> None:
    partial = target.with_suffix(target.suffix + ".partial")
    for attempt in range(1, attempts + 1):
        if partial.exists():
            partial.unlink()
        try:
            with urllib.request.urlopen(_request(source_url, authorization)) as response:
                with partial.open("wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
            _validate_zip(partial)
            partial.replace(target)
            return
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            if partial.exists():
                partial.unlink()
            if attempt == attempts:
                raise RuntimeError(
                    f"download failed after {attempts} attempts: {source_url}"
                ) from exc
            delay = 2**attempt
            print(f"retry {attempt}/{attempts - 1} after invalid response; wait={delay}s")
            time.sleep(delay)


def download(
    rows: list[dict[str, str]],
    output_dir: Path,
    manifest_path: Path,
    email: str,
    password: str,
) -> None:
    """Resolve authenticated listings and atomically download the planned archives."""

    authorization = _authorization_header(email, password)
    manifest_rows = []
    for row in rows:
        directory_url = row["directory_url"]
        with urllib.request.urlopen(_request(directory_url, authorization)) as response:
            listing = response.read().decode("utf-8", errors="replace")
        filename = find_daily_zip(listing, row["date"], row["version"])
        source_url = directory_url + filename
        day = date.fromisoformat(row["date"])
        target = output_dir / f"{day:%Y/%m/%d}" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            _validate_zip(target)
            status = "existing_verified"
        else:
            _download_with_retries(source_url, target, authorization)
            status = "downloaded_verified"
        manifest_rows.append(
            {
                **row,
                "source_url": source_url,
                "local_path": target.as_posix(),
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
                "download_status": status,
            }
        )
        print(f"{row['date']}: {status} {target}")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fields = PLAN_FIELDS + ["source_url", "local_path", "bytes", "sha256", "download_status"]
    with manifest_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path("configs/case_catalog_candidates.csv")
    )
    parser.add_argument(
        "--plan", type=Path, default=Path("configs/imerg_daily_download_plan.csv")
    )
    parser.add_argument("--version", default="V07B")
    parser.add_argument(
        "--coverage-gaps",
        type=Path,
        help="build the plan only from missing IMERG rows in a pairing coverage audit",
    )
    parser.add_argument(
        "--allowed-split",
        choices=["development", "independent_test"],
        default="development",
        help="defaults to development; independent_test also requires --frozen-rule",
    )
    parser.add_argument(
        "--frozen-rule",
        type=Path,
        help="required authorization evidence when planning independent_test downloads",
    )
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--prompt-email",
        action="store_true",
        help="securely prompt for PPS email instead of reading PPS_EMAIL",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/external/imerg_final_v07b")
    )
    parser.add_argument(
        "--manifest", type=Path, default=Path("outputs/imerg_download_manifest.csv")
    )
    args = parser.parse_args()

    if args.allowed_split == "independent_test":
        if args.frozen_rule is None:
            raise SystemExit("--frozen-rule is required for independent_test planning")
        rule = yaml.safe_load(args.frozen_rule.read_text(encoding="utf-8"))
        if rule.get("hazard") != "heavy_rain" or rule.get("status") != "frozen":
            raise SystemExit("independent_test planning requires a frozen heavy-rain rule")

    cases = read_cases(args.catalog)
    rows = (
        build_gap_plan(
            cases,
            read_cases(args.coverage_gaps),
            args.version,
            allowed_split=args.allowed_split,
        )
        if args.coverage_gaps
        else build_plan(cases, args.version)
    )
    write_plan(rows, args.plan)
    print(f"wrote {args.plan}: {len(rows)} UTC days")
    if not args.download:
        print("plan only; pass --download after PPS registration")
        return
    email = (
        getpass.getpass("NASA PPS email (input hidden): ").strip().lower()
        if args.prompt_email
        else os.environ.get("PPS_EMAIL", "").strip().lower()
    )
    password = os.environ.get("PPS_PASSWORD", "").strip() or email
    if not email:
        raise SystemExit("PPS_EMAIL is required for --download; do not commit credentials")
    download(rows, args.output_dir, args.manifest, email, password)


if __name__ == "__main__":
    main()
