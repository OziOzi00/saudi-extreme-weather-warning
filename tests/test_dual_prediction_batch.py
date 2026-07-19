import hashlib
import json
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "handoff/reports/dual_prediction_batch_v1"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_dual_prediction_batch_is_complete_locked_and_hash_valid() -> None:
    schema = _read_json(ROOT / "schemas/dual_prediction_batch_manifest_v1.schema.json")
    manifest = _read_json(BATCH / "batch_manifest.json")
    Draft202012Validator(schema).validate(manifest)
    state = _read_json(BATCH / "batch_state.json")
    assert state["status"] == "complete"
    assert all(status == "completed" for status in state["stages"].values())
    assert state["truth_accessed_during_prediction"] is False
    assert state["stage_results"]["generate_dual_reports"]["report_count"] == 29
    assert state["stage_results"]["lock_llm_advisories"]["rows"] == 87
    assert state["stage_results"]["post_lock_verification"]["truth_opened_only_after_lock"] is True
    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]


def test_all_dual_reports_match_schema_and_preserve_system_timeline() -> None:
    schema = _read_json(ROOT / "schemas/agent_dual_prediction_report_v1.schema.json")
    reports = sorted((BATCH / "reports").glob("*/*/*.json"))
    reports = [path for path in reports if not path.name.endswith(".evidence.json")]
    assert len(reports) == 29
    for path in reports:
        report = _read_json(path)
        evidence = _read_json(path.with_suffix(".evidence.json"))
        Draft202012Validator(schema).validate(report)
        assert report["truth_accessed"] is False
        assert evidence["system_timeline"]["truth_accessed"] is False
        assert [item["lead_time_hours"] for item in report["timeline_analysis"]] == [
            24,
            48,
            72,
        ]
        source = evidence["system_timeline"]["timeline"]
        for item, expected in zip(report["timeline_analysis"], source, strict=True):
            assert item["system_base_risk_level"] == expected["base_risk_level"]
            assert item["system_knowledge_triggered"] is expected["knowledge_triggered"]
            assert item["system_joint_final_risk_level"] == expected["joint_final_risk_level"]
            assert item["agreement_with_system"] is (
                item["llm_advisory_risk_level"] == item["system_joint_final_risk_level"]
            )


def test_advisory_lock_is_truth_free_and_verified_only_after_lock() -> None:
    advisory_path = BATCH / "llm_advisory_prediction_lock.csv"
    advisory = pd.read_csv(advisory_path)
    assert len(advisory) == 87
    assert set(advisory["truth_accessed"].astype(str).str.lower()) == {"false"}
    assert not any(
        token in column.lower()
        for column in advisory.columns.drop("truth_accessed")
        for token in ("observed", "truth", "case_role", "hit", "miss", "false_alarm")
    )
    assert set(advisory["lead_time_hours"]) == {24, 48, 72}
    verification = _read_json(BATCH / "verification/system_vs_llm_metrics.json")
    assert verification["truth_opened_only_after_lock"] is True
    assert (
        verification["prediction_lock_sha256"]
        == hashlib.sha256(advisory_path.read_bytes()).hexdigest()
    )
    assert len(verification["groups"]) == 4


def test_rebuilt_process_data_and_system_locks_are_complete() -> None:
    process = pd.read_csv(BATCH / "adm1_full_process_data.csv")
    assert len(process) == 957
    assert (
        process[["initial_time", "region_id", "lead_time_hours", "indicator"]].duplicated().sum()
        == 0
    )
    assert set(process["lead_time_hours"]) == {24, 48, 72}
    assert process["indicator"].nunique() == 11
    audit = _read_json(BATCH / "system_replay_audit.json")
    assert len(audit) == 4
    assert all(group["reference_decisions_reproduced"] for group in audit)
    assert sum(group["rows"] for group in audit) == 87
