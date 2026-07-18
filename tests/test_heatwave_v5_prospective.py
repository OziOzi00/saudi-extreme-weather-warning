from pathlib import Path

from saudi_warning.verification.heatwave_v5_prospective import validate_v5_lock


ROOT = Path(__file__).resolve().parents[1]


def test_v5_cross_year_lock_is_internally_consistent() -> None:
    assert validate_v5_lock(ROOT, check_forecast_absence=False) == []


def test_v5_preforecast_lock_has_no_selected_artifacts() -> None:
    assert validate_v5_lock(ROOT, check_forecast_absence=True) == []
