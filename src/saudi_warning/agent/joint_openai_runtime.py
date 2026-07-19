"""Live Luna/Terra runtime for Neo4j-backed joint forecast reports."""

from __future__ import annotations

import json
import os
from typing import Any, Literal

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


class TimelineAnalysis(BaseModel):
    lead_time_hours: int
    base_risk_level: Literal["low", "medium", "high"]
    knowledge_triggered: bool
    joint_final_risk_level: Literal["low", "medium", "high"]
    signal_analysis_zh: str


class JointLiveReportModel(BaseModel):
    schema_version: Literal["agent_joint_forecast_report_v5"] = (
        "agent_joint_forecast_report_v5"
    )
    report_mode: Literal["joint_forecast_live"] = "joint_forecast_live"
    truth_accessed: Literal[False] = False
    neo4j_query_mode: Literal["live_neo4j"] = "live_neo4j"
    case_id: str
    region_id: str
    hazard: Literal["heavy_rain", "heatwave"]
    focus_lead_time_hours: int
    selected_joint_rule: str
    base_risk_level: Literal["low", "medium", "high"]
    knowledge_triggered: bool
    joint_final_risk_level: Literal["low", "medium", "high"]
    development_gate_passed: bool
    operating_status: Literal["research_candidate", "research_only_blocked"]
    formal_warning_allowed: Literal[False] = False
    generation_mode: Literal["openai_luna", "openai_terra"]
    executive_summary_zh: str
    timeline_analysis: list[TimelineAnalysis] = Field(default_factory=list)
    spatial_temporal_analysis_zh: str
    knowledge_graph_analysis_zh: str
    uncertainty_analysis_zh: str
    limitations_zh: list[str] = Field(default_factory=list)
    recommended_actions_zh: list[str] = Field(default_factory=list)
    provenance_summary_zh: str


REQUIRED_TOOL_CALLS = {
    "get_joint_decision",
    "get_neo4j_timeline",
    "get_method_status",
    "get_provenance",
    "get_forecast_constraints",
}


def _construct_agent(
    packet: dict[str, Any], model: str
) -> tuple[Agent, set[str]]:
    called: set[str] = set()

    @function_tool
    def get_joint_decision() -> str:
        """Return the immutable focus-window base and joint risk decision."""

        called.add("get_joint_decision")
        return json.dumps(packet["joint_decision"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_neo4j_timeline() -> str:
        """Return the live Neo4j 24/48/72-hour truth-free prediction timeline."""

        called.add("get_neo4j_timeline")
        return json.dumps(packet["neo4j_context"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_method_status() -> str:
        """Return development gate and operating-policy boundaries."""

        called.add("get_method_status")
        return json.dumps(packet["method_status"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_provenance() -> str:
        """Return prediction-lock, selection-lock, and live-query provenance."""

        called.add("get_provenance")
        return json.dumps(packet["provenance"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_forecast_constraints() -> str:
        """Return mandatory truth-sealing and non-overwrite constraints."""

        called.add("get_forecast_constraints")
        return json.dumps(packet["constraints"], ensure_ascii=False)

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
        raise ValueError("unsupported Agent API mode")
    instructions = """
你是沙特极端天气联合Forecast Agent，必须调用全部五个工具后输出结构化中文报告。
get_neo4j_timeline来自正在运行的Neo4j，而不是本地模板；必须分析24/48/72小时风险演变。
这是无真值预测模式：不得声称同期观测、真实灾害、伤亡、新闻、命中、漏报或事后验证结果。
基础风险、图谱是否触发、联合最终风险、规则、开发门槛和运行状态必须逐字保持工具事实。
大模型只负责综合解释，不得修改、升级或降级任何风险等级。
高温operating_status为research_only_blocked时，必须突出误报控制和独立对照不足，不能写成正式预警。
暴雨research_candidate也不是生产验证；必须说明图谱独立纠错增益仍需新案例验证。
timeline_analysis必须覆盖工具返回的全部lead，并保持每个lead的三项决策字段完全一致。
报告需要比字段翻译更有分析性：解释时间演变、证据组合、图谱贡献、不确定性和分级行动建议。
不得虚构Neo4j中不存在的区域、气象数值或来源。
""".strip()
    return (
        Agent(
            name="Saudi Joint Weather Live Neo4j Forecast Agent",
            instructions=instructions,
            model=sdk_model,
            tools=[
                get_joint_decision,
                get_neo4j_timeline,
                get_method_status,
                get_provenance,
                get_forecast_constraints,
            ],
            output_type=JointLiveReportModel,
        ),
        called,
    )


def generate_joint_report(packet: dict[str, Any], model: str) -> dict[str, Any]:
    agent, called = _construct_agent(packet, model)
    result = Runner.run_sync(
        agent,
        "查询全部受控工具，生成有时间演变、图谱贡献和不确定性分析的联合预测报告。",
        run_config=RunConfig(
            workflow_name="saudi_joint_weather_live_neo4j_forecast",
            tracing_disabled=True,
        ),
    )
    missing = sorted(REQUIRED_TOOL_CALLS - called)
    if missing:
        raise RuntimeError("Joint Agent skipped required tools: " + ", ".join(missing))
    if not isinstance(result.final_output, JointLiveReportModel):
        raise RuntimeError("Joint Agent returned an invalid structured output")
    return result.final_output.model_dump()
