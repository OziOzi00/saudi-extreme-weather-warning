"""Separate observed weather skill from event-window coverage for heatwave v4."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if config.get("status") != "locked_post_diagnostic_metric_separation":
        raise ValueError("weather-gate assessment is not locked")
    if config.get("independent_heatwave_access") != "forbidden":
        raise ValueError("independent heatwave access must remain forbidden")
    if config["decision_policy"].get("event_window_coverage_is_diagnostic_only") is not True:
        raise ValueError("event-window coverage must remain diagnostic-only")
    for item in config["locked_inputs"].values():
        source = Path(item["path"])
        if _sha256(source) != str(item["sha256"]).lower():
            raise ValueError(f"locked input SHA-256 mismatch: {source}")
    return config


def assess(config: dict[str, Any]) -> dict[str, Any]:
    rows = pd.read_csv(config["locked_inputs"]["layered_details"]["path"])
    methods = list(config["candidate_methods"])
    if set(rows["method"].astype(str)) != set(methods):
        raise ValueError("candidate methods diverge from the lock")
    target = rows[rows["evaluation_scope"] == "target_window"]
    gates = config["weather_success_gates"]
    results: list[dict[str, Any]] = []
    for method in methods:
        group = target[target["method"] == method]
        observed_hot = group[group["observed_hot_day"]]
        observed_nonhot = group[~group["observed_hot_day"]]
        controls = group[group["case_role"] == "control"]
        event_context = group[group["case_role"] == "event"]
        control_cases = controls.groupby("case_id")["candidate_positive"].any()
        recall = float(observed_hot["candidate_positive"].mean())
        specificity = float((~observed_nonhot["candidate_positive"]).mean())
        control_rejection = float((~control_cases).mean())
        passed = (
            recall >= float(gates["minimum_observed_hot_day_recall"])
            and specificity
            >= float(gates["minimum_observed_nonhot_day_specificity"])
            and control_rejection
            >= float(gates["required_control_case_rejection_fraction"])
        )
        results.append(
            {
                "method": method,
                "observed_hot_days": len(observed_hot),
                "observed_hot_day_hits": int(observed_hot["candidate_positive"].sum()),
                "observed_hot_day_recall": recall,
                "observed_nonhot_days": len(observed_nonhot),
                "observed_nonhot_day_correct_negatives": int(
                    (~observed_nonhot["candidate_positive"]).sum()
                ),
                "observed_nonhot_day_specificity": specificity,
                "control_case_rejection_fraction": control_rejection,
                "event_context_windows": len(event_context),
                "event_context_positive_windows": int(
                    event_context["candidate_positive"].sum()
                ),
                "passes_weather_gates": passed,
            }
        )
    passing = [row for row in results if row["passes_weather_gates"]]
    selected = None
    if passing:
        selected = max(
            passing,
            key=lambda row: (
                row["observed_hot_day_recall"],
                row["observed_nonhot_day_specificity"],
            ),
        )["method"]
    return {
        "schema_version": "heatwave_v4_1_weather_gate_v1",
        "scope": config["scope"],
        "weather_truth_definition": config["rationale"]["weather_truth"],
        "event_context_scored_as_weather_truth": False,
        "method_assessments": results,
        "selected_method_for_next_prospective_development": selected,
        "recommendation": (
            "preregister_new_prospective_development"
            if selected
            else "redesign_numeric_calibration"
        ),
        "rule_status": "draft_blocked",
        "can_freeze_now": False,
        "independent_heatwave_opened": False,
        "can_open_independent_heatwave": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/heatwave_v4_1_weather_gate.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("manifests/heatwave_v4_1_weather_gate_assessment.json"),
    )
    args = parser.parse_args()
    result = assess(load_config(args.config))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(args.output)
    print(f"selected={result['selected_method_for_next_prospective_development']}")
    print(f"recommendation={result['recommendation']}")


if __name__ == "__main__":
    main()
