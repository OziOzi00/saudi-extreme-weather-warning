"""CLI for a live Neo4j-backed report from a runtime prediction lock."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from saudi_warning.orchestration.runtime_report import (
    build_runtime_packet,
    generate_runtime_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--prediction-lock", type=Path, required=True)
    parser.add_argument("--hazard", choices=["heavy_rain", "heatwave"], required=True)
    parser.add_argument("--runtime-namespace", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--region-id", required=True)
    parser.add_argument("--lead-time-hours", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--escalation-model", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()
    missing = [name for name in ("OPENAI_API_KEY", "NEO4J_PASSWORD") if not os.getenv(name)]
    if missing:
        raise SystemExit("missing runtime secrets: " + ", ".join(missing))
    root = args.root.resolve()
    prediction_lock = args.prediction_lock
    if not prediction_lock.is_absolute():
        prediction_lock = root / prediction_lock
    packet = build_runtime_packet(
        root,
        prediction_lock=prediction_lock,
        hazard=args.hazard,
        runtime_namespace=args.runtime_namespace,
        case_id=args.case_id,
        region_id=args.region_id,
        lead_time_hours=args.lead_time_hours,
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.environ["NEO4J_PASSWORD"],
    )
    _, used_model = generate_runtime_report(
        packet,
        models=[args.model, args.escalation_model],
        output_json=args.output_json,
        output_markdown=args.output_markdown,
        evidence_output=args.evidence_output,
    )
    print(f"model={used_model}")
    print("neo4j_query_mode=live_neo4j")
    print("truth_accessed=false")


if __name__ == "__main__":
    main()
