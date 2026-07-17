from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from saudi_warning.verification.run_development_diagnostics import (
    build_development_metrics,
    read_qc_config,
)


ROOT = Path(__file__).resolve().parents[1]
PAIRS = ROOT / "handoff" / "weather_verification" / "development_pairs.csv"
CONFIG = ROOT / "configs" / "weather_verification_qc_v1.yaml"
METRICS = ROOT / "handoff" / "weather_verification" / "development_continuous_metrics.csv"


def test_qc_config_keeps_independent_test_and_formal_ghcn_closed() -> None:
    config = read_qc_config(CONFIG)

    assert config["scope"] == "development_only"
    assert config["independent_test_access"] == "forbidden_until_rule_freeze"
    assert config["ghcn_daily"]["current_observation_time_status"] == "missing"
    assert "categorical_skill" in config["ghcn_daily"]["forbidden_outputs"]
    assert "heatwave_sequence" in config["ghcn_daily"]["forbidden_outputs"]


def test_development_metric_output_is_strictly_layered() -> None:
    frame = pd.read_csv(METRICS)

    assert len(frame) == 36
    assert set(frame["dataset_split"]) == {"development"}
    accepted = frame[frame["result_status"] == "accepted_development_metric"]
    provisional = frame[frame["result_status"] == "provisional_diagnostic_not_formal"]
    assert len(accepted) == 12
    assert len(provisional) == 24
    assert set(accepted["variable"]) == {"daily_precip_total"}
    assert set(accepted["pair_qc_status"]) == {"accepted"}
    assert set(provisional["variable"]) == {"tmax_c", "tmin_c"}
    assert set(provisional["pair_qc_status"]) == {"provisional"}
    categorical = [
        "hits",
        "misses",
        "false_alarms",
        "correct_negatives",
        "pod",
        "far",
        "csi",
    ]
    assert frame[categorical].isna().all().all()


def test_metric_value_matches_direct_calculation() -> None:
    pairs = pd.read_csv(PAIRS)
    output = build_development_metrics(pairs, read_qc_config(CONFIG))
    source = pairs[
        (pairs["qc_status"] == "accepted")
        & (pairs["variable"] == "daily_precip_total")
        & (pairs["aggregation"] == "weighted_mean")
    ]
    expected_mae = np.mean(np.abs(source["forecast_value"] - source["observed_value"]))
    row = output[
        (output["variable"] == "daily_precip_total")
        & (output["aggregation"] == "weighted_mean")
        & (output["scope"] == "all_leads")
    ].iloc[0]

    assert row["pair_count"] == len(source)
    assert row["mae"] == pytest.approx(expected_mae)
