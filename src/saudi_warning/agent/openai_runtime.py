"""Optional OpenAI Agents SDK runtime, imported only when explicitly used."""

from __future__ import annotations

import json
import os
from typing import Any, Literal

try:
    from agents import (
        Agent,
        AsyncOpenAI,
        OpenAIChatCompletionsModel,
        OpenAIResponsesModel,
        RunConfig,
        Runner,
        function_tool,
    )
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - depends on optional environment
    raise RuntimeError(
        'OpenAI Agent dependencies are missing; run: pip install -e ".[agent]"'
    ) from exc


class AgentReportModel(BaseModel):
    schema_version: Literal["agent_report_v1"] = "agent_report_v1"
    case_id: str
    region_id: str
    hazard: Literal["heavy_rain", "heatwave"]
    risk_level: Literal["low", "medium", "high"]
    risk_score: float
    confidence: Literal["low", "medium", "high"]
    rule_id: str
    rule_status: Literal["draft", "frozen", "example"]
    status_disclosure_zh: str
    executive_summary_zh: str
    evidence_summary_zh: str
    limitations_zh: list[str] = Field(default_factory=list)
    recommended_actions_zh: list[str] = Field(default_factory=list)
    cited_source_ids: list[str] = Field(default_factory=list)


REQUIRED_TOOL_CALLS = {
    "get_risk_result",
    "get_case_trace",
    "get_region_context",
    "get_verification_status",
    "get_reporting_constraints",
}


def _construct_openai_agent(packet: dict[str, Any], model: str) -> tuple[Agent, set[str]]:
    called_tools: set[str] = set()

    risk = packet["risk"]
    graph = packet["graph"]

    @function_tool
    def get_risk_result() -> str:
        """Return the immutable Risk JSON. Never change its protected fields."""

        called_tools.add("get_risk_result")
        return json.dumps(risk, ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_case_trace() -> str:
        """Return the selected forecast case, events, impacts, and source records."""

        called_tools.add("get_case_trace")
        return json.dumps(
            {
                "case": graph["case"],
                "events": graph["events"],
                "impact_records": graph["impact_records"],
                "sources": graph["sources"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @function_tool
    def get_region_context() -> str:
        """Return versioned region metadata and related historical case summaries."""

        called_tools.add("get_region_context")
        return json.dumps(
            {
                "region": graph["region"],
                "region_case_context": graph["region_case_context"],
                "neo4j_live_verification": graph["neo4j_live_verification"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @function_tool
    def get_verification_status() -> str:
        """Return weather verification exactly as recorded in Risk JSON."""

        called_tools.add("get_verification_status")
        return json.dumps(risk.get("verification"), ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_reporting_constraints() -> str:
        """Return mandatory reporting boundaries that must appear in the report."""

        called_tools.add("get_reporting_constraints")
        return json.dumps(packet["boundaries"], ensure_ascii=False)

    instructions = """
你是沙特极端天气项目的只读综合报告Agent。你必须调用全部五个工具后再输出。
Risk JSON是唯一的风险等级、分数、置信度、阈值和规则状态权威来源，不得修改。
图谱只用于补充区域、历史事件、影响证据、来源和验证边界，不得用历史事件覆盖风险等级。
unknown表示证据不足，不得写成没有影响。不得虚构来源，cited_source_ids只能使用工具返回的source_id。
必须明确区分历史回放、development和正式业务预警。输出简洁中文，避免给出未经来源支持的新数值。
""".strip()
    client_kwargs: dict[str, str] = {
        "api_key": os.getenv("OPENAI_API_KEY", "construction-only-placeholder")
    }
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        client_kwargs["base_url"] = base_url.rstrip("/")
    client = AsyncOpenAI(**client_kwargs)
    api_mode = os.getenv("SAUDI_WARNING_AGENT_API_MODE", "responses")
    if api_mode == "responses":
        sdk_model = OpenAIResponsesModel(model=model, openai_client=client)
    elif api_mode == "chat_completions":
        sdk_model = OpenAIChatCompletionsModel(model=model, openai_client=client)
    else:
        raise ValueError(
            "SAUDI_WARNING_AGENT_API_MODE must be responses or chat_completions"
        )

    return (
        Agent(
            name="Saudi Weather Controlled Report Agent",
            instructions=instructions,
            model=sdk_model,
            tools=[
                get_risk_result,
                get_case_trace,
                get_region_context,
                get_verification_status,
                get_reporting_constraints,
            ],
            output_type=AgentReportModel,
        ),
        called_tools,
    )


def build_openai_agent(packet: dict[str, Any], model: str) -> Agent:
    """Construct the SDK Agent without making a network request."""

    agent, _ = _construct_openai_agent(packet, model)
    return agent


def generate_with_openai(packet: dict[str, Any], model: str) -> dict[str, Any]:
    """Run one read-only reporting Agent and return its structured output."""

    agent, called_tools = _construct_openai_agent(packet, model)
    result = Runner.run_sync(
        agent,
        "读取全部受控工具，为当前案例生成一份结构化综合报告。",
        run_config=RunConfig(
            workflow_name="saudi_extreme_weather_controlled_report",
            tracing_disabled=True,
        ),
    )
    output = result.final_output
    missing_tools = sorted(REQUIRED_TOOL_CALLS - called_tools)
    if missing_tools:
        raise RuntimeError("Agent skipped required tools: " + ", ".join(missing_tools))
    if not isinstance(output, AgentReportModel):
        raise RuntimeError("Agent did not return the required structured output")
    return output.model_dump()
