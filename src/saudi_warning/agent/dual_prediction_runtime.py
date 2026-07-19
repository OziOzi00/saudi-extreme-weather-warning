"""Agent runtime with immutable system decisions and a separate LLM advisory forecast."""

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


RiskLevel = Literal["low", "medium", "high"]
Confidence = Literal["low", "medium", "high"]


class DualTimelineItem(BaseModel):
    lead_time_hours: int
    system_base_risk_level: RiskLevel
    system_knowledge_triggered: bool
    system_joint_final_risk_level: RiskLevel
    llm_advisory_risk_level: RiskLevel
    llm_advisory_confidence: Confidence
    agreement_with_system: bool
    advisory_analysis_zh: str
    key_signals_zh: list[str] = Field(default_factory=list)


class DualPredictionReport(BaseModel):
    schema_version: Literal["agent_dual_prediction_report_v1"] = "agent_dual_prediction_report_v1"
    report_mode: Literal["system_plus_llm_advisory"] = "system_plus_llm_advisory"
    truth_accessed: Literal[False] = False
    case_id: str
    region_id: str
    hazard: Literal["heavy_rain", "heatwave"]
    dataset_split: Literal["development", "independent_test"]
    focus_lead_time_hours: int
    selected_joint_rule: str
    development_gate_passed: bool
    operating_status: Literal["research_candidate", "research_only_blocked"]
    formal_warning_allowed: Literal[False] = False
    system_focus_risk_level: RiskLevel
    llm_focus_advisory_risk_level: RiskLevel
    llm_focus_confidence: Confidence
    focus_agreement: bool
    system_analysis_zh: str
    llm_advisory_summary_zh: str
    comparison_analysis_zh: str
    timeline_analysis: list[DualTimelineItem] = Field(default_factory=list)
    uncertainty_analysis_zh: str
    limitations_zh: list[str] = Field(default_factory=list)
    recommended_actions_zh: list[str] = Field(default_factory=list)
    provenance_summary_zh: str


REQUIRED_TOOLS = {
    "get_immutable_system_timeline",
    "get_full_forecast_indicators",
    "get_joint_method_status",
    "get_provenance",
    "get_prediction_constraints",
}


def _sdk_model(model: str):
    kwargs: dict[str, str] = {
        "api_key": os.getenv("OPENAI_API_KEY", "construction-only-placeholder")
    }
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url.rstrip("/")
    client = AsyncOpenAI(**kwargs)
    mode = os.getenv("SAUDI_WARNING_AGENT_API_MODE", "responses")
    if mode == "responses":
        return OpenAIResponsesModel(model=model, openai_client=client)
    if mode == "chat_completions":
        return OpenAIChatCompletionsModel(model=model, openai_client=client)
    raise ValueError("unsupported Agent API mode")


def generate_dual_prediction_report(packet: dict[str, Any], model: str) -> dict[str, Any]:
    """Generate a second forecast opinion without changing the system forecast."""
    called: set[str] = set()

    @function_tool
    def get_immutable_system_timeline() -> str:
        """Return immutable base, graph-trigger, and final system risks for all leads."""
        called.add("get_immutable_system_timeline")
        return json.dumps(packet["system_timeline"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_full_forecast_indicators() -> str:
        """Return truth-free MAZU-like ADM1 indicators for all forecast windows."""
        called.add("get_full_forecast_indicators")
        return json.dumps(packet["forecast_indicators"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_joint_method_status() -> str:
        """Return selected method, development metrics, and operating boundary."""
        called.add("get_joint_method_status")
        return json.dumps(packet["method_status"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_provenance() -> str:
        """Return prediction-lock, selection-lock, source, and Neo4j provenance."""
        called.add("get_provenance")
        return json.dumps(packet["provenance"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_prediction_constraints() -> str:
        """Return truth isolation and report separation constraints."""
        called.add("get_prediction_constraints")
        return json.dumps(packet["constraints"], ensure_ascii=False)

    agent = Agent(
        name="Saudi Weather System plus Independent LLM Advisory Agent",
        instructions=(
            "你必须调用全部五个工具。报告包含两条严格分离的预测：第一条逐字保存系统联合预测，"
            "不得修改；第二条是你仅依据预测时可用的完整MAZU-like指标、三窗口变化、图谱上下文"
            "和方法边界独立形成的LLM综合预测意见。LLM意见可以与系统不同，但必须逐窗口给出"
            "low/medium/high、置信度、关键指标和理由。不得读取、猜测或暗示同期观测、事件/对照"
            "标签、命中、漏报、误报、灾害新闻或事后答案。agreement_with_system必须准确反映两"
            "个风险等级是否相同。高温research_only_blocked时，即使LLM意见为high，也不能授权"
            "正式预警。分析必须解释24/48/72小时演变、系统与LLM分歧、不确定性和适用边界。"
        ),
        model=_sdk_model(model),
        tools=[
            get_immutable_system_timeline,
            get_full_forecast_indicators,
            get_joint_method_status,
            get_provenance,
            get_prediction_constraints,
        ],
        output_type=DualPredictionReport,
    )
    result = Runner.run_sync(
        agent,
        "读取全部受控预测工具，保留系统结果，并形成可单独评分的LLM独立综合预测意见。",
        max_turns=12,
        run_config=RunConfig(
            workflow_name="saudi_system_plus_llm_advisory_prediction",
            tracing_disabled=True,
        ),
    )
    missing = sorted(REQUIRED_TOOLS - called)
    if missing:
        raise RuntimeError("dual prediction Agent skipped required tools: " + ", ".join(missing))
    return result.final_output.model_dump()
