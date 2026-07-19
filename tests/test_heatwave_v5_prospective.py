import json
from pathlib import Path

import pandas as pd
import yaml

from saudi_warning.risk.run_heatwave_v5_prospective import assess_candidate, run
from saudi_warning.verification.heatwave_v5_prospective import validate_v5_lock


ROOT = Path(__file__).resolve().parents[1]


def test_v5_cross_year_lock_is_internally_consistent() -> None:
    assert validate_v5_lock(ROOT, check_forecast_absence=False) == []


def test_v5_lock_records_that_forecasts_were_absent_when_committed() -> None:
    # Forecast artifacts legitimately exist after the preregistration commit. The
    # immutable lock, rather than today's working tree, records the temporal fact.
    lock = json.loads(
        (ROOT / "manifests/heatwave_v5_prospective_lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert lock["forecast_artifacts_present_at_lock"] is False
    assert lock["forecast_arrays_read_during_selection"] is False


def test_v5_weather_and_case_gates_are_kept_separate() -> None:
    config = yaml.safe_load(
        (ROOT / "configs/heatwave_v5_prospective_candidate.yaml").read_text(
            encoding="utf-8"
        )
    )
    rows = []
    for role, case_id in (("event", "E1"), ("event", "E2"), ("event", "E3")):
        for lead, observed, hot, positive in (
            (24, True, True, False),
            (48, True, True, True),
            (72, False, False, False),
        ):
            rows.append(
                {
                    "case_id": case_id,
                    "case_role": role,
                    "lead_time_hours": lead,
                    "observed_hot_day": observed,
                    "candidate_hot_day": hot,
                    "candidate_positive": positive,
                }
            )
    for case_id in ("C1", "C2", "C3"):
        for lead in (24, 48, 72):
            rows.append(
                {
                    "case_id": case_id,
                    "case_role": "control",
                    "lead_time_hours": lead,
                    "observed_hot_day": False,
                    "candidate_hot_day": False,
                    "candidate_positive": False,
                }
            )
    result = assess_candidate(pd.DataFrame(rows), config)
    assert result["observed_hot_day_recall"] == 1.0
    assert result["observed_nonhot_day_specificity"] == 1.0
    assert result["event_case_detection_fraction"] == 1.0
    assert result["control_case_rejection_fraction"] == 1.0
    assert result["passes_all_preregistered_gates"] is True
    assert result["independent_heatwave_opened"] is False


def test_v5_cross_year_result_is_reproducible_without_retuning(tmp_path: Path) -> None:
    result = run(
        ROOT,
        ROOT / "configs/heatwave_v5_prospective_candidate.yaml",
        ROOT / "manifests/heatwave_v5_prospective_selection.csv",
        ROOT
        / "handoff/region_summaries/heatwave_v5_2018_adm1_indicator_summaries.csv",
        tmp_path / "details.csv",
        tmp_path / "assessment.json",
    )
    assert result["observed_hot_day_hits"] == 5
    assert result["observed_hot_days"] == 6
    assert result["observed_nonhot_day_correct_negatives"] == 8
    assert result["observed_nonhot_days"] == 12
    assert result["event_case_detections"] == 2
    assert result["control_case_correct_rejections"] == 2
    assert result["passes_all_preregistered_gates"] is False
    assert result["recommendation"] == "keep_heatwave_draft_blocked"
    assert result["post_lock_threshold_search_performed"] is False
