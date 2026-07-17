from __future__ import annotations

import csv
from pathlib import Path

import pytest

from saudi_warning.risk.run_heatwave_bias_cv import load_preregistration


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "heatwave_bias_correction_cv_v1.yaml"
PAIRS = ROOT / "handoff" / "weather_verification" / "heatwave_bias_cv_pairs.csv"
AUDIT = ROOT / "handoff" / "risk_dry_runs" / "heatwave_bias_cv_rule_review.csv"
ASSESSMENT = ROOT / "manifests" / "heatwave_bias_cv_assessment.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_bias_cv_preregistration_locks_inputs_and_independent_access() -> None:
    config = load_preregistration(CONFIG)

    assert config["scope"] == "development_only"
    assert config["independent_heatwave_access"] == "forbidden"
    assert config["estimator"]["method"] == (
        "leave_one_case_out_additive_median_error"
    )
    assert config["success_gates"]["minimum_target_window_recall"] == 0.6
    assert config["decision_policy"]["independent_test_may_tune_correction"] is False


def test_bias_cv_outputs_cover_each_development_heat_case_once() -> None:
    pairs = read_csv(PAIRS)
    audit = read_csv(AUDIT)
    case_ids = {row["case_id"] for row in pairs}

    assert len(pairs) == 18
    assert len(audit) == 18
    assert len(case_ids) == 6
    assert all(int(row["training_case_count"]) == 5 for row in pairs)
    assert all("20200729_00" != row["case_id"] for row in pairs)
    assert sum(row["evaluation_scope"] == "target_window" for row in audit) == 11
    assert sum(row["evaluation_scope"] == "context_only" for row in audit) == 7


def test_bias_cv_remains_blocked_under_preregistered_gates() -> None:
    [row] = read_csv(ASSESSMENT)

    assert row["recommendation"] == "blocked"
    assert row["independent_heatwave_opened"] == "False"
    assert float(row["final_correction_degc"]) == pytest.approx(2.2798309326)
    assert float(row["target_window_recall"]) == pytest.approx(3 / 7)
    assert float(row["target_window_specificity"]) == 1.0
    assert float(row["event_case_detection_fraction"]) == 0.5
    assert float(row["control_case_rejection_fraction"]) == 1.0
    assert "target_window_recall_below_gate" in row["blocking_reasons"]
    assert "event_case_detection_below_gate" in row["blocking_reasons"]
