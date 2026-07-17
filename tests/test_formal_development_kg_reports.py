import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "handoff" / "knowledge_graph" / "formal_development_bundle.json"
REPORTS = ROOT / "handoff" / "reports" / "development_heavy_rain"
MANIFEST = ROOT / "manifests" / "formal_development_report_manifest.csv"


def test_formal_development_bundle_uses_frozen_risks() -> None:
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    risks = [node for node in bundle["nodes"] if node["label"] == "RiskAssessment"]
    rules = [node for node in bundle["nodes"] if node["label"] == "Rule"]

    assert bundle["status"] == "development_bundle"
    assert bundle["input_counts"]["risk_files"] == 15
    assert len(risks) == 15
    assert len(rules) == 1
    assert {node["properties"]["rule_status"] for node in risks} == {"frozen"}
    assert "尚未执行独立测试" in bundle["warning_zh"]


def test_formal_development_reports_preserve_disclosures() -> None:
    paths = sorted(REPORTS.glob("*.md"))
    with MANIFEST.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert len(paths) == len(rows) == 15
    assert len({row["sha256"] for row in rows}) == 15
    assert {row["rule_status"] for row in rows} == {"frozen"}
    assert {row["dataset_split"] for row in rows} == {"development"}
    for path in paths:
        report = path.read_text(encoding="utf-8")
        assert "冻结规则结果" in report
        assert "development_evidence_available" in report
        assert "not_opened_missing_four_imerg_dates" in report
        assert "固定模板生成" in report
