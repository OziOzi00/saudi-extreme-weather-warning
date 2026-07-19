import json
from pathlib import Path

import pandas as pd
import yaml

from saudi_warning.risk.benchmark_integrated_candidates import (
    heatwave_candidate_rows,
    load_heatwave_development,
    load_rain_rows,
)
from saudi_warning.risk.select_joint_pipeline import (
    _rain_assessment,
    apply_locked_heatwave_candidate,
    apply_locked_heavy_rain_candidate,
)
from saudi_warning.agent.run_joint_forecast_report import build_report, validate_report


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "manifests/joint_pipeline_selection_lock_v2.json"
CONFIG_PATH = ROOT / "configs/joint_pipeline_candidate_search_v2.yaml"


def _lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def test_joint_selection_uses_development_and_records_search_scale() -> None:
    lock = _lock()
    assert lock["selection_split"] == "development"
    assert lock["independent_truth_used_by_selection_code"] is False
    assert lock["heavy_rain"]["candidate_count"] == 234
    assert lock["heatwave"]["candidate_count"] == 2316
    assert lock["heavy_rain"]["selected"]["passes_all_gates"] is True
    assert lock["heatwave"]["selected"]["passes_all_gates"] is False
    assert [
        item["operating_profile"] for item in lock["heatwave"]["operating_points"]
    ] == ["balanced", "conservative", "recall_first"]


def test_locked_rain_rule_infers_on_all_leads_then_scores_targets() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    rows = load_rain_rows(ROOT, "development", target_only=False)
    selected = apply_locked_heavy_rain_candidate(
        rows, _lock()["heavy_rain"]["selected"]
    )
    assessment = _rain_assessment(selected, config).iloc[0]
    corrected = selected[selected["knowledge_triggered"]]

    assert set(corrected["lead_time_hours"].astype(int)) == {24, 48, 72}
    assert assessment["hits"] == 5
    assert assessment["false_alarms"] == 0
    assert assessment["knowledge_trigger_count"] == 2


def test_locked_heat_rule_predictions_do_not_depend_on_truth_columns() -> None:
    search_config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    base_config = yaml.safe_load(
        (ROOT / search_config["heatwave"]["base_config"]).read_text(
            encoding="utf-8"
        )
    )
    source = load_heatwave_development(ROOT)
    base_method = _lock()["heatwave"]["selected"]["base_method"]
    base = heatwave_candidate_rows(source, base_config)
    base = base[base["method"] == base_method].copy()
    altered = base.copy()
    altered["observed_hot_day"] = ~altered["observed_hot_day"].astype(bool)
    altered["observed_tmax_degc"] = -999.0

    original_result = apply_locked_heatwave_candidate(
        base, _lock()["heatwave"]["selected"]
    )
    altered_result = apply_locked_heatwave_candidate(
        altered, _lock()["heatwave"]["selected"]
    )
    columns = ["knowledge_triggered", "integrated_hot_day", "candidate_positive"]
    pd.testing.assert_frame_equal(
        original_result[columns].reset_index(drop=True),
        altered_result[columns].reset_index(drop=True),
    )


def test_independent_prediction_locks_contain_no_truth_fields() -> None:
    result = json.loads(
        (
            ROOT / "manifests/joint_pipeline_full_chain_evaluation_v2.json"
        ).read_text(encoding="utf-8")
    )
    assert result["prediction_locks"]["truth_fields_present_in_prediction_locks"] is False
    forbidden = {
        "observed_tmax_degc",
        "observed_hot_day",
        "case_role",
        "hits",
        "misses",
        "false_alarms",
    }
    for name in (
        "locked_joint_heavy_rain_predictions.csv",
        "locked_joint_heatwave_predictions.csv",
    ):
        columns = set(
            pd.read_csv(ROOT / "handoff/model_selection/joint_v2" / name).columns
        )
        assert columns.isdisjoint(forbidden)


def test_development_prediction_locks_contain_no_truth_fields() -> None:
    lock = _lock()["truth_free_development_prediction_locks"]
    assert lock["truth_fields_present"] is False
    forbidden = {
        "observed_tmax_degc",
        "observed_hot_day",
        "case_role",
        "hits",
        "misses",
        "false_alarms",
    }
    for hazard in ("heavy_rain", "heatwave"):
        columns = set(pd.read_csv(ROOT / lock[f"{hazard}_path"]).columns)
        assert columns.isdisjoint(forbidden)


def test_joint_agent_reports_base_and_corrected_risk_without_truth() -> None:
    report = build_report(
        ROOT, "heavy_rain", "development", "20200501_00", "SA-09", 48
    )
    assert report["truth_accessed"] is False
    assert report["base_risk_level"] == "low"
    assert report["knowledge_triggered"] is True
    assert report["joint_final_risk_level"] == "medium"
    assert report["decision_change"] == "upgraded"
    assert report["development_gate_passed"] is True
    assert validate_report(report) == []


def test_joint_agent_blocks_heatwave_formal_warning() -> None:
    report = build_report(
        ROOT, "heatwave", "independent_test", "20200729_00", "SA-04", 48
    )
    assert report["truth_accessed"] is False
    assert report["base_risk_level"] == "high"
    assert report["joint_final_risk_level"] == "high"
    assert report["decision_change"] == "unchanged"
    assert report["operating_status"] == "research_only_blocked"
    assert report["formal_warning_allowed"] is False
    assert validate_report(report) == []


def test_joint_policy_keeps_heatwave_formal_warning_blocked() -> None:
    policy = yaml.safe_load(
        (ROOT / "configs/joint_operating_policy_v2.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert policy["hazards"]["heavy_rain"]["joint_research_output_enabled"] is True
    assert policy["hazards"]["heatwave"]["formal_warning_allowed"] is False
    assert policy["reporting"]["truth_access_in_forecast"] == "forbidden"
