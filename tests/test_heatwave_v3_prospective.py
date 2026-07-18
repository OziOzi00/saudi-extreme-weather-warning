from pathlib import Path

from saudi_warning.verification.heatwave_v3_prospective import validate_prospective_lock


ROOT = Path(__file__).resolve().parents[1]


def test_heatwave_v3_lock_remains_valid_after_forecast_delivery() -> None:
    assert validate_prospective_lock(ROOT, check_forecast_absence=False) == []


def test_heatwave_v3_selection_does_not_name_independent_artifacts() -> None:
    text = (ROOT / "manifests/heatwave_v3_prospective_selection.csv").read_text(
        encoding="utf-8"
    )
    assert "independent_test" not in text
    assert "20200729_00" not in text
    assert "not_accessed_as_of_lock" in text


def test_heatwave_v3_candidate_remains_exploratory() -> None:
    text = (ROOT / "configs/heatwave_v3_prospective_candidate.yaml").read_text(
        encoding="utf-8"
    )
    assert "candidate_origin: retrospective_development_sensitivity" in text
    assert "exploratory_candidate_requires_new_development_validation" in text
    assert "independent_heatwave_access: forbidden" in text
