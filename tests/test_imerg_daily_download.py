import csv
from pathlib import Path

import pytest

from scripts.download_imerg_daily import (
    build_gap_plan,
    build_plan,
    find_daily_zip,
    read_cases,
)


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


def test_gap_plan_contains_only_missing_development_dates() -> None:
    cases = read_cases(ROOT / "configs" / "case_catalog_candidates.csv")
    coverage = [
        {
            "case_id": case_id,
            "observation_source": "IMERG",
            "pair_status": "missing",
            "valid_start_time": f"{day}T00:00:00Z",
        }
        for case_id, day in (
            ("20200501_00", "2020-05-03"),
            ("20200505_00", "2020-05-05"),
            ("20200505_00", "2020-05-07"),
            ("20200515_00", "2020-05-15"),
            ("20201109_00", "2020-11-09"),
            ("20201119_00", "2020-11-19"),
        )
    ]
    plan = build_gap_plan(cases, coverage)

    assert [row["date"] for row in plan] == [
        "2020-05-03",
        "2020-05-05",
        "2020-05-07",
        "2020-05-15",
        "2020-11-09",
        "2020-11-19",
    ]
    assert {row["dataset_splits"] for row in plan} == {"development"}
    assert {row["status"] for row in plan} == {
        "planned_development_pairing_gap"
    }
    assert not any("independent" in row["dataset_splits"] for row in plan)


def test_find_daily_zip_requires_exact_version_and_one_match() -> None:
    filename = (
        "3B-DAY-GIS.MS.MRG.3IMERG.20200726-"
        "S000000-E235959.3630.V07B.zip"
    )
    html = f'<a href="{filename}">{filename}</a>'
    assert find_daily_zip(html, "2020-07-26", "V07B") == filename
    with pytest.raises(RuntimeError, match="exactly one"):
        find_daily_zip(html, "2020-07-26", "V07A")


def test_independent_gap_plan_requires_explicit_partition() -> None:
    cases = read_cases(ROOT / "configs" / "case_catalog_candidates.csv")
    coverage = [
        {
            "case_id": "20200725_00",
            "observation_source": "IMERG",
            "pair_status": "missing",
            "valid_start_time": "2020-07-25T00:00:00Z",
        }
    ]

    with pytest.raises(ValueError, match="development"):
        build_gap_plan(cases, coverage)
    plan = build_gap_plan(cases, coverage, allowed_split="independent_test")
    assert plan[0]["dataset_splits"] == "independent_test"
    assert plan[0]["status"] == "planned_independent_after_rule_freeze"
