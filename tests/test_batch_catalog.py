from pathlib import Path

import pytest

from saudi_warning.forecasting.run_batch import load_catalog, output_paths


def test_load_catalog_and_output_names(tmp_path: Path) -> None:
    catalog = tmp_path / "cases.csv"
    catalog.write_text(
        "case_id,initial_time,event_type\ncase_a,2020-08-20T00:00:00Z,heavy_rain\n",
        encoding="utf-8",
    )
    [case] = load_catalog(catalog)
    assert case.case_id == "case_a"
    assert output_paths(tmp_path, case.initial_time)[72].name == "mazu_like_20200820_00_lead072.nc"


def test_catalog_rejects_duplicate_case_id(tmp_path: Path) -> None:
    catalog = tmp_path / "cases.csv"
    catalog.write_text(
        "case_id,initial_time\ncase_a,2020-08-20T00:00:00Z\ncase_a,2020-08-21T00:00:00Z\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_catalog(catalog)
