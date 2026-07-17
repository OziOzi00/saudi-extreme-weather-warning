import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "handoff" / "knowledge_graph" / "heavy_rain_evaluation_bundle.json"
REPORTS = ROOT / "handoff" / "reports" / "independent_heavy_rain"
MANIFEST = ROOT / "manifests" / "independent_heavy_rain_report_manifest.csv"


def test_heavy_rain_bundle_contains_development_and_independent_results() -> None:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    risks = [node for node in bundle["nodes"] if node["label"] == "RiskAssessment"]

    assert bundle["input_counts"]["risk_files"] == 33
    assert len(bundle["nodes"]) == 87
    assert len(bundle["relations"]) == 152
    assert len(risks) == 33
    assert "一次性independent_test" in bundle["warning_zh"]
    serialized = json.dumps(risks, ensure_ascii=False)
    assert "independent_test_one_time_locked" in serialized
    assert "development_evidence_available" in serialized


def test_independent_reports_preserve_locked_evaluation_status() -> None:
    paths = sorted(REPORTS.glob("*.md"))
    with MANIFEST.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert len(paths) == len(rows) == 18
    assert len({row["sha256"] for row in rows}) == 18
    assert {row["dataset_split"] for row in rows} == {"independent_test"}
    for path in paths:
        report = path.read_text(encoding="utf-8")
        assert "冻结规则结果" in report
        assert "independent_test_one_time_locked" in report
        assert '"no_retuning": true' in report
