from saudi_warning.forecasting.graphcast_loader import requested_lead_steps
from saudi_warning.forecasting.indicator_converter import ensure_supported_lead


def test_72_hour_window_has_twelve_six_hour_steps() -> None:
    assert requested_lead_steps(72) == [f"{hour}h" for hour in range(6, 73, 6)]


def test_supported_leads_are_accepted() -> None:
    for lead in (24, 48, 72):
        ensure_supported_lead(lead)
