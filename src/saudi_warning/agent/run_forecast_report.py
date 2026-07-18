"""Generate one truth-sealed forecast report without evaluation truth."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from saudi_warning.agent.forecast_evidence import build_forecast_evidence_packet
from saudi_warning.agent.forecast_output import (
    deterministic_forecast_report,
    render_forecast_report,
    validate_forecast_report,
)


def _generation_mode(model: str) -> str:
    lowered = model.lower()
    if "terra" in lowered:
        return "openai_terra"
    if "luna" in lowered:
        return "openai_luna"
    raise ValueError("only Luna and Terra are allowed")


def _run_openai(packet: dict[str, Any], model: str, escalation: str) -> dict[str, Any]:
    from saudi_warning.agent.forecast_openai_runtime import (
        generate_forecast_with_openai,
    )

    errors: list[str] = []
    for selected in dict.fromkeys([model, escalation]):
        if not selected:
            continue
        report = generate_forecast_with_openai(packet, selected)
        report["generation_mode"] = _generation_mode(selected)
        errors = validate_forecast_report(report, packet)
        if not errors:
            return report
    raise ValueError("Forecast Agent output failed guardrails: " + "; ".join(errors))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--risk", type=Path, required=True)
    parser.add_argument(
        "--provider", choices=["auto", "deterministic", "openai"], default="auto"
    )
    parser.add_argument(
        "--model", default=os.getenv("SAUDI_WARNING_AGENT_MODEL", "gpt-5.6-luna")
    )
    parser.add_argument(
        "--escalation-model",
        default=os.getenv("SAUDI_WARNING_AGENT_ESCALATION_MODEL", "gpt-5.6-terra"),
    )
    parser.add_argument("--generated-at")
    parser.add_argument(
        "--output-json", type=Path, default=Path("outputs/forecast_report.json")
    )
    parser.add_argument(
        "--output-markdown", type=Path, default=Path("outputs/forecast_report.md")
    )
    parser.add_argument(
        "--bundle-output",
        type=Path,
        default=Path("outputs/prediction_context_bundle.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generated_at = args.generated_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    packet = build_forecast_evidence_packet(args.risk, generated_at=generated_at)
    api_available = bool(os.getenv("OPENAI_API_KEY"))
    if args.provider == "openai" and not api_available:
        raise SystemExit("OPENAI_API_KEY is not set; keep the key outside the repository")
    if args.provider == "deterministic" or (args.provider == "auto" and not api_available):
        report = deterministic_forecast_report(packet)
    else:
        try:
            report = _run_openai(packet, args.model, args.escalation_model)
        except Exception as exc:
            if args.provider == "openai":
                raise SystemExit(f"Forecast Agent failed: {exc}") from exc
            print(f"Forecast Agent unavailable; using deterministic fallback: {exc}")
            report = deterministic_forecast_report(packet)
    errors = validate_forecast_report(report, packet)
    if errors:
        raise SystemExit("invalid forecast report:\n- " + "\n- ".join(errors))
    for path in (args.output_json, args.output_markdown, args.bundle_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output_markdown.write_text(
        render_forecast_report(report, packet), encoding="utf-8"
    )
    args.bundle_output.write_text(
        json.dumps(packet["graph"]["bundle"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output_json}")
    print(f"wrote {args.output_markdown}")
    print(f"wrote {args.bundle_output}")
    print(f"generation_mode={report['generation_mode']}")
    print("truth_accessed=false")


if __name__ == "__main__":
    main()
