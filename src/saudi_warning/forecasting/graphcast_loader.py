"""GraphCast case loader interface (member A)."""

from collections.abc import Sequence


def requested_lead_steps(max_lead_hours: int = 72) -> list[str]:
    """Return six-hour GraphCast lead steps required by a v1 forecast window."""
    if max_lead_hours not in {24, 48, 72}:
        raise ValueError("max_lead_hours must be one of 24, 48, or 72")
    return [f"{hour}h" for hour in range(6, max_lead_hours + 1, 6)]


def required_variables() -> Sequence[str]:
    """Return the minimal GraphCast variable contract for MAZU-like v1."""
    return (
        "total_precipitation_6hr",
        "2m_temperature",
        "10m_u_component_of_wind",
        "10m_v_component_of_wind",
        "specific_humidity",
        "u_component_of_wind",
        "v_component_of_wind",
        "vertical_velocity",
        "geopotential",
    )
