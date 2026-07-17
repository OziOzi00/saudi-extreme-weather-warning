"""Generate development-only continuous metrics with explicit QC separation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from saudi_warning.verification.metrics import compute_metrics, validate_pairs


RESULT_COLUMNS = [
    "dataset_split",
    "pair_qc_status",
    "result_status",
    "variable",
    "aggregation",
    "scope",
    "pair_count",
    "mae",
    "rmse",
    "bias",
    "unit",
    "hits",
    "misses",
    "false_alarms",
    "correct_negatives",
    "pod",
    "far",
    "csi",
    "metric_limitations",
]


def read_qc_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if config.get("status") != "frozen_for_development_diagnostics":
        raise ValueError("QC configuration is not frozen for development diagnostics")
    if config.get("scope") != "development_only":
        raise ValueError("QC configuration must be development_only")
    if config.get("independent_test_access") != "forbidden_until_rule_freeze":
        raise ValueError("independent-test access guard is missing")
    return config


def _label_metrics(
    metrics: pd.DataFrame,
    pair_qc_status: str,
    result_status: str,
    limitations: str,
) -> pd.DataFrame:
    labelled = metrics.copy()
    labelled.insert(0, "dataset_split", "development")
    labelled.insert(1, "pair_qc_status", pair_qc_status)
    labelled.insert(2, "result_status", result_status)
    labelled["metric_limitations"] = limitations
    return labelled[RESULT_COLUMNS]


def build_development_metrics(pairs: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Compute accepted IMERG metrics and segregated provisional GHCN diagnostics."""

    errors = validate_pairs(pairs)
    if errors:
        raise ValueError("; ".join(errors))
    approved_ids = {str(value) for value in config["approved_development_case_ids"]}
    actual_ids = set(pairs["case_id"].astype(str))
    if actual_ids != approved_ids:
        raise ValueError("pair case IDs do not exactly match the frozen development set")
    if pairs["event_threshold"].notna().any():
        raise ValueError("development thresholds must remain blank at this stage")

    accepted = pairs[pairs["qc_status"] == "accepted"].copy()
    if accepted.empty or set(accepted["observation_source"]) != {"IMERG"}:
        raise ValueError("accepted development rows must be IMERG-only")
    if (accepted["coverage_fraction"] < config["imerg"]["minimum_coverage_fraction"]).any():
        raise ValueError("accepted IMERG row is below the frozen coverage minimum")
    accepted_metrics = _label_metrics(
        compute_metrics(accepted),
        "accepted",
        "accepted_development_metric",
        "Development split only; thresholds are not frozen, so categorical fields are blank.",
    )

    provisional = pairs[pairs["qc_status"] == "provisional"].copy()
    if provisional.empty or set(provisional["observation_source"]) != {"GHCN_DAILY"}:
        raise ValueError("provisional development rows must be GHCN_DAILY-only")
    minimum_stations = config["ghcn_daily"]["diagnostic_minimum_station_count"]
    if (provisional["station_count"] < minimum_stations).any():
        raise ValueError("provisional GHCN row is below the diagnostic station minimum")
    # compute_metrics intentionally accepts only accepted rows. This copy changes the
    # in-memory calculation gate, not the source pairs or their provisional status.
    provisional_for_calculation = provisional.copy()
    provisional_for_calculation["qc_status"] = "accepted"
    provisional_metrics = _label_metrics(
        compute_metrics(provisional_for_calculation),
        "provisional",
        "provisional_diagnostic_not_formal",
        (
            "GHCN OBS-TIME is missing and some windows have one station; values are "
            "continuous diagnostics only, not formal temperature or heatwave validation."
        ),
    )

    output = pd.concat([accepted_metrics, provisional_metrics], ignore_index=True)
    categorical = [
        "hits",
        "misses",
        "false_alarms",
        "correct_negatives",
        "pod",
        "far",
        "csi",
    ]
    if output[categorical].notna().any().any():
        raise AssertionError("categorical metrics were produced before threshold freeze")
    return output.sort_values(
        ["pair_qc_status", "variable", "aggregation", "scope"], kind="stable"
    ).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs",
        type=Path,
        default=Path("handoff/weather_verification/development_pairs.csv"),
    )
    parser.add_argument(
        "--qc-config",
        type=Path,
        default=Path("configs/weather_verification_qc_v1.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("handoff/weather_verification/development_continuous_metrics.csv"),
    )
    args = parser.parse_args()

    pairs = pd.read_csv(args.pairs)
    metrics = build_development_metrics(pairs, read_qc_config(args.qc_config))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.output, index=False, float_format="%.8g")
    counts = metrics["result_status"].value_counts()
    print(args.output)
    print(f"rows={len(metrics)} " + " ".join(f"{key}={value}" for key, value in counts.items()))


if __name__ == "__main__":
    main()
