"""Run a development-only Agent diagnosis of the blocked heatwave rule."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
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


ARTIFACTS = {
    "rule": Path("configs/heatwave_rules_v2.yaml"),
    "bias_cv": Path("manifests/heatwave_bias_cv_v2_assessment.csv"),
    "diagnostic": Path("manifests/heatwave_development_diagnostic_summary.json"),
    "prospective": Path("manifests/heatwave_v3_prospective_assessment.json"),
    "prospective_details": Path(
        "handoff/weather_verification/heatwave_v3_prospective_details.csv"
    ),
}


class HeatwaveResearchReport(BaseModel):
    schema_version: Literal["heatwave_agent_research_v1"] = "heatwave_agent_research_v1"
    current_status: Literal["draft_blocked"]
    root_causes_zh: list[str] = Field(min_length=1)
    evidence_findings_zh: list[str] = Field(min_length=1)
    proposed_next_method_zh: str
    preregistration_requirements_zh: list[str] = Field(min_length=1)
    prohibited_actions_zh: list[str] = Field(min_length=1)
    new_data_requirements_zh: list[str] = Field(min_length=1)
    success_criteria_zh: list[str] = Field(min_length=1)
    can_freeze_now: Literal[False]
    can_open_independent_heatwave: Literal[False]
    artifact_citations: list[str] = Field(min_length=1)


def _load_inputs() -> dict[str, Any]:
    rule = yaml.safe_load(ARTIFACTS["rule"].read_text(encoding="utf-8"))
    with ARTIFACTS["bias_cv"].open(encoding="utf-8", newline="") as stream:
        bias_cv = next(csv.DictReader(stream))
    diagnostic = json.loads(ARTIFACTS["diagnostic"].read_text(encoding="utf-8"))
    prospective = json.loads(ARTIFACTS["prospective"].read_text(encoding="utf-8"))
    with ARTIFACTS["prospective_details"].open(encoding="utf-8", newline="") as stream:
        details = list(csv.DictReader(stream))
    if rule.get("status") != "draft" or rule.get("freeze_decision", {}).get(
        "independent_heatwave_opened"
    ) is not False:
        raise ValueError("heatwave v2 status boundary changed")
    if prospective.get("recommendation") != "keep_blocked":
        raise ValueError("prospective assessment no longer says keep_blocked")
    if prospective.get("independent_heatwave_opened") is not False:
        raise ValueError("independent heatwave was unexpectedly opened")
    return {
        "rule": rule,
        "bias_cv": bias_cv,
        "diagnostic": diagnostic,
        "prospective": prospective,
        "prospective_details": details,
    }


def _sdk_model(model: str) -> Any:
    kwargs = {"api_key": os.environ["OPENAI_API_KEY"]}
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


def run_research(model: str) -> dict[str, Any]:
    inputs = _load_inputs()
    calls: set[str] = set()

    @function_tool
    def get_current_rule() -> str:
        """Return the current draft heatwave rule and frozen decision boundaries."""

        calls.add("get_current_rule")
        return json.dumps(inputs["rule"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_bias_cross_validation() -> str:
        """Return the latest development-only additive-bias cross-validation."""

        calls.add("get_bias_cross_validation")
        return json.dumps(inputs["bias_cv"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_error_diagnostic() -> str:
        """Return error attribution and aggregation sensitivity diagnostics."""

        calls.add("get_error_diagnostic")
        return json.dumps(inputs["diagnostic"], ensure_ascii=False, sort_keys=True)

    @function_tool
    def get_prospective_failure() -> str:
        """Return the locked prospective assessment and per-window details."""

        calls.add("get_prospective_failure")
        return json.dumps(
            {
                "assessment": inputs["prospective"],
                "details": inputs["prospective_details"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @function_tool
    def get_research_constraints() -> str:
        """Return non-negotiable anti-leakage constraints for the next method."""

        calls.add("get_research_constraints")
        return json.dumps(
            [
                "不得读取或使用独立高温案例调参。",
                "不得在已看结果的SA-08前瞻案例上继续搜索权重或降低阈值。",
                "下一方法必须先预注册，再读取新的GraphCast development预报。",
                "事件窗口覆盖、观测高温日检出和观测非高温日正确否定必须分开报告。",
                "Agent只能提出研究方案，不能把draft规则改写为frozen。",
            ],
            ensure_ascii=False,
        )

    agent = Agent(
        name="Heatwave Development Research Agent",
        model=_sdk_model(model),
        instructions=(
            "你是气象验证研究Agent，只分析development证据。必须调用全部五个工具。"
            "请区分数值天气误差、空间聚合代理差异、连续日状态误差和事件标签误差。"
            "提出一个可预注册、可用新development案例验证的方法，不得为了覆盖已知漏报而降阈值，"
            "不得打开独立高温集，不得宣称已经解决或可冻结。artifact_citations只能从以下五项原样选择："
            + "、".join(path.as_posix() for path in ARTIFACTS.values())
            + "。即使工具内容提到其他路径，也不得引用那些未读取文件。"
        ),
        tools=[
            get_current_rule,
            get_bias_cross_validation,
            get_error_diagnostic,
            get_prospective_failure,
            get_research_constraints,
        ],
        output_type=HeatwaveResearchReport,
    )
    result = Runner.run_sync(
        agent,
        "诊断当前高温漏报的根因，并给出下一轮严谨、可验证的解决方案。",
        run_config=RunConfig(
            workflow_name="saudi_heatwave_development_research",
            tracing_disabled=True,
        ),
    )
    required = {
        "get_current_rule",
        "get_bias_cross_validation",
        "get_error_diagnostic",
        "get_prospective_failure",
        "get_research_constraints",
    }
    if missing := sorted(required - calls):
        raise RuntimeError("research Agent skipped required tools: " + ", ".join(missing))
    if not isinstance(result.final_output, HeatwaveResearchReport):
        raise RuntimeError("research Agent returned an invalid output type")
    output = result.final_output.model_dump()
    allowed = {path.as_posix() for path in ARTIFACTS.values()}
    unknown = sorted(set(output["artifact_citations"]) - allowed)
    if unknown:
        raise RuntimeError("research Agent cited unknown artifacts: " + ", ".join(unknown))
    output["generation_model"] = model
    output["independent_heatwave_accessed"] = False
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=os.getenv("SAUDI_WARNING_AGENT_MODEL", "gpt-5.6-luna")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/heatwave_agent_research.json")
    )
    args = parser.parse_args()
    output = run_research(args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
