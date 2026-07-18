"""Validate the prospective heatwave v3 development lock before forecast access."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _window(start: date, days: int) -> list[date]:
    return [start + timedelta(days=offset) for offset in range(days)]


def validate_prospective_lock(root: Path, check_forecast_absence: bool = True) -> list[str]:
    """Return validation errors without reading any GraphCast forecast content."""
    root = root.resolve()
    lock_path = root / "manifests/heatwave_v3_prospective_lock.json"
    selection_path = root / "manifests/heatwave_v3_prospective_selection.csv"
    batch_path = root / "configs/heatwave_v3_prospective_batch_catalog.csv"
    candidate_path = root / "configs/heatwave_v3_prospective_candidate.yaml"
    daily_path = root / "manifests/ssod_v2_saudi_2020_daily_summary.csv"
    catalog_path = root / "configs/case_catalog_candidates.csv"

    lock: dict[str, Any] = json.loads(lock_path.read_text(encoding="utf-8"))
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    selection = _rows(selection_path)
    batch = _rows(batch_path)
    catalog = _rows(catalog_path)
    daily = _rows(daily_path)
    errors: list[str] = []

    if lock.get("status") != "locked_before_new_development_forecast_access":
        errors.append("prospective lock status is invalid")
    for flag in ("forecast_results_read_during_selection", "independent_heatwave_opened"):
        if lock.get(flag) is not False:
            errors.append(f"{flag} must be false")
    if lock.get("base_rule_modified") is not False:
        errors.append("base heatwave rule must remain unmodified")
    if candidate.get("scope") != "prospective_development_only":
        errors.append("candidate scope must be prospective_development_only")
    if candidate.get("independent_heatwave_access") != "forbidden":
        errors.append("candidate must forbid independent heatwave access")

    for name, item in lock.get("input_fingerprints", {}).items():
        path = root / item["path"]
        actual = _sha256(path)
        if actual != item["sha256"]:
            errors.append(f"{name} SHA-256 mismatch: expected {item['sha256']}, got {actual}")

    selected_ids = {row["case_id"] for row in selection}
    if selected_ids != set(lock.get("selected_case_ids", [])):
        errors.append("selection does not match locked case IDs")
    if selected_ids != {row["case_id"] for row in batch}:
        errors.append("batch catalog does not match selection")
    if selected_ids & {row["case_id"] for row in catalog}:
        errors.append("prospective cases already exist in the baseline catalog")

    rule = lock["selection_rules"]
    daily_index = {
        (row["region_id"], row["date"]): row
        for row in daily
        if row["variable"] == "tmax_c" and row["aggregation"] == "station_max"
    }
    for row in selection:
        start = date.fromisoformat(row["target_start_date"])
        end = date.fromisoformat(row["target_end_date"])
        days = _window(start, int(rule["utc_days_per_window"]))
        if days[-1] != end:
            errors.append(f"{row['case_id']}: target window length is invalid")
        initial = datetime.fromisoformat(row["initial_time"].replace("Z", "+00:00")).date()
        if initial != start - timedelta(days=1):
            errors.append(f"{row['case_id']}: initialization must precede target by one day")
        if row["region_id"] != rule["region_id"]:
            errors.append(f"{row['case_id']}: selected region diverges from lock")
        observed: list[float] = []
        for day in days:
            item = daily_index.get((row["region_id"], day.isoformat()))
            if item is None:
                errors.append(f"{row['case_id']}: missing SSOD observation for {day}")
                continue
            if int(item["station_count"]) < int(rule["minimum_station_count_per_day"]):
                errors.append(f"{row['case_id']}: insufficient station coverage for {day}")
            observed.append(float(item["observed_value"]))
        declared = [float(value) for value in row["observed_values_degc"].split(";")]
        if observed != declared:
            errors.append(f"{row['case_id']}: declared values do not match SSOD")
        if row["case_role"] == "event" and any(
            value < float(rule["event_station_max_minimum_degc_each_day"])
            for value in observed
        ):
            errors.append(f"{row['case_id']}: event threshold failed")
        if row["case_role"] == "control" and any(
            value > float(rule["control_station_max_maximum_degc_each_day"])
            for value in observed
        ):
            errors.append(f"{row['case_id']}: control threshold failed")
        if row["independent_overlap"] != "no":
            errors.append(f"{row['case_id']}: independent overlap must be no")
        if row["forecast_access_status"] != "not_accessed_as_of_lock":
            errors.append(f"{row['case_id']}: forecast access was not sealed")

    independent = [
        row
        for row in catalog
        if row["hazard"] == "heatwave" and row["dataset_split"] == "independent_test"
    ]
    buffer_days = int(rule["independent_heatwave_embargo_buffer_days"])
    for selected in selection:
        selected_start = date.fromisoformat(selected["target_start_date"])
        selected_end = date.fromisoformat(selected["target_end_date"])
        for held_out in independent:
            embargo_start = date.fromisoformat(held_out["event_start_time"][:10]) - timedelta(
                days=buffer_days
            )
            embargo_end = date.fromisoformat(held_out["event_end_time"][:10]) + timedelta(
                days=buffer_days
            )
            if selected_start <= embargo_end and selected_end >= embargo_start:
                errors.append(f"{selected['case_id']}: overlaps independent embargo")

    locked_candidate = lock["candidate"]
    temperature = candidate["temperature_candidate"]
    if float(temperature["maximum_weight"]) != float(
        locked_candidate["aggregation_maximum_weight"]
    ):
        errors.append("candidate maximum weight diverges from lock")
    if float(temperature["fixed_bias_correction_degc"]) != float(
        locked_candidate["fixed_bias_correction_degc"]
    ):
        errors.append("candidate bias correction diverges from lock")

    if check_forecast_absence:
        forecast_roots = (
            root / "data/raw/graphcast_2020",
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
    errors = validate_prospective_lock(
        args.root, check_forecast_absence=not args.allow_post_lock_artifacts
    )
    if errors:
        for error in errors:
            print(f"- {error}")
        raise SystemExit(f"prospective heatwave lock failed with {len(errors)} errors")
    print("verified 2 observation-only prospective development cases")
    print("no forecast artifact read; independent heatwave remains unopened")


if __name__ == "__main__":
    main()
