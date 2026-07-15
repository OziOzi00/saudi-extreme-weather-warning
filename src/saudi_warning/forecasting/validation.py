"""Contract and quality-control validation for MAZU-like v1 NetCDF files."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from saudi_warning.forecasting.indicator_converter import _window_steps


EXPECTED_INDICATORS: dict[str, dict[str, float | str]] = {
    "daily_precip_total": {"unit": "mm", "minimum": 0.0, "maximum": 1000.0},
    "t2m_c": {"unit": "degC", "minimum": -80.0, "maximum": 70.0},
    "tmax_c": {"unit": "degC", "minimum": -80.0, "maximum": 70.0},
    "tmin_c": {"unit": "degC", "minimum": -80.0, "maximum": 70.0},
    "wind10_speed": {"unit": "m s-1", "minimum": 0.0, "maximum": 150.0},
    "pwat": {"unit": "kg m-2", "minimum": 0.0, "maximum": 100.0},
    "ivt": {"unit": "kg m-1 s-1", "minimum": 0.0, "maximum": 2000.0},
    "wind850_speed": {"unit": "m s-1", "minimum": 0.0, "maximum": 150.0},
    "wind_shear_850_200": {
        "unit": "m s-1",
        "minimum": 0.0,
        "maximum": 150.0,
    },
    "omega500": {"unit": "Pa s-1", "minimum": -20.0, "maximum": 20.0},
    "geopotential_height500": {
        "unit": "gpm",
        "minimum": 4000.0,
        "maximum": 6500.0,
    },
}

REQUIRED_GLOBAL_ATTRIBUTES = {
    "forecast_model",
    "initial_time",
    "lead_time_hours",
    "valid_start_time",
    "valid_end_time",
    "source_resolution",
    "indicator_version",
    "window_steps",
}

FILENAME_PATTERN = re.compile(
    r"^mazu_like_(?P<date>\d{8})_(?P<hour>\d{2})_lead(?P<lead>024|048|072)\.nc$"
)


@dataclass
class NetCDFValidationReport:
    """Serializable result of one file validation."""

    path: str
    valid: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    indicators: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc(value: Any, field_name: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        errors.append(f"{field_name}: expected UTC ISO-8601 ending in Z")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field_name}: invalid timestamp")
        return None
    return parsed.astimezone(timezone.utc)


def _check_coordinate(
    dataset: xr.Dataset,
    name: str,
    minimum: float,
    maximum: float,
    errors: list[str],
) -> None:
    if name not in dataset.coords:
        errors.append(f"missing coordinate: {name}")
        return
    values = np.asarray(dataset[name].values, dtype=float)
    if values.ndim != 1 or values.size < 2 or not np.isfinite(values).all():
        errors.append(f"{name}: expected a finite one-dimensional coordinate")
        return
    differences = np.diff(values)
    if not (np.all(differences > 0) or np.all(differences < 0)):
        errors.append(f"{name}: coordinate must be strictly monotonic")
    if float(values.min()) < minimum or float(values.max()) > maximum:
        errors.append(f"{name}: outside Saudi context bounds [{minimum}, {maximum}]")
    if not np.allclose(np.abs(differences), 0.25, atol=1e-6):
        errors.append(f"{name}: expected regular 0.25 degree spacing")


def validate_mazu_like_file(
    path: Path,
    expected_initial_time: str | None = None,
    expected_lead: int | None = None,
    check_filename: bool = True,
) -> NetCDFValidationReport:
    """Validate contract, time semantics, units, finite coverage, and broad ranges."""
    report = NetCDFValidationReport(path=path.as_posix())
    filename_match = FILENAME_PATTERN.fullmatch(path.name) if check_filename else None
    if check_filename and filename_match is None:
        report.errors.append("filename: does not match MAZU-like v1 convention")
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        report.errors.append("file: missing, not a regular file, or empty")
        return report
    try:
        with xr.open_dataset(path, engine="scipy") as opened:
            dataset = opened.load()
    except Exception as error:
        report.errors.append(f"file: unreadable NetCDF ({type(error).__name__}: {error})")
        return report

    missing_attrs = sorted(REQUIRED_GLOBAL_ATTRIBUTES - set(dataset.attrs))
    if missing_attrs:
        report.errors.append(f"global attributes missing: {', '.join(missing_attrs)}")
    lead_raw = dataset.attrs.get("lead_time_hours")
    try:
        lead = int(lead_raw)
    except (TypeError, ValueError):
        lead = None
        report.errors.append("lead_time_hours: expected integer")
    if lead not in {24, 48, 72}:
        report.errors.append("lead_time_hours: expected 24, 48, or 72")
    if expected_lead is not None and lead != expected_lead:
        report.errors.append(f"lead_time_hours: expected {expected_lead}, found {lead}")
    if filename_match is not None and lead is not None:
        if int(filename_match.group("lead")) != lead:
            report.errors.append("filename lead is inconsistent with lead_time_hours")

    initial = _utc(dataset.attrs.get("initial_time"), "initial_time", report.errors)
    valid_start = _utc(
        dataset.attrs.get("valid_start_time"), "valid_start_time", report.errors
    )
    valid_end = _utc(dataset.attrs.get("valid_end_time"), "valid_end_time", report.errors)
    if expected_initial_time is not None:
        expected_initial = _utc(expected_initial_time, "expected_initial_time", report.errors)
        if initial is not None and expected_initial is not None and initial != expected_initial:
            report.errors.append("initial_time: does not match catalog")
    if initial is not None and filename_match is not None:
        filename_stamp = f"{filename_match.group('date')}_{filename_match.group('hour')}"
        if initial.strftime("%Y%m%d_%H") != filename_stamp:
            report.errors.append("filename timestamp is inconsistent with initial_time")
    if valid_start is not None and valid_end is not None:
        if valid_end - valid_start != timedelta(hours=24):
            report.errors.append("valid window: expected exactly 24 hours")
    if initial is not None and valid_end is not None and lead in {24, 48, 72}:
        if valid_end != initial + timedelta(hours=lead):
            report.errors.append("valid_end_time: inconsistent with initial_time and lead")
    if lead in {24, 48, 72}:
        expected_steps = ",".join(_window_steps(lead))
        if dataset.attrs.get("window_steps") != expected_steps:
            report.errors.append(f"window_steps: expected {expected_steps}")

    expected_attrs = {
        "forecast_model": "GraphCast",
        "source_resolution": "0.25 degree",
        "indicator_version": "mazu_like_v1",
    }
    for name, expected in expected_attrs.items():
        if dataset.attrs.get(name) != expected:
            report.errors.append(f"{name}: expected {expected!r}")
    _check_coordinate(dataset, "latitude", 15.0, 33.0, report.errors)
    _check_coordinate(dataset, "longitude", 33.0, 57.0, report.errors)

    missing_variables = sorted(set(EXPECTED_INDICATORS) - set(dataset.data_vars))
    if missing_variables:
        report.errors.append(f"indicators missing: {', '.join(missing_variables)}")
    for name, expected in EXPECTED_INDICATORS.items():
        if name not in dataset:
            continue
        variable = dataset[name]
        if set(variable.dims) != {"latitude", "longitude"} or variable.ndim != 2:
            report.errors.append(f"{name}: expected latitude x longitude dimensions")
        unit = str(variable.attrs.get("units", ""))
        if unit != expected["unit"]:
            report.errors.append(f"{name}: expected unit {expected['unit']!r}, found {unit!r}")
        values = np.asarray(variable.values, dtype=float)
        finite = np.isfinite(values)
        finite_count = int(finite.sum())
        total_count = int(values.size)
        facts: dict[str, Any] = {
            "unit": unit,
            "finite_count": finite_count,
            "total_count": total_count,
            "missing_fraction": 1.0 - finite_count / total_count,
            "minimum": None,
            "maximum": None,
            "out_of_range_count": 0,
        }
        if finite_count == 0:
            report.errors.append(f"{name}: contains no finite values")
        else:
            finite_values = values[finite]
            lower = float(expected["minimum"])
            upper = float(expected["maximum"])
            out_of_range = int(((finite_values < lower) | (finite_values > upper)).sum())
            facts.update(
                minimum=float(finite_values.min()),
                maximum=float(finite_values.max()),
                out_of_range_count=out_of_range,
            )
            if out_of_range:
                report.errors.append(
                    f"{name}: {out_of_range} values outside broad range [{lower}, {upper}]"
                )
            if finite_count < total_count:
                report.warnings.append(
                    f"{name}: {total_count - finite_count} non-finite cells present"
                )
        report.indicators[name] = facts

    if all(name in dataset for name in ("tmin_c", "t2m_c", "tmax_c")):
        tmin = np.asarray(dataset["tmin_c"].values, dtype=float)
        tmean = np.asarray(dataset["t2m_c"].values, dtype=float)
        tmax = np.asarray(dataset["tmax_c"].values, dtype=float)
        comparable = np.isfinite(tmin) & np.isfinite(tmean) & np.isfinite(tmax)
        violations = int(((tmin > tmean) | (tmean > tmax))[comparable].sum())
        if violations:
            report.errors.append(
                f"temperature ordering: {violations} cells violate Tmin <= Tmean <= Tmax"
            )

    report.metadata = {
        "file_size_bytes": path.stat().st_size,
        "initial_time": dataset.attrs.get("initial_time"),
        "lead_time_hours": lead,
        "valid_start_time": dataset.attrs.get("valid_start_time"),
        "valid_end_time": dataset.attrs.get("valid_end_time"),
        "forecast_model": dataset.attrs.get("forecast_model"),
        "source_resolution": dataset.attrs.get("source_resolution"),
        "indicator_version": dataset.attrs.get("indicator_version"),
        "latitude_count": int(dataset.sizes.get("latitude", 0)),
        "longitude_count": int(dataset.sizes.get("longitude", 0)),
    }
    report.valid = not report.errors
    return report


def validate_mazu_like_sequence(paths: list[Path]) -> list[str]:
    """Validate that one case has exactly three aligned, contiguous lead windows."""
    reports = [validate_mazu_like_file(path) for path in paths]
    errors = [f"{report.path}: {error}" for report in reports for error in report.errors]
    if errors:
        return errors
    by_lead = {int(report.metadata["lead_time_hours"]): report for report in reports}
    if set(by_lead) != {24, 48, 72} or len(reports) != 3:
        return ["sequence: expected exactly one file for each lead 24, 48, and 72"]
    initial_times = {report.metadata["initial_time"] for report in reports}
    if len(initial_times) != 1:
        errors.append("sequence: initial_time differs across lead files")
    for previous, current in ((24, 48), (48, 72)):
        if by_lead[previous].metadata["valid_end_time"] != by_lead[current].metadata[
            "valid_start_time"
        ]:
            errors.append(f"sequence: lead{previous:03d} and lead{current:03d} are not contiguous")
    coordinate_shapes = {
        (report.metadata["latitude_count"], report.metadata["longitude_count"])
        for report in reports
    }
    if len(coordinate_shapes) != 1:
        errors.append("sequence: coordinate shapes differ across lead files")
    return errors
