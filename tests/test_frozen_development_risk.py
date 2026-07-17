import csv
import json
from pathlib import Path

from saudi_warning.risk.validation import validate_paths


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "handoff" / "risk_results" / "development_heavy_rain"
MANIFEST = ROOT / "manifests" / "formal_development_risk_manifest.csv"


def test_frozen_development_results_are_complete_and_valid() -> None:
    paths = sorted(RESULTS.glob("*.json"))
    report = validate_paths(
        paths,
        ROOT / "schemas" / "risk_result.schema.json",
        ROOT / "configs" / "region_registry.csv",
        require_frozen=True,
    )

    assert len(paths) == 15
    assert not {path: errors for path, errors in report.items() if errors}
    for path in paths:
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["hazard"] == "heavy_rain"
        assert result["rule_status"] == "frozen"
        assert result["verification"]["dataset_split"] == "development"
        assert result["verification"]["pair_qc_status"] == "accepted"
        assert result["verification"]["independent_test_status"].startswith("not_opened")


def test_formal_development_manifest_is_traceable() -> None:
    with MANIFEST.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 15
    assert len({row["sha256"] for row in rows}) == 15
    assert {row["dataset_split"] for row in rows} == {"development"}
    assert {row["validation_status"] for row in rows} == {"passed"}
    assert {row["hazard"] for row in rows} == {"heavy_rain"}
    assert {row["rule_status"] for row in rows} == {"frozen"}
