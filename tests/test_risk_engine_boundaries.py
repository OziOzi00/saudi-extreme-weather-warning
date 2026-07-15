"""Exercise candidate-rule thresholds, missing data, and forecast streaks."""

from pathlib import Path

from saudi_warning.risk.engine import evaluate_all, load_rule


ROOT = Path(__file__).resolve().parents[1]
CREATED_AT = "2026-07-15T00:00:00Z"


def _statistics() -> dict[tuple[str, str, str], dict[str, float]]:
    rows = {
        "daily_precip_total": {
            "daily_spatial_p95_p90": 5.0,
            "daily_spatial_p95_p95": 15.0,
        },
        "pwat": {"daily_region_mean_p90": 30.0},
        "ivt": {"daily_region_mean_p90": 200.0},
        "wind850_speed": {"daily_region_mean_p90": 10.0},
        "tmax_c": {
            "daily_spatial_p95_p90": 39.0,
            "daily_spatial_p95_p95": 42.0,
        },
        "tmin_c": {"daily_spatial_p95_p90": 27.0},
    }
    return {("JJA", "SA-01", indicator): values for indicator, values in rows.items()}


def _summary_rows(
    lead: int,
    precip: float | None = 0.0,
    omega: float | None = 0.1,
    tmax: float | None = 35.0,
    tmin: float | None = 25.0,
) -> list[dict[str, object]]:
    start_hour = lead - 24
    values = {
        "daily_precip_total": (precip, "mm"),
        "pwat": (20.0, "kg m-2"),
        "ivt": (100.0, "kg m-1 s-1"),
        "wind850_speed": (5.0, "m s-1"),
        "omega500": (omega, "Pa s-1"),
        "tmax_c": (tmax, "degC"),
        "tmin_c": (tmin, "degC"),
    }
    rows = []
    for indicator, (value, unit) in values.items():
        rows.append(
            {
                "source_file": f"handoff/mazu_like/mazu_like_20200820_00_lead{lead:03d}.nc",
                "initial_time": "2020-08-20T00:00:00Z",
                "lead_time_hours": lead,
                "valid_start_time": f"2020-08-{20 + start_hour // 24:02d}T00:00:00Z",
                "valid_end_time": f"2020-08-{20 + lead // 24:02d}T00:00:00Z",
                "region_id": "SA-01",
                "region_name_en": "Riyadh Region",
                "indicator": indicator,
                "unit": unit,
                "weighted_mean": value,
                "spatial_p95": value,
                "maximum": value,
            }
        )
    return rows


def _rules() -> tuple[dict, dict]:
    heavy = load_rule(ROOT / "configs" / "heavy_rain_rules_v1.yaml", "heavy_rain")
    heat = load_rule(ROOT / "configs" / "heatwave_rules_v1.yaml", "heatwave")
    return heavy, heat


def _result(results: list[dict], hazard: str, lead: int = 24) -> dict:
    return next(
        item
        for item in results
        if item["hazard"] == hazard and item["lead_time_hours"] == lead
    )


def test_heavy_rain_absolute_floor_and_high_support_gate() -> None:
    heavy, heat = _rules()
    medium = evaluate_all(_summary_rows(24, precip=10.0), _statistics(), heavy, heat, CREATED_AT)
    medium_result = _result(medium, "heavy_rain")
    assert medium_result["risk_level"] == "medium"
    assert medium_result["indicator_summary"]["precip_medium_threshold_mm"] == 10.0

    unsupported = evaluate_all(
        _summary_rows(24, precip=20.0, omega=0.1),
        _statistics(),
        heavy,
        heat,
        CREATED_AT,
    )
    assert _result(unsupported, "heavy_rain")["risk_level"] == "medium"

    supported = evaluate_all(
        _summary_rows(24, precip=20.0, omega=-0.1),
        _statistics(),
        heavy,
        heat,
        CREATED_AT,
    )
    assert _result(supported, "heavy_rain")["risk_level"] == "high"


def test_missing_primary_is_not_treated_as_zero_or_positive_risk() -> None:
    heavy, heat = _rules()
    rows = _summary_rows(24, precip=None)
    results = evaluate_all(rows, _statistics(), heavy, heat, CREATED_AT)
    rain = _result(results, "heavy_rain")
    assert rain["risk_level"] == "low"
    assert rain["confidence"] == "low"
    assert rain["missing_evidence"][0]["value"] is None


def test_three_contiguous_severe_hot_days_reach_high_only_on_day_three() -> None:
    heavy, heat = _rules()
    rows = []
    for lead in (24, 48, 72):
        rows.extend(_summary_rows(lead, tmax=45.0, tmin=30.0))
    results = evaluate_all(rows, _statistics(), heavy, heat, CREATED_AT)
    heat_results = [_result(results, "heatwave", lead) for lead in (24, 48, 72)]
    assert [item["indicator_summary"]["forecast_hot_day_duration"] for item in heat_results] == [
        1,
        2,
        3,
    ]
    assert [item["risk_level"] for item in heat_results] == ["medium", "medium", "high"]


def test_non_finite_supporting_value_is_reported_missing() -> None:
    heavy, heat = _rules()
    rows = _summary_rows(24, precip=10.0)
    ivt = next(row for row in rows if row["indicator"] == "ivt")
    ivt["weighted_mean"] = float("nan")
    results = evaluate_all(rows, _statistics(), heavy, heat, CREATED_AT)
    rain = _result(results, "heavy_rain")
    assert any(item["indicator"] == "ivt" for item in rain["missing_evidence"])
    assert rain["risk_level"] == "medium"
