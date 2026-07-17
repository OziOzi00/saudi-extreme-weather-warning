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


def test_qc_config_keeps_independent_heatwave_closed_and_ssod_formal() -> None:
    config = read_qc_config(CONFIG)

    assert config["scope"] == "development_only"
    assert config["independent_test_access"] == "hazard_specific_lock"
    assert config["independent_heatwave_access"] == "forbidden_until_heat_rule_freeze"
    assert config["ghcn_daily"]["current_observation_time_status"] == "missing"
    assert "categorical_skill" in config["ghcn_daily"]["forbidden_outputs"]
    assert "heatwave_sequence" in config["ghcn_daily"]["forbidden_outputs"]


def test_development_metric_output_is_strictly_layered() -> None:
    frame = pd.read_csv(METRICS)

    assert len(frame) == 36
    assert set(frame["dataset_split"]) == {"development"}
    imerg_metrics = frame[frame["result_status"] == "accepted_development_metric"]
    ssod_metrics = frame[
        frame["result_status"] == "accepted_ssod_utc_development_metric"
    ]
    assert len(imerg_metrics) == 12
    assert len(ssod_metrics) == 24
    assert set(imerg_metrics["variable"]) == {"daily_precip_total"}
    assert set(ssod_metrics["variable"]) == {"tmax_c", "tmin_c"}
    assert set(frame["pair_qc_status"]) == {"accepted"}
    categorical = [
        "hits",
        "misses",
        "false_alarms",
        "correct_negatives",
        "pod",
        "far",
        "csi",
    ]
    rain = frame[frame["variable"] == "daily_precip_total"]
    heat = frame[frame["variable"].isin(["tmax_c", "tmin_c"])]
    assert rain[categorical].isna().all().all()
    assert heat[categorical[:4]].notna().all().all()
    assert heat[categorical[4:]].notna().any().all()


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
