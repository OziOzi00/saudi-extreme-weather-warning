from pathlib import Path

from saudi_warning.risk.diagnose_heatwave_development import diagnose


ROOT = Path(__file__).resolve().parents[1]


def test_heatwave_diagnostic_preserves_development_boundary() -> None:
    rows, summary = diagnose(
        ROOT / "handoff/weather_verification/heatwave_bias_cv_v2_pairs.csv",
        ROOT / "handoff/risk_dry_runs/heatwave_bias_cv_v2_rule_review.csv",
        ROOT / "handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv",
    )

    assert len(rows) == 24
    assert summary["scope"] == "development_only"
    assert summary["independent_heatwave_opened"] is False
    assert summary["prohibited_action"] == "do_not_open_or_tune_on_independent_heatwave"


def test_heatwave_diagnostic_separates_label_and_rule_failures() -> None:
    rows, summary = diagnose(
        ROOT / "handoff/weather_verification/heatwave_bias_cv_v2_pairs.csv",
        ROOT / "handoff/risk_dry_runs/heatwave_bias_cv_v2_rule_review.csv",
        ROOT / "handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv",
    )

    assert summary["event_target_windows"] == 9
    assert summary["candidate_event_window_hits"] == 5
    assert summary["candidate_event_window_misses"] == 4
    assert summary["observed_hot_event_target_windows"] == 6
    assert summary["observed_nonhot_event_target_windows"] == 3
    assert summary["candidate_hits_among_observed_hot_event_windows"] == 3
    assert summary["candidate_positives_among_observed_nonhot_event_windows"] == 2
    assert summary["miss_attribution_counts"] == {
        "aggregation_proxy_gap": 1,
        "duration_gate": 1,
        "forecast_or_correction_shortfall": 1,
        "event_label_not_observed_hot_day": 1,
    }
    assert set(rows["diagnostic_attribution"]) >= {
        "aggregation_proxy_gap",
        "duration_gate",
        "forecast_or_correction_shortfall",
        "event_label_not_observed_hot_day",
    }


def test_heatwave_bias_correction_improves_mae_but_not_all_leads() -> None:
    _, summary = diagnose(
        ROOT / "handoff/weather_verification/heatwave_bias_cv_v2_pairs.csv",
        ROOT / "handoff/risk_dry_runs/heatwave_bias_cv_v2_rule_review.csv",
        ROOT / "handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv",
    )

    assert summary["corrected_mae_degc"] < summary["raw_mae_degc"]
    assert len(summary["lead_diagnostics"]) == 3


def test_heatwave_aggregation_sensitivity_is_exploratory_only() -> None:
    _, summary = diagnose(
        ROOT / "handoff/weather_verification/heatwave_bias_cv_v2_pairs.csv",
        ROOT / "handoff/risk_dry_runs/heatwave_bias_cv_v2_rule_review.csv",
        ROOT / "handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv",
    )

    sensitivity = summary["aggregation_sensitivity"]
    assert sensitivity[0]["maximum_weight"] == 0.0
    assert sensitivity[0]["event_target_hits"] == 5
    assert sensitivity[0]["control_correct_negatives"] == 6
    assert all(row["exploratory_only"] is True for row in sensitivity)
