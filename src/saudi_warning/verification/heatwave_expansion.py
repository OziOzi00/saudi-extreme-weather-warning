"""Verify the locked second-round heatwave development expansion selection."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def validate_expansion(root: Path) -> list[str]:
    """Return errors without reading any GraphCast forecast result."""
    root = root.resolve()
    lock_path = root / "manifests/heatwave_development_expansion_v2_lock.json"
    selection_path = root / "manifests/heatwave_development_expansion_v2_selection.csv"
    daily_path = root / "manifests/ssod_v2_saudi_2020_daily_summary.csv"
    catalog_path = root / "configs/case_catalog_candidates.csv"
    batch_catalog_path = root / "configs/heatwave_development_expansion_v2_catalog.csv"

    lock: dict[str, Any] = json.loads(lock_path.read_text(encoding="utf-8"))
    selection = _rows(selection_path)
    catalog = _rows(catalog_path)
    batch_catalog = _rows(batch_catalog_path)
    daily = _rows(daily_path)
    errors: list[str] = []

    if lock.get("status") != "preregistered_before_forecast_access":
        errors.append("lock status is not preregistered_before_forecast_access")
    if lock.get("independent_heatwave_opened") is not False:
        errors.append("independent heatwave must remain unopened")
    if lock.get("forecast_results_read_during_selection") is not False:
        errors.append("selection must precede forecast access")
    if lock.get("rule_modified") is not False:
        errors.append("selection must not modify the heatwave rule")

    fingerprints = lock.get("input_fingerprints", {})
    for name, path in (("ssod_daily_summary", daily_path),):
        expected = fingerprints.get(name, {}).get("sha256")
        actual = _sha256(path)
        if expected != actual:
            errors.append(f"{name} SHA-256 mismatch: expected {expected}, got {actual}")

    selected_ids = {row["case_id"] for row in selection}
    if selected_ids != set(lock.get("selected_case_ids", [])):
        errors.append("selected case IDs do not match the lock")
    if selected_ids != {row["case_id"] for row in batch_catalog}:
        errors.append("batch catalog does not match the locked selection")
    catalog_by_id = {row["case_id"]: row for row in catalog}
    integrated = selected_ids <= set(catalog_by_id)
    if not integrated:
        expected = fingerprints.get("baseline_case_catalog", {}).get("sha256")
        actual = _sha256(catalog_path)
        if expected != actual:
            errors.append(
                f"baseline_case_catalog SHA-256 mismatch: expected {expected}, got {actual}"
            )
    else:
        for case_id in selected_ids:
            row = catalog_by_id[case_id]
            if row["selection_status"] != "approved" or row["dataset_split"] != "development":
                errors.append(f"{case_id}: integrated catalog status is not approved development")

    daily_index = {
        (row["region_id"], row["date"]): row
        for row in daily
        if row["variable"] == "tmax_c" and row["aggregation"] == "station_max"
    }
    rules = lock["selection_rules"]
    for row in selection:
        start = date.fromisoformat(row["target_start_date"])
        end = date.fromisoformat(row["target_end_date"])
        window = _dates(start, end)
        if len(window) != rules["utc_days_per_window"]:
            errors.append(f"{row['case_id']}: target window is not three UTC days")
            continue
        initial = datetime.fromisoformat(row["initial_time"].replace("Z", "+00:00")).date()
        if initial != start - timedelta(days=1):
            errors.append(f"{row['case_id']}: initial time must be one day before target start")
        observed = []
        for day in window:
            item = daily_index.get((row["region_id"], day.isoformat()))
            if item is None:
                errors.append(f"{row['case_id']}: missing SSOD observation for {day}")
                continue
            if int(item["station_count"]) < rules["minimum_station_count_per_day"]:
                errors.append(f"{row['case_id']}: insufficient stations for {day}")
            observed.append(float(item["observed_value"]))
        declared = [float(value) for value in row["observed_values_degc"].split(";")]
        if observed != declared:
            errors.append(f"{row['case_id']}: declared observations do not match SSOD")
        if row["case_role"] == "event" and any(
            value < rules["event_station_max_minimum_degc_each_day"] for value in observed
        ):
            errors.append(f"{row['case_id']}: event threshold failed")
        if row["case_role"] == "control" and any(
            value > rules["control_station_max_maximum_degc_each_day"] for value in observed
        ):
            errors.append(f"{row['case_id']}: control threshold failed")
        if row["independent_overlap"] != "no":
            errors.append(f"{row['case_id']}: independent overlap must be no")
        if row["forecast_access_status"] != "not_accessed_as_of_lock":
            errors.append(f"{row['case_id']}: forecast access status is not locked")

    independent = [
        row
        for row in catalog
        if row["hazard"] == "heatwave" and row["dataset_split"] == "independent_test"
    ]
    buffer_days = int(rules["independent_heatwave_embargo_buffer_days"])
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
                errors.append(f"{selected['case_id']}: overlaps independent heatwave embargo")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    errors = validate_expansion(args.root)
    if errors:
        for error in errors:
            print(f"- {error}")
        raise SystemExit(f"heatwave expansion validation failed with {len(errors)} errors")
    print("verified 2 locked heatwave development expansion cases")
    print("independent heatwave remains unopened; observation-only selection lock is preserved")


if __name__ == "__main__":
    main()
