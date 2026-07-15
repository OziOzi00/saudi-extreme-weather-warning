"""Run candidate rules against versioned MAZU-like ADM1 summaries."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from saudi_warning.risk.engine import (
    evaluate_all,
    load_rule,
    load_statistics,
    load_summaries,
    write_evidence_audit,
    write_results,
    write_threshold_audit,
)


def _is_formal_output(path: Path) -> bool:
    formal = (Path.cwd() / "handoff" / "risk_results").resolve()
    resolved = path.resolve()
    return resolved == formal or formal in resolved.parents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summaries",
        type=Path,
        default=Path("handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv"),
    )
    parser.add_argument(
        "--statistics",
        type=Path,
        default=Path("handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv"),
    )
    parser.add_argument(
        "--heavy-rule", type=Path, default=Path("configs/heavy_rain_rules_v1.yaml")
    )
    parser.add_argument(
        "--heat-rule", type=Path, default=Path("configs/heatwave_rules_v1.yaml")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("handoff/risk_dry_runs/results")
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=Path("handoff/risk_dry_runs/risk_evidence_audit.csv"),
    )
    parser.add_argument(
        "--threshold-audit-output",
        type=Path,
        default=Path("handoff/risk_dry_runs/candidate_threshold_audit.csv"),
    )
    parser.add_argument("--created-at", help="UTC ISO-8601 timestamp for reproducible artifacts")
    args = parser.parse_args()

    heavy_rule = load_rule(args.heavy_rule, "heavy_rain")
    heat_rule = load_rule(args.heat_rule, "heatwave")
    if _is_formal_output(args.output_dir):
        raise SystemExit("the draft runner cannot write into handoff/risk_results")

    created_at = args.created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    statistics = load_statistics(args.statistics)
    results = evaluate_all(
        load_summaries(args.summaries),
        statistics,
        heavy_rule,
        heat_rule,
        created_at,
    )
    write_results(results, args.output_dir)
    write_evidence_audit(results, args.audit_output)
    write_threshold_audit(statistics, heavy_rule, heat_rule, args.threshold_audit_output)
    print(f"wrote {len(results)} draft results to {args.output_dir}")
    print(args.audit_output)
    print(args.threshold_audit_output)


if __name__ == "__main__":
    main()
