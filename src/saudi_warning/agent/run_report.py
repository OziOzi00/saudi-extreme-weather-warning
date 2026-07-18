"""Generate an explicit post-event verification report from evaluation truth."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from saudi_warning.agent.evidence import build_evidence_packet
from saudi_warning.agent.output import (
    deterministic_agent_report,
    render_agent_report,
    validate_agent_report,
)


def _generation_mode(model: str) -> str:
    lowered = model.lower()
    if "terra" in lowered:
        return "openai_terra"
    if "luna" in lowered:
        return "openai_luna"
    raise ValueError("only Luna and Terra are allowed by the Agent report schema")


def _run_openai_with_guard(
    packet: dict[str, Any], model: str, escalation_model: str
) -> dict[str, Any]:
    from saudi_warning.agent.openai_runtime import generate_with_openai

    attempts = [model]
    if escalation_model and escalation_model != model:
        attempts.append(escalation_model)
    last_errors: list[str] = []
    for selected_model in attempts:
        report = generate_with_openai(packet, selected_model)
        report["generation_mode"] = _generation_mode(selected_model)
        errors = validate_agent_report(report, packet)
        if not errors:
            return report
        last_errors = errors
    raise ValueError("Agent output failed guardrails: " + "; ".join(last_errors))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--risk", type=Path, required=True)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("handoff/knowledge_graph/heavy_rain_evaluation_bundle.json"),
    )
    parser.add_argument("--mode", choices=["development", "formal"], default="formal")
    parser.add_argument(
        "--provider", choices=["auto", "deterministic", "openai"], default="auto"
    )
    parser.add_argument(
        "--model",
        default=os.getenv("SAUDI_WARNING_AGENT_MODEL", "gpt-5.6-luna"),
    )
    parser.add_argument(
        "--escalation-model",
        default=os.getenv("SAUDI_WARNING_AGENT_ESCALATION_MODEL", "gpt-5.6-terra"),
    )
    parser.add_argument("--output-json", type=Path, default=Path("outputs/agent_report.json"))
    parser.add_argument(
        "--output-markdown", type=Path, default=Path("outputs/agent_report.md")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    packet = build_evidence_packet(args.risk, args.bundle, mode=args.mode)
    api_available = bool(os.getenv("OPENAI_API_KEY"))
    if args.provider == "openai" and not api_available:
        raise SystemExit("OPENAI_API_KEY is not set; keep the key outside the repository")

    if args.provider == "deterministic" or (args.provider == "auto" and not api_available):
        report = deterministic_agent_report(packet)
    else:
        try:
            report = _run_openai_with_guard(packet, args.model, args.escalation_model)
        except Exception as exc:
            if args.provider == "openai":
                raise SystemExit(f"OpenAI Agent failed: {exc}") from exc
            print(f"OpenAI Agent unavailable; using deterministic fallback: {exc}")
            report = deterministic_agent_report(packet)

    errors = validate_agent_report(report, packet)
    if errors:
        raise SystemExit("invalid Agent report:\n- " + "\n- ".join(errors))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output_markdown.write_text(render_agent_report(report, packet), encoding="utf-8")
    print(f"wrote {args.output_json}")
    print(f"wrote {args.output_markdown}")
    print(f"generation_mode={report['generation_mode']}")


if __name__ == "__main__":
    main()
