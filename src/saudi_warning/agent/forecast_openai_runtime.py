"""Optional OpenAI runtime for truth-sealed forecast reports."""

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
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        'OpenAI Agent dependencies are missing; run: pip install -e ".[agent]"'
    ) from exc


class ForecastReportModel(BaseModel):
    schema_version: Literal["agent_forecast_report_v2"] = "agent_forecast_report_v2"
    report_mode: Literal["forecast"] = "forecast"
    truth_accessed: Literal[False] = False
    case_id: str
    region_id: str
    hazard: Literal["heavy_rain", "heatwave"]
    risk_level: Literal["low", "medium", "high"]
    risk_score: float
    confidence: Literal["low", "medium", "high"]
    rule_id: str
    rule_status: Literal["draft", "frozen", "example"]
    knowledge_prior_status: Literal["not_available", "context_only", "available"]
    knowledge_prior_risk: Literal["low", "medium", "high"] | None
    conflict_flag: Literal[
        "none",
        "possible_underestimation",
        "possible_overestimation",
        "insufficient_primary_evidence",
        "spatial_scale_mismatch",
        "duration_state_uncertain",
    ]
    attention_level: Literal["routine", "watch", "urgent"]
    status_disclosure_zh: str
    executive_summary_zh: str
    weather_evidence_zh: str
    knowledge_context_zh: str
    limitations_zh: list[str] = Field(default_factory=list)
    recommended_actions_zh: list[str] = Field(default_factory=list)
    cited_prior_source_ids: list[str] = Field(default_factory=list)


REQUIRED_TOOL_CALLS = {
    "get_forecast_risk",
    "get_prediction_context",
    "get_knowledge_prior",
    "get_consistency_check",
    "get_forecast_constraints",
}


def _model(packet: dict[str, Any], model: str) -> tuple[Agent, set[str]]:
    called: set[str] = set()

    @function_tool
    def get_forecast_risk() -> str:
        """Return immutable forecast facts with post-event verification removed."""

        called.add("get_forecast_risk")
        return json.dumps(packet["risk"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_prediction_context() -> str:
        """Return only the truth-sealed forecast window, region, and rule context."""

        called.add("get_prediction_context")
        return json.dumps(
            {
                "temporal_mode": packet["temporal_mode"],
                "knowledge_cutoff": packet["knowledge_cutoff"],
                "truth_accessed": packet["truth_accessed"],
                "case": packet["graph"]["case"],
                "window": packet["graph"]["window"],
                "region": packet["graph"]["region"],
                "rule": packet["graph"]["rule"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @function_tool
    def get_knowledge_prior() -> str:
        """Return pre-cutoff knowledge prior status; never substitute evaluation truth."""

        called.add("get_knowledge_prior")
        return json.dumps(packet["knowledge_prior"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_consistency_check() -> str:
        """Return the deterministic candidate consistency check without changing risk."""

        called.add("get_consistency_check")
        return json.dumps(
            packet["consistency_check"], ensure_ascii=False, sort_keys=True
        )

    @function_tool
    def get_forecast_constraints() -> str:
        """Return mandatory truth-sealing and reporting constraints."""

        called.add("get_forecast_constraints")
        return json.dumps(packet["boundaries"], ensure_ascii=False)

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
    instructions = """
你是沙特极端天气Forecast Agent。必须调用全部五个工具后输出。
这是无真值预测模式：工具中没有且不得推测同期观测、真实灾害、伤亡、影响、新闻或事后验证。
Risk JSON预测视图是风险等级、分数、置信度和规则状态的唯一权威，不得修改。
knowledge_prior为not_available时必须明确说明先验不足，不能用常识或同期事件补造。
knowledge_prior为context_only时只能解释区域地形和长期月气候背景，必须保持risk为null，不能把静态背景写成具体事件预测。
consistency_check中的possible_underestimation已因development误关注过多而降级为diagnostic_only；
必须保留工具给出的effective attention_level，不能把候选watch写成默认关注级别，也不能证明模型错误。
必须说明这是MAZU 2025方法参考到2020案例的迁移回放，不是实时业务预警。
cited_prior_source_ids只能使用工具明确返回的预测前来源；当前为空时必须返回空数组。
knowledge_prior为context_only时，cited_prior_source_ids必须完整复制工具返回的全部source_ids，不能漏引。
输出简洁、审慎的中文预测报告。
""".strip()
    return (
        Agent(
            name="Saudi Weather Truth-Sealed Forecast Agent",
            instructions=instructions,
            model=sdk_model,
            tools=[
                get_forecast_risk,
                get_prediction_context,
                get_knowledge_prior,
                get_consistency_check,
                get_forecast_constraints,
            ],
            output_type=ForecastReportModel,
        ),
        called,
    )


def build_forecast_openai_agent(packet: dict[str, Any], model: str) -> Agent:
    agent, _ = _model(packet, model)
    return agent


def generate_forecast_with_openai(packet: dict[str, Any], model: str) -> dict[str, Any]:
    agent, called = _model(packet, model)
    result = Runner.run_sync(
        agent,
        "读取全部受控工具，生成一份无真值极端天气预测报告。",
        run_config=RunConfig(
            workflow_name="saudi_weather_truth_sealed_forecast",
            tracing_disabled=True,
        ),
    )
    missing = sorted(REQUIRED_TOOL_CALLS - called)
    if missing:
        raise RuntimeError("Forecast Agent skipped required tools: " + ", ".join(missing))
    if not isinstance(result.final_output, ForecastReportModel):
        raise RuntimeError("Forecast Agent did not return the required structured output")
    return result.final_output.model_dump()
