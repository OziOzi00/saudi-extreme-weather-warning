import hashlib
import json
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator

from saudi_warning.orchestration.joint_inference import build_runtime_prediction_lock
from saudi_warning.orchestration.workflow import ControlledWorkflow, WorkflowRequest


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv"


def test_runtime_rain_inference_reproduces_locked_joint_decision(tmp_path: Path) -> None:
    output = tmp_path / "rain.csv"
    actual = build_runtime_prediction_lock(
        ROOT,
        summary_path=SUMMARY,
        hazard="heavy_rain",
        case_id="20200501_00",
        region_ids=["SA-09"],
        output_path=output,
    )
    expected = pd.read_csv(
        ROOT
        / "handoff/model_selection/joint_v2/locked_development_joint_heavy_rain_predictions.csv"
    )
    expected = expected[
        expected["case_id"].eq("20200501_00") & expected["region_id"].eq("SA-09")
    ]
    columns = [
        "lead_time_hours",
        "base_risk_level",
        "knowledge_triggered",
        "joint_final_risk_level",
        "support_count",
    ]
    pd.testing.assert_frame_equal(
        actual[columns].reset_index(drop=True),
        expected[columns].reset_index(drop=True),
        check_dtype=False,
    )
    assert not any(column.startswith("observed_") for column in actual.columns)


def test_runtime_heat_inference_reproduces_locked_joint_decision(tmp_path: Path) -> None:
    output = tmp_path / "heat.csv"
    actual = build_runtime_prediction_lock(
        ROOT,
        summary_path=SUMMARY,
        hazard="heatwave",
        case_id="20200729_00",
        region_ids=["SA-04"],
        output_path=output,
    )
    expected = pd.read_csv(
        ROOT / "handoff/model_selection/joint_v2/locked_joint_heatwave_predictions.csv"
    )
    expected = expected[
        expected["case_id"].eq("20200729_00") & expected["region_id"].eq("SA-04")
    ]
    columns = [
        "lead_time_hours",
        "base_risk_level",
        "knowledge_triggered",
        "joint_final_risk_level",
        "candidate_tmax_degc",
    ]
    pd.testing.assert_frame_equal(
        actual[columns].reset_index(drop=True),
        expected[columns].reset_index(drop=True),
        check_dtype=False,
    )
    assert not any(column.startswith("observed_") for column in actual.columns)


def test_workflow_state_is_resumable_and_request_is_immutable(tmp_path: Path) -> None:
    request = WorkflowRequest(
        run_id="unit-run",
        case_id="20200501_00",
        initial_time="2020-05-01T00:00:00Z",
        hazard="heavy_rain",
        region_ids=("SA-09",),
        output_root=str(tmp_path),
    )
    workflow = ControlledWorkflow(ROOT, request)
    result = workflow.advance()
    assert result["completed_stage"] == "preflight"
    assert workflow.next_stage() == "forecast_materialization"
    restored = ControlledWorkflow(ROOT, request)
    assert restored.next_stage() == "forecast_materialization"
    state = json.loads(restored.state_path.read_text(encoding="utf-8"))
    assert state["truth_accessed"] is False
    changed = WorkflowRequest(**{**request.__dict__, "hazard": "heatwave"})
    try:
        ControlledWorkflow(ROOT, changed)
    except ValueError as exc:
        assert "immutable request" in str(exc)
    else:
        raise AssertionError("run_id reuse with a changed request must fail")


def test_real_orchestrator_runs_are_complete_truth_free_and_hash_valid() -> None:
    state_schema = json.loads(
        (ROOT / "schemas/controlled_orchestrator_state_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    manifest_schema = json.loads(
        (ROOT / "schemas/controlled_orchestrator_run_manifest_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "20260719_rain_full_agent": ("gpt-5.6-luna", "openai_luna", "medium"),
        "20260719_heat_full_agent": ("gpt-5.6-terra", "openai_terra", "high"),
    }
    for run_id, (controller_model, generation_mode, risk_level) in expected.items():
        run_dir = ROOT / "handoff/orchestrator_runs" / run_id
        state = json.loads((run_dir / "workflow_state.json").read_text(encoding="utf-8"))
        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        controller = json.loads(
            (run_dir / "controller_result.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(state_schema).validate(state)
        Draft202012Validator(manifest_schema).validate(manifest)
        assert state["status"] == "complete"
        assert all(item["status"] == "completed" for item in state["stages"].values())
        assert manifest["truth_accessed"] is False
        assert controller["controller_model"] == controller_model
        assert controller["completed_stage_count"] == 8
        assert controller["tool_trace"][0] == controller["tool_trace"][-1] == "inspect"
        for artifact in manifest["artifacts"]:
            path = ROOT / artifact["path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
        report_paths = [
            path for path in run_dir.glob("*.json")
            if path.name.endswith("lead048.json")
        ]
        assert len(report_paths) == 1
        report = json.loads(report_paths[0].read_text(encoding="utf-8"))
        assert report["generation_mode"] == generation_mode
        assert report["joint_final_risk_level"] == risk_level
        assert report["neo4j_query_mode"] == "live_neo4j"
        assert report["truth_accessed"] is False
