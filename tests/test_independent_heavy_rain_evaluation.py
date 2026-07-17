import csv
import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "manifests" / "independent_heavy_rain_evaluation_lock.json"
PAIRS = ROOT / "handoff" / "weather_verification" / "independent_heavy_rain_pairs.csv"
METRICS = ROOT / "handoff" / "weather_verification" / "independent_heavy_rain_metrics.csv"
REVIEW = ROOT / "handoff" / "weather_verification" / "independent_heavy_rain_rule_review.csv"
RESULTS = ROOT / "handoff" / "risk_results" / "independent_heavy_rain"


def test_independent_lock_binds_frozen_rule_and_four_cases() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    rule = ROOT / lock["rule_file"]

    assert lock["dataset_split"] == "independent_test"
    assert lock["case_ids"] == [
        "20200711_00",
        "20200725_00",
        "20201112_00",
        "20201125_00",
    ]
    assert hashlib.sha256(rule.read_bytes()).hexdigest() == lock["rule_sha256"]
    assert "must not be changed" in lock["no_retuning_declaration"]


def test_independent_pairs_and_metrics_are_complete() -> None:
    pairs = pd.read_csv(PAIRS)
    metrics = pd.read_csv(METRICS)

    assert len(pairs) == 54
    assert set(pairs["qc_status"]) == {"accepted"}
    p95 = pairs[pairs["aggregation"] == "spatial_p95"]
    assert len(p95) == 18
    assert p95["event_threshold"].notna().all()
    assert pairs[pairs["aggregation"] != "spatial_p95"]["event_threshold"].isna().all()
    assert len(metrics) == 12
    assert set(metrics["dataset_split"]) == {"independent_test"}
    all_p95 = metrics[
        (metrics["aggregation"] == "spatial_p95") & (metrics["scope"] == "all_leads")
    ].iloc[0]
    categorical_total = sum(
        int(all_p95[field])
        for field in ("hits", "misses", "false_alarms", "correct_negatives")
    )
    assert categorical_total == all_p95["pair_count"] == 18


def test_independent_review_and_results_are_sealed() -> None:
    with REVIEW.open(encoding="utf-8", newline="") as stream:
        review = list(csv.DictReader(stream))
    paths = sorted(RESULTS.glob("*.json"))

    assert len(review) == len(paths) == 18
    assert sum(row["evaluation_scope"] == "target_window" for row in review) == 11
    assert sum(row["evaluation_scope"] == "context_only" for row in review) == 7
    for path in paths:
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["rule_status"] == "frozen"
        assert result["verification"]["status"] == "independent_test_one_time_locked"
        assert result["verification"]["no_retuning"] is True
