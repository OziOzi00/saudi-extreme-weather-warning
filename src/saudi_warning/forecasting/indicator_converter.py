"""MAZU-like conversion entry points (member A implementation pending)."""


def ensure_supported_lead(lead_time_hours: int) -> None:
    """Validate the only lead windows supported by v1."""
    if lead_time_hours not in {24, 48, 72}:
        raise ValueError("v1 supports 24, 48, and 72 hour windows only")
