import json
from pathlib import Path

from saudi_warning.verification.heatwave_expansion import validate_expansion


ROOT = Path(__file__).resolve().parents[1]


def test_locked_heatwave_expansion_matches_ssod_and_catalog() -> None:
    assert validate_expansion(ROOT) == []


def test_locked_heatwave_expansion_keeps_independent_data_closed() -> None:
    lock = json.loads(
        (ROOT / "manifests/heatwave_development_expansion_v2_lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert lock["independent_heatwave_opened"] is False
    assert lock["forecast_results_read_during_selection"] is False
    assert lock["rule_modified"] is False


def test_locked_heatwave_expansion_has_balanced_roles() -> None:
    import csv

    path = ROOT / "manifests/heatwave_development_expansion_v2_selection.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {row["case_role"] for row in rows} == {"event", "control"}
    assert {row["case_id"] for row in rows} == {"20200622_00", "20200627_00"}
