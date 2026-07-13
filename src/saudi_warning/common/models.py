"""Shared lightweight models for hand-offs between project members."""

from dataclasses import dataclass
from typing import Literal


Hazard = Literal["heavy_rain", "heatwave"]
RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ForecastCase:
    """Identity and time semantics of one forecast window."""

    case_id: str
    initial_time: str
    lead_time_hours: int
    valid_start_time: str
    valid_end_time: str


@dataclass(frozen=True)
class RiskResult:
    """Minimum region-level result passed from member B to member C."""

    case_id: str
    region: str
    hazard: Hazard
    lead_time_hours: int
    risk_level: RiskLevel
    risk_score: float
    triggered_conditions: list[str]
    missing_conditions: list[str]
    source_file: str
    rule_version: str
