from pathlib import Path

from saudi_warning.risk.run_heatwave_v3_prospective import run


ROOT = Path(__file__).resolve().parents[1]


def _run():
    return run(
        ROOT,
        ROOT / "configs/heatwave_v3_prospective_candidate.yaml",
        ROOT / "configs/case_catalog_candidates.csv",
        ROOT / "handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv",
        ROOT / "handoff/weather_verification/development_pairs.csv",
        ROOT / "handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv",
        ROOT / "configs/heavy_rain_rules_v2.yaml",
        ROOT / "configs/heatwave_rules_v2.yaml",
    )


def test_heatwave_v3_prospective_gate_fails_without_retuning() -> None:
    details, _, assessment = _run()

    assert len(details) == 6
    assert assessment["event_target_windows"] == 2
    assert assessment["event_target_hits"] == 0
    assert assessment["observed_hot_target_windows"] == 2
    assert assessment["observed_hot_target_hits"] == 0
    assert assessment["control_target_windows"] == 2
    assert assessment["control_correct_negatives"] == 2
    assert assessment["recommendation"] == "keep_blocked"


def test_heatwave_v3_prospective_keeps_independent_sealed() -> None:
    _, _, assessment = _run()

    assert assessment["candidate_weight"] == 0.6
    assert assessment["heatwave_rule_frozen"] is False
    assert assessment["independent_heatwave_opened"] is False
    assert assessment["alternative_weights_searched_after_lock"] is False


def test_heatwave_v3_event_failure_is_duration_sensitive() -> None:
    details, _, _ = _run()
    event = [row for row in details if row["case_role"] == "event"]
    lead48 = next(row for row in event if row["lead_time_hours"] == 48)
    lead72 = next(row for row in event if row["lead_time_hours"] == 72)

    assert lead48["candidate_tmax_degc"] < lead48["event_threshold_degc"]
    assert lead72["candidate_tmax_degc"] >= lead72["event_threshold_degc"]
    assert lead48["risk_level"] == "low"
    assert lead72["risk_level"] == "low"
