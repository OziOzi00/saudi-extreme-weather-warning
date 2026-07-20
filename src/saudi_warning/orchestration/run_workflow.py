"""Run or resume the complete controlled GraphCast-to-Agent workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from saudi_warning.orchestration.controller_agent import run_controller
from saudi_warning.orchestration.workflow import ControlledWorkflow, WorkflowRequest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--initial-time", required=True)
    parser.add_argument("--hazard", choices=["heavy_rain", "heatwave"], required=True)
    parser.add_argument("--region-id", action="append", dest="region_ids", required=True)
    parser.add_argument("--focus-lead-time-hours", type=int, default=48)
    parser.add_argument("--model", default=os.getenv("SAUDI_WARNING_AGENT_MODEL", "gpt-5.6-luna"))
    parser.add_argument(
        "--escalation-model",
        default=os.getenv("SAUDI_WARNING_AGENT_ESCALATION_MODEL", "gpt-5.6-terra"),
    )
    parser.add_argument("--deterministic-controller", action="store_true")
    parser.add_argument("--cache-dir", default="data/raw/graphcast_2020")
    parser.add_argument("--mazu-dir", default="handoff/mazu_like")
    parser.add_argument("--output-root", default="handoff/orchestrator_runs")
    args = parser.parse_args()
    if not args.deterministic_controller and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for the orchestration Agent")
    request = WorkflowRequest(
        run_id=args.run_id,
        case_id=args.case_id,
        initial_time=args.initial_time,
        hazard=args.hazard,
        region_ids=tuple(dict.fromkeys(args.region_ids)),
        focus_lead_time_hours=args.focus_lead_time_hours,
        model=args.model,
        escalation_model=args.escalation_model,
        cache_dir=args.cache_dir,
        mazu_dir=args.mazu_dir,
        output_root=args.output_root,
    )
    workflow = ControlledWorkflow(args.root, request)
    if args.deterministic_controller:
        workflow.run_to_completion()
        controller = {
            "status": "complete",
            "mode": "deterministic_test_controller",
            "truth_accessed": False,
        }
    else:
        failures: list[str] = []
        controller = None
        for model in dict.fromkeys([args.model, args.escalation_model]):
            try:
                controller = run_controller(workflow, model)
                break
            except Exception as exc:
                failures.append(f"{model}: {type(exc).__name__}: {exc}")
                if workflow.state()["status"] == "failed":
                    break
        if controller is None:
            raise SystemExit("orchestration Agent failed: " + "; ".join(failures))
    controller_path = workflow.run_dir / "controller_result.json"
    controller_path.write_text(
        json.dumps(controller, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"run_status={workflow.state()['status']}")
    print(f"state={workflow.state_path}")
    print(f"manifest={workflow.run_dir / 'run_manifest.json'}")
    print("truth_accessed=false")


if __name__ == "__main__":
    main()
