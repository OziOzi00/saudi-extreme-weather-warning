"""Validate the cross-year heatwave v5 lock without reading forecast arrays."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _window(start: date, days: int) -> list[date]:
    return [start + timedelta(days=offset) for offset in range(days)]


def _has_two_consecutive(values: list[bool]) -> bool:
    return any(left and right for left, right in zip(values, values[1:], strict=False))


def _regional_thresholds(stats: pd.DataFrame, region_id: str) -> tuple[float, float]:
    row = stats[
        (stats["period"] == "JJA")
        & (stats["region_id"] == region_id)
        & (stats["indicator"] == "tmax_c")
    ]
    if len(row) != 1:
        raise ValueError(f"missing unique JJA tmax statistics for {region_id}")
    source = row.iloc[0]
    return (
        max(47.0, float(source["daily_spatial_p95_p50"])),
        max(49.0, float(source["daily_spatial_p95_p90"])),
    )


def validate_v5_lock(root: Path, check_forecast_absence: bool = True) -> list[str]:
    """Return lock violations while keeping all GraphCast forecast arrays sealed."""
    root = root.resolve()
    lock_path = root / "manifests/heatwave_v5_prospective_lock.json"
    lock: dict[str, Any] = json.loads(lock_path.read_text(encoding="utf-8"))
    candidate_path = root / lock["candidate_path"]
    selection_path = root / lock["selection_file"]
    batch_path = root / lock["batch_catalog"]
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    selection = _rows(selection_path)
    batch = _rows(batch_path)
    errors: list[str] = []

    if lock.get("status") != "locked_before_2018_graphcast_forecast_access":
        errors.append("v5 prospective lock status is invalid")
    for flag in (
        "forecast_artifacts_present_at_lock",
        "forecast_arrays_read_during_selection",
        "independent_heatwave_opened",
        "base_rule_modified",
    ):
        if lock.get(flag) is not False:
            errors.append(f"{flag} must be false")
    if candidate.get("status") != "preregistered_before_2018_forecast_access":
        errors.append("candidate was not preregistered before forecast access")
    if candidate.get("independent_heatwave_access") != "forbidden":
        errors.append("independent heatwave access must remain forbidden")
    if candidate["candidate"].get("permitted_methods") != ["lead_specific_median"]:
        errors.append("exactly one candidate method must be permitted")
    if candidate["candidate"].get("maximum_blending_forbidden") is not True:
        errors.append("maximum blending must remain forbidden")
    if candidate["candidate"].get("threshold_search_forbidden") is not True:
        errors.append("threshold search must remain forbidden")

    for name, item in lock.get("input_fingerprints", {}).items():
        path = root / item["path"]
        if not path.exists():
            errors.append(f"missing locked input: {name}")
            continue
        actual = _sha256(path)
        if actual != str(item["sha256"]).lower():
            errors.append(f"{name} SHA-256 mismatch: expected {item['sha256']}, got {actual}")

    selected_ids = {row["case_id"] for row in selection}
    if selected_ids != set(lock.get("selected_case_ids", [])):
        errors.append("selection diverges from locked case IDs")
    if selected_ids != {row["case_id"] for row in batch}:
        errors.append("batch catalog diverges from the locked selection")
    if len(selection) != 6 or len(selected_ids) != 6:
        errors.append("v5 requires exactly six unique prospective cases")
    roles = pd.Series([row["case_role"] for row in selection]).value_counts().to_dict()
    if roles != {"event": 3, "control": 3}:
        errors.append("v5 requires three events and three controls")

    daily_path = root / lock["input_fingerprints"]["ssod_daily_summary"]["path"]
    daily = _rows(daily_path)
    daily_index = {
        (row["region_id"], row["date"]): row
        for row in daily
        if row["variable"] == "tmax_c" and row["aggregation"] == "station_max"
    }
    stats_path = root / lock["input_fingerprints"]["mazu_2025_statistics"]["path"]
    stats = pd.read_csv(stats_path)
    selection_rules = candidate["selection_rules"]
    minimum_stations = int(selection_rules["minimum_station_count_per_day"])
    pair_rows: dict[str, list[dict[str, str]]] = {}

    for row in selection:
        pair_rows.setdefault(row["matched_pair_id"], []).append(row)
        if row["dataset_split"] != "development" or row["hazard"] != "heatwave":
            errors.append(f"{row['case_id']}: invalid split or hazard")
        if row["selection_source"] != "NOAA_SSOD_V2":
            errors.append(f"{row['case_id']}: selection source must be NOAA SSODv2")
        if row["selection_aggregation"] != "station_max":
            errors.append(f"{row['case_id']}: selection aggregation must be station_max")
        if row["forecast_access_status"] != "not_accessed_as_of_lock":
            errors.append(f"{row['case_id']}: forecast access was not sealed")
        initial = datetime.fromisoformat(row["initial_time"].replace("Z", "+00:00"))
        start = date.fromisoformat(row["target_start_date"])
        end = date.fromisoformat(row["target_end_date"])
        days = _window(start, int(selection_rules["utc_days_per_window"]))
        if initial.year != 2018 or initial.date() != start - timedelta(days=1):
            errors.append(f"{row['case_id']}: invalid 2018 initialization boundary")
        if days[-1] != end:
            errors.append(f"{row['case_id']}: target window must contain three UTC days")

        hot_threshold, severe_threshold = _regional_thresholds(stats, row["region_id"])
        if not np.isclose(float(row["regional_hot_threshold_degc"]), hot_threshold):
            errors.append(f"{row['case_id']}: hot threshold diverges from locked formula")
        if not np.isclose(float(row["regional_severe_threshold_degc"]), severe_threshold):
            errors.append(f"{row['case_id']}: severe threshold diverges from locked formula")

        observed: list[float] = []
        for day in days:
            item = daily_index.get((row["region_id"], day.isoformat()))
            if item is None:
                errors.append(f"{row['case_id']}: missing SSOD observation for {day}")
                continue
            if int(item["station_count"]) < minimum_stations:
                errors.append(f"{row['case_id']}: insufficient station coverage for {day}")
            observed.append(float(item["observed_value"]))
        declared = [float(value) for value in row["observed_values_degc"].split(";")]
        if observed != declared:
            errors.append(f"{row['case_id']}: declared observations diverge from SSOD")
        flags = [value.lower() == "true" for value in row["observed_hot_day_flags"].split(";")]
        calculated_flags = [value >= hot_threshold for value in observed]
        if flags != calculated_flags:
            errors.append(f"{row['case_id']}: observed hot-day flags are inconsistent")
        if row["case_role"] == "event" and not _has_two_consecutive(flags):
            errors.append(f"{row['case_id']}: event lacks two consecutive observed hot days")
        if row["case_role"] == "control" and (
            any(flags) or any(value > 45.0 for value in observed)
        ):
            errors.append(f"{row['case_id']}: control exceeds its locked ceiling")

    maximum_separation = int(
        selection_rules["maximum_event_control_start_separation_days"]
    )
    for pair_id, rows in pair_rows.items():
        if len(rows) != 2 or {row["case_role"] for row in rows} != {"event", "control"}:
            errors.append(f"{pair_id}: matched pair must contain one event and one control")
            continue
        if len({row["region_id"] for row in rows}) != 1:
            errors.append(f"{pair_id}: matched cases must use the same region")
        starts = [date.fromisoformat(row["target_start_date"]) for row in rows]
        if abs((starts[0] - starts[1]).days) > maximum_separation:
            errors.append(f"{pair_id}: matched cases are too far apart")
        first, second = sorted(rows, key=lambda item: item["target_start_date"])
        if date.fromisoformat(first["target_end_date"]) >= date.fromisoformat(
            second["target_start_date"]
        ):
            errors.append(f"{pair_id}: matched windows overlap")

    pairs_path = root / lock["input_fingerprints"]["calibration_pairs"]["path"]
    pairs = pd.read_csv(pairs_path)
    pairs["calibration_error_degc"] = (
        pairs["observed_tmax_degc"] - pairs["raw_forecast_tmax_degc"]
    )
    expected = pairs.groupby("lead_time_hours")["calibration_error_degc"].median()
    declared_corrections = candidate["candidate"]["corrections_degc"]
    for lead in (24, 48, 72):
        if not np.isclose(float(declared_corrections[lead]), float(expected.loc[lead])):
            errors.append(f"lead{lead:03d}: correction is not the locked all-case median")

    assessment_path = (
        root / lock["input_fingerprints"]["method_selection_assessment"]["path"]
    )
    assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    if assessment.get("selected_method_for_next_prospective_development") != (
        "lead_specific_median"
    ):
        errors.append("v4.1 did not select the locked v5 candidate method")
    if assessment.get("can_open_independent_heatwave") is not False:
        errors.append("prior assessment must keep the independent heatwave set closed")

    if check_forecast_absence:
        forecast_roots = (
            root / "data/raw/graphcast_2018",
            root / "data/processed/mazu_like",
            root / "handoff/mazu_like",
        )
        for directory in forecast_roots:
            if not directory.exists():
                continue
            for path in directory.rglob("*"):
                if path.is_file() and any(case_id in path.name for case_id in selected_ids):
                    errors.append(f"forecast artifact already exists before lock: {path}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--allow-post-lock-artifacts", action="store_true")
    args = parser.parse_args()
    errors = validate_v5_lock(
        args.root, check_forecast_absence=not args.allow_post_lock_artifacts
    )
    if errors:
        for error in errors:
            print(f"- {error}")
        raise SystemExit(f"heatwave v5 prospective lock failed with {len(errors)} errors")
    print("verified 3 observation-only events and 3 matched controls from 2018")
    print("independent heatwave remains unopened")
    if args.allow_post_lock_artifacts:
        print("post-lock forecast artifacts are allowed")
    else:
        print("no selected GraphCast forecast artifact exists")


if __name__ == "__main__":
    main()
