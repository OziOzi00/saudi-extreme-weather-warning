from pathlib import Path

from saudi_warning.risk.assess_heatwave_v4_weather_gate import assess, load_config
from saudi_warning.risk.run_heatwave_v4_layered import run


ROOT = Path(__file__).resolve().parents[1]


def test_v4_layered_comparison_preserves_boundaries(tmp_path: Path) -> None:
    result = run(
        ROOT / "configs/heatwave_v4_layered_calibration.yaml",
        tmp_path / "details.csv",
        tmp_path / "assessment.json",
    )

    assert result["independent_heatwave_opened"] is False
    assert result["evaluated_sa08_used_for_fitting"] is False
    assert result["thresholds_changed"] is False
    assert result["duration_rule_changed"] is False
    assert result["maximum_blending_used"] is False
    assert result["can_freeze_now"] is False
    assert result["passing_methods"] == []


def test_weather_gate_selects_lead_specific_only_for_next_development() -> None:
    result = assess(load_config(ROOT / "configs/heatwave_v4_1_weather_gate.yaml"))

    assert result["selected_method_for_next_prospective_development"] == (
        "lead_specific_median"
    )
    assert result["rule_status"] == "draft_blocked"
    assert result["event_context_scored_as_weather_truth"] is False
    assert result["can_freeze_now"] is False
    assert result["can_open_independent_heatwave"] is False

    methods = {row["method"]: row for row in result["method_assessments"]}
    assert methods["lead_specific_median"]["observed_hot_day_hits"] == 4
    assert methods["lead_specific_median"]["observed_hot_days"] == 6
    assert methods["lead_specific_median"]["observed_nonhot_day_specificity"] == 8 / 9
    assert methods["lead_specific_median"]["passes_weather_gates"] is True
