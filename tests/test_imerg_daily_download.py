import csv
from pathlib import Path

import pytest

from scripts.download_imerg_daily import build_plan, find_daily_zip, read_cases


ROOT = Path(__file__).resolve().parents[1]


def test_plan_contains_only_unique_heavy_rain_dates() -> None:
    rows = build_plan(read_cases(ROOT / "configs" / "case_catalog_candidates.csv"))
    assert len(rows) == 22
    assert len({row["date"] for row in rows}) == 22
    assert rows[0]["date"] == "2020-05-01"
    assert rows[-1]["date"] == "2020-11-26"
    assert all(row["version"] == "V07B" for row in rows)
    assert all("HEAT" not in row["case_ids"] for row in rows)


def test_versioned_plan_matches_catalog() -> None:
    expected = build_plan(read_cases(ROOT / "configs" / "case_catalog_candidates.csv"))
    with (ROOT / "configs" / "imerg_daily_download_plan.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        actual = list(csv.DictReader(stream))
    assert actual == expected


def test_find_daily_zip_requires_exact_version_and_one_match() -> None:
    filename = (
        "3B-DAY-GIS.MS.MRG.3IMERG.20200726-"
        "S000000-E235959.3630.V07B.zip"
    )
    html = f'<a href="{filename}">{filename}</a>'
    assert find_daily_zip(html, "2020-07-26", "V07B") == filename
    with pytest.raises(RuntimeError, match="exactly one"):
        find_daily_zip(html, "2020-07-26", "V07A")
