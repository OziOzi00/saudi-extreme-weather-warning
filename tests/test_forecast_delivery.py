"""Test member A validation, preflight, cache, and provenance delivery controls."""

import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from saudi_warning.forecasting.delivery import build_delivery_rows, sha256_file
from saudi_warning.forecasting.graphcast_loader import cache_file_is_valid, required_variables
from saudi_warning.forecasting.preflight_catalog import preflight_rows
from saudi_warning.forecasting.run_batch import CaseRecord, load_catalog, process_case
from saudi_warning.forecasting.validation import (
    EXPECTED_INDICATORS,
    validate_mazu_like_file,
    validate_mazu_like_sequence,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = ROOT / "examples" / "data"


def _catalog(path: Path) -> Path:
    path.write_text(
        "case_id,initial_time,event_type\n"
        "20200820_00,2020-08-20T00:00:00Z,demo\n",
        encoding="utf-8",
    )
    return path


def test_versioned_example_files_pass_file_and_sequence_validation() -> None:
    paths = sorted(EXAMPLE_DIR.glob("mazu_like_*.nc"))
    assert len(paths) == 3
    assert all(validate_mazu_like_file(path).valid for path in paths)
    assert validate_mazu_like_sequence(paths) == []


def test_validator_reports_missing_indicator_bad_unit_and_range(tmp_path: Path) -> None:
    source = EXAMPLE_DIR / "mazu_like_20200820_00_lead024.nc"
    with xr.open_dataset(source, engine="scipy") as opened:
        dataset = opened.load().drop_vars("ivt")
    dataset["daily_precip_total"].attrs["units"] = "m"
    dataset["geopotential_height500"][:] = 9999.0
    target = tmp_path / source.name
    dataset.to_netcdf(target, engine="scipy")
    report = validate_mazu_like_file(target)
    assert not report.valid
    assert any("indicators missing: ivt" in error for error in report.errors)
    assert any("daily_precip_total: expected unit" in error for error in report.errors)
    assert any("geopotential_height500" in error and "outside" in error for error in report.errors)


@pytest.mark.parametrize(
    "rows,match",
    [
        (
            "a,2020-08-20T00:00:00Z\nb,2020-08-20T00:00:00Z\n",
            "duplicate initial_time",
        ),
        ("a,2020-08-20T06:00:00Z\n", "00 or 12 UTC"),
        ("a,2020-08-20T00:00:00+03:00\n", "ending in Z"),
        ("a,2021-08-20T00:00:00Z\n", "2020 replay year"),
    ],
)
def test_catalog_preflight_rejects_output_collisions_and_invalid_cycles(
    tmp_path: Path, rows: str, match: str
) -> None:
    catalog = tmp_path / "cases.csv"
    catalog.write_text("case_id,initial_time\n" + rows, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_catalog(catalog)


def test_preflight_and_process_case_skip_only_valid_existing_outputs(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path / "cases.csv")
    rows = preflight_rows(catalog, EXAMPLE_DIR, tmp_path / "empty_cache")
    assert rows[0]["ready_for_b"] == "yes"
    assert rows[0]["valid_output_count"] == "3"
    assert len(rows[0]["missing_cache_steps"].split(";")) == 12
    status, _, message = process_case(
        CaseRecord("20200820_00", "2020-08-20T00:00:00Z"),
        tmp_path / "empty_cache",
        EXAMPLE_DIR,
        retries=1,
        timeout_seconds=1,
    )
    assert status == "skipped"
    assert "passed validation" in message


def test_process_case_repairs_only_invalid_lead_via_validated_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    for source in EXAMPLE_DIR.glob("*.nc"):
        shutil.copy2(source, output_dir / source.name)
    lead024 = output_dir / "mazu_like_20200820_00_lead024.nc"
    lead048 = output_dir / "mazu_like_20200820_00_lead048.nc"
    original_024_hash = sha256_file(lead024)
    lead048.write_bytes(b"interrupted write")

    monkeypatch.setattr(
        "saudi_warning.forecasting.run_batch.cache_missing_steps",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "saudi_warning.forecasting.run_batch.load_case_with_cache",
        lambda *args, **kwargs: object(),
    )

    def fake_convert(case: object, initial_time: str, lead: int) -> xr.Dataset:
        source = EXAMPLE_DIR / f"mazu_like_20200820_00_lead{lead:03d}.nc"
        with xr.open_dataset(source, engine="scipy") as opened:
            return opened.load()

    monkeypatch.setattr("saudi_warning.forecasting.run_batch.convert_window", fake_convert)
    status, paths, message = process_case(
        CaseRecord("20200820_00", "2020-08-20T00:00:00Z"),
        tmp_path / "cache",
        output_dir,
        retries=1,
        timeout_seconds=1,
    )
    assert status == "completed"
    assert "lead048" in message
    assert sha256_file(lead024) == original_024_hash
    assert validate_mazu_like_file(paths[48]).valid
    assert not list(output_dir.glob("*.partial"))


def test_delivery_manifest_rows_include_hashes_and_validation(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path / "cases.csv")
    rows = build_delivery_rows(
        catalog,
        EXAMPLE_DIR,
        ROOT,
        validated_at_utc="2026-07-15T00:00:00Z",
    )
    assert len(rows) == 3
    assert all(row["validation_status"] == "passed" for row in rows)
    assert all(len(row["sha256"]) == 64 for row in rows)
    assert rows[0]["sha256"] == sha256_file(ROOT / rows[0]["source_file"])


def test_cache_validation_rejects_corruption_and_accepts_required_structure(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken.nc"
    broken.write_bytes(b"not a NetCDF")
    assert not cache_file_is_valid(broken)

    lat = [15.0, 15.25]
    lon = [33.0, 33.25]
    level = [1000, 925, 850, 700, 500, 300, 200]
    variables = {}
    for name in required_variables():
        if name in {
            "specific_humidity",
            "u_component_of_wind",
            "v_component_of_wind",
            "vertical_velocity",
            "geopotential",
        }:
            variables[name] = (("level", "lat", "lon"), np.ones((7, 2, 2)))
        else:
            variables[name] = (("lat", "lon"), np.ones((2, 2)))
    valid = tmp_path / "valid.nc"
    xr.Dataset(variables, coords={"level": level, "lat": lat, "lon": lon}).to_netcdf(
        valid, engine="scipy"
    )
    assert set(required_variables()) == set(variables)
    assert cache_file_is_valid(valid)


def test_expected_indicator_contract_stays_at_eleven_fields() -> None:
    assert len(EXPECTED_INDICATORS) == 11
