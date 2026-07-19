"""Luna/Terra supervisor for the restricted orchestration state machine."""

from __future__ import annotations

import json
import os
from typing import Literal

from agents import (
    Agent,
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    OpenAIResponsesModel,
    RunConfig,
    Runner,
    function_tool,
)
from pydantic import BaseModel

from saudi_warning.orchestration.workflow import ControlledWorkflow, STAGES


class OrchestrationResult(BaseModel):
    status: Literal["complete"]
    run_id: str
    completed_stage_count: int
    truth_accessed: Literal[False] = False
    summary_zh: str


def _model(model: str):
    kwargs: dict[str, str] = {
        "api_key": os.getenv("OPENAI_API_KEY", "construction-only-placeholder")
    }
    if os.getenv("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.environ["OPENAI_BASE_URL"].rstrip("/")
    client = AsyncOpenAI(**kwargs)
    mode = os.getenv("SAUDI_WARNING_AGENT_API_MODE", "responses")
    if mode == "responses":
        return OpenAIResponsesModel(model=model, openai_client=client)
    if mode == "chat_completions":
        return OpenAIChatCompletionsModel(model=model, openai_client=client)
    raise ValueError("unsupported Agent API mode")


def run_controller(workflow: ControlledWorkflow, model: str) -> dict:
    """Require the model to inspect and advance only through safe transitions."""
    calls: list[str] = []

    @function_tool
    def inspect_workflow() -> str:
        """Inspect stage statuses and the next permitted state transition."""
        calls.append("inspect")
        state = workflow.state()
        compact = {
            "run_id": workflow.request.run_id,
            "status": state["status"],
            "next_stage": workflow.next_stage(),
            "stages": {name: state["stages"][name]["status"] for name in STAGES},
            "truth_accessed": False,
        }
        return json.dumps(compact, ensure_ascii=False)

    @function_tool
    def advance_workflow() -> str:
        """Execute exactly the next legal stage, validate it, and persist resumable state."""
        result = workflow.advance()
        calls.append(str(result.get("completed_stage", "complete")))
        return json.dumps(result, ensure_ascii=False)

    agent = Agent(
        name="Saudi Extreme Weather Controlled Orchestrator",
        instructions=(
            "你是受控流程编排 Agent。先调用 inspect_workflow，然后反复调用 "
            "advance_workflow，直到 next_stage 为 null；最后再次检查并输出 complete。"
            "不得跳步、不得编造完成状态、不得要求任意 shell、不得修改风险规则，"
            "不得读取同期真值。任一工具报错时应停止并让运行保留 failed 状态。"
        ),
        model=_model(model),
        tools=[inspect_workflow, advance_workflow],
        output_type=OrchestrationResult,
    )
    result = Runner.run_sync(
        agent,
        "完成当前案例的全部受控编排步骤，并在最终状态检查通过后总结。",
        max_turns=30,
        run_config=RunConfig(
            workflow_name="saudi_extreme_weather_controlled_orchestrator",
            tracing_disabled=True,
        ),
    )
    state = workflow.state()
    if state["status"] != "complete" or workflow.next_stage() is not None:
        raise RuntimeError("controller claimed completion before the state machine completed")
    if not calls or "inspect" not in calls:
        raise RuntimeError("controller did not inspect workflow state")
    output = result.final_output.model_dump()
    if output["run_id"] != workflow.request.run_id:
        raise RuntimeError("controller returned a different run_id")
    output["controller_model"] = model
    output["tool_trace"] = calls
    return output
