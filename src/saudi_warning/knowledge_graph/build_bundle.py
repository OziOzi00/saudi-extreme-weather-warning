"""CLI for validating member-C inputs and writing a Neo4j import bundle."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .bundle import build_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", type=Path, default=Path("configs/region_registry.csv"))
    parser.add_argument(
        "--cases", type=Path, default=Path("configs/case_catalog_candidates.csv")
    )
    parser.add_argument(
        "--truth",
        type=Path,
        default=Path("handoff/disaster_truth/disaster_impact_truth.csv"),
    )
    parser.add_argument(
        "--sources", type=Path, default=Path("handoff/disaster_truth/source_catalog.csv")
    )
    parser.add_argument(
        "--risk",
        type=Path,
        action="append",
        default=None,
        help="Risk JSON file or directory; repeat to include multiple inputs.",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("handoff/knowledge_graph/import_bundle.json")
    )
    parser.add_argument("--generated-at", help="UTC timestamp override for reproducible builds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generated_at = args.generated_at or (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    risk_paths = args.risk or [Path("handoff/risk_results/example_risk_result.json")]
    bundle = build_bundle(
        args.regions,
        args.cases,
        args.truth,
        args.sources,
        risk_paths,
        generated_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(content, encoding="utf-8")
    print(
        f"wrote {args.output}: {len(bundle['nodes'])} nodes, "
        f"{len(bundle['relations'])} relations"
    )


if __name__ == "__main__":
    main()
