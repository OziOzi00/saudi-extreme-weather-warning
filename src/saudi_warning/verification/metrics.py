"""Continuous, categorical, and heatwave-sequence verification metrics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


PAIR_COLUMNS = {
    "case_id",
    "initial_time",
    "lead_time_hours",
    "valid_start_time",
    "valid_end_time",
    "region_id",
    "variable",
    "aggregation",
    "forecast_value",
    "observed_value",
    "unit",
    "event_threshold",
    "observation_source",
    "observation_id",
    "coverage_fraction",
    "station_count",
    "qc_status",
}


def validate_pairs(frame: pd.DataFrame) -> list[str]:
    """Return contract errors without silently dropping malformed rows."""
    errors: list[str] = []
    missing = sorted(PAIR_COLUMNS - set(frame.columns))
    if missing:
        return [f"missing columns: {', '.join(missing)}"]
    if not frame["lead_time_hours"].isin([24, 48, 72]).all():
        errors.append("lead_time_hours must contain only 24, 48, or 72")
    if not frame["variable"].isin(["daily_precip_total", "tmax_c", "tmin_c"]).all():
        errors.append("variable contains an unsupported value")
    if not frame["qc_status"].isin(["accepted", "provisional", "rejected"]).all():
        errors.append("qc_status contains an unsupported value")
    expected_units = {"daily_precip_total": "mm", "tmax_c": "degC", "tmin_c": "degC"}
    wrong_unit = frame.apply(
        lambda row: expected_units.get(row["variable"]) != row["unit"], axis=1
    )
    if wrong_unit.any():
        errors.append("unit is inconsistent with variable")
    timestamps = {
        column: pd.to_datetime(frame[column], utc=True, errors="coerce")
        for column in ("initial_time", "valid_start_time", "valid_end_time")
    }
    if any(values.isna().any() for values in timestamps.values()):
        errors.append("time fields must be valid ISO-8601 timestamps")
    else:
        duration = timestamps["valid_end_time"] - timestamps["valid_start_time"]
        if not (duration == pd.Timedelta(hours=24)).all():
            errors.append("every valid window must be exactly 24 hours")
        expected_end = timestamps["initial_time"] + pd.to_timedelta(
            frame["lead_time_hours"], unit="h"
        )
        if not (timestamps["valid_end_time"] == expected_end).all():
            errors.append("valid_end_time is inconsistent with initial_time and lead")
    for column in ("forecast_value", "observed_value"):
        numeric = pd.to_numeric(frame[column], errors="coerce")
        accepted = frame["qc_status"] == "accepted"
        if not np.isfinite(numeric[accepted]).all():
            errors.append(f"{column} must be finite for accepted rows")
    coverage = pd.to_numeric(frame["coverage_fraction"], errors="coerce")
    if not np.isfinite(coverage).all() or ((coverage < 0) | (coverage > 1)).any():
        errors.append("coverage_fraction must be between 0 and 1")
    imerg = frame["observation_source"] == "IMERG"
    if (imerg & (frame["variable"] != "daily_precip_total")).any():
        errors.append("IMERG pairs may only verify daily_precip_total")
    if (imerg & ~frame["aggregation"].isin(["weighted_mean", "spatial_p95", "maximum"])).any():
        errors.append("IMERG pairs require a grid aggregation")
    ghcn = frame["observation_source"] == "GHCN_DAILY"
    if (ghcn & ~frame["aggregation"].isin(["station_mean", "station_max", "station_min"])).any():
        errors.append("GHCN pairs require a station aggregation")
    station_count = pd.to_numeric(frame["station_count"], errors="coerce")
    if (ghcn & ((station_count < 1) | ~np.isfinite(station_count))).any():
        errors.append("GHCN pairs require station_count >= 1")
    identities = [
        "case_id",
        "lead_time_hours",
        "region_id",
        "variable",
        "aggregation",
        "observation_id",
    ]
    if frame.duplicated(identities).any():
        errors.append("duplicate forecast-observation pair identity")
    return errors


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _metric_row(frame: pd.DataFrame, variable: str, aggregation: str, scope: str) -> dict[str, Any]:
    forecast = frame["forecast_value"].to_numpy(dtype=float)
    observed = frame["observed_value"].to_numpy(dtype=float)
    errors = forecast - observed
    row: dict[str, Any] = {
        "variable": variable,
        "aggregation": aggregation,
        "scope": scope,
        "pair_count": len(frame),
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "bias": float(np.mean(errors)),
        "unit": str(frame["unit"].iloc[0]),
        "hits": None,
        "misses": None,
        "false_alarms": None,
        "correct_negatives": None,
        "pod": None,
        "far": None,
        "csi": None,
    }
    threshold_rows = frame[np.isfinite(frame["event_threshold"].to_numpy(dtype=float))]
    if threshold_rows.empty:
        return row
    forecast_event = threshold_rows["forecast_value"] >= threshold_rows["event_threshold"]
    observed_event = threshold_rows["observed_value"] >= threshold_rows["event_threshold"]
    hits = int((forecast_event & observed_event).sum())
    misses = int((~forecast_event & observed_event).sum())
    false_alarms = int((forecast_event & ~observed_event).sum())
    correct_negatives = int((~forecast_event & ~observed_event).sum())
    row.update(
        hits=hits,
        misses=misses,
        false_alarms=false_alarms,
        correct_negatives=correct_negatives,
        pod=_ratio(hits, hits + misses),
        far=_ratio(false_alarms, hits + false_alarms),
        csi=_ratio(hits, hits + misses + false_alarms),
    )
    return row


def compute_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """Compute metrics by lead and across all leads for accepted pairs."""
    errors = validate_pairs(frame)
    if errors:
        raise ValueError("; ".join(errors))
    accepted = frame[frame["qc_status"] == "accepted"].copy()
    accepted["forecast_value"] = pd.to_numeric(accepted["forecast_value"])
    accepted["observed_value"] = pd.to_numeric(accepted["observed_value"])
    accepted["event_threshold"] = pd.to_numeric(
        accepted["event_threshold"], errors="coerce"
    )
    rows: list[dict[str, Any]] = []
    for (variable, aggregation), group in accepted.groupby(["variable", "aggregation"]):
        if group["unit"].nunique() != 1:
            raise ValueError(f"mixed units for {variable}/{aggregation}")
        rows.append(_metric_row(group, variable, aggregation, "all_leads"))
        for lead, lead_group in group.groupby("lead_time_hours"):
            rows.append(_metric_row(lead_group, variable, aggregation, f"lead{int(lead):03d}"))
    return pd.DataFrame(rows)


def _longest_run(flags: list[bool]) -> int:
    longest = 0
    current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return longest


def _onset_index(flags: list[bool], minimum_duration: int) -> int | None:
    for index in range(len(flags) - minimum_duration + 1):
        if all(flags[index : index + minimum_duration]):
            return index
    return None


def compute_heatwave_sequences(
    frame: pd.DataFrame, minimum_duration: int = 2
) -> pd.DataFrame:
    """Compare forecast and observed hot-day onset/duration within available leads."""
    errors = validate_pairs(frame)
    if errors:
        raise ValueError("; ".join(errors))
    accepted = frame[
        (frame["qc_status"] == "accepted") & (frame["variable"] == "tmax_c")
    ].copy()
    accepted["event_threshold"] = pd.to_numeric(
        accepted["event_threshold"], errors="coerce"
    )
    accepted["forecast_value"] = pd.to_numeric(accepted["forecast_value"])
    accepted["observed_value"] = pd.to_numeric(accepted["observed_value"])
    accepted = accepted[np.isfinite(accepted["event_threshold"])]
    rows: list[dict[str, Any]] = []
    keys = ["case_id", "initial_time", "region_id", "aggregation"]
    for key, group in accepted.groupby(keys):
        group = group.sort_values("lead_time_hours")
        forecast_flags = (group["forecast_value"] >= group["event_threshold"]).tolist()
        observed_flags = (group["observed_value"] >= group["event_threshold"]).tolist()
        forecast_onset = _onset_index(forecast_flags, minimum_duration)
        observed_onset = _onset_index(observed_flags, minimum_duration)
        leads = group["lead_time_hours"].astype(int).tolist()
        forecast_lead = None if forecast_onset is None else leads[forecast_onset]
        observed_lead = None if observed_onset is None else leads[observed_onset]
        rows.append(
            {
                "case_id": key[0],
                "initial_time": key[1],
                "region_id": key[2],
                "aggregation": key[3],
                "available_days": len(group),
                "minimum_duration": minimum_duration,
                "forecast_onset_lead_hours": forecast_lead,
                "observed_onset_lead_hours": observed_lead,
                "onset_error_days": (
                    None
                    if forecast_lead is None or observed_lead is None
                    else (forecast_lead - observed_lead) / 24
                ),
                "forecast_max_duration_days": _longest_run(forecast_flags),
                "observed_max_duration_days": _longest_run(observed_flags),
                "duration_error_days": _longest_run(forecast_flags)
                - _longest_run(observed_flags),
            }
        )
    return pd.DataFrame(rows)
