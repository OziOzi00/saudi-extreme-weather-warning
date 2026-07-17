"""Generate validated frozen heatwave outputs for development cases only."""

from __future__ import annotations

import argparse
from pathlib import Path

from saudi_warning.risk.engine import (
    evaluate_all,
    load_rule,
    load_statistics,
    load_summaries,
    write_results,
)
from saudi_warning.risk.run_development_review import (
    ARTIFACT_CREATED_AT,
    build_review,
    read_development_cases,
    select_development_summaries,
)
from saudi_warning.risk.run_frozen_development import write_manifest
from saudi_warning.risk.validation import validate_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path("configs/case_catalog_candidates.csv")
    )
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
        "--heavy-rule", type=Path, default=Path("configs/heavy_rain_rules_v2.yaml")
    )
    parser.add_argument(
        "--heat-rule", type=Path, default=Path("configs/heatwave_rules_v2.yaml")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("handoff/risk_results/development_heatwave"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/formal_development_heatwave_risk_manifest.csv"),
    )
    parser.add_argument(
        "--schema", type=Path, default=Path("schemas/risk_result.schema.json")
    )
    parser.add_argument(
        "--regions", type=Path, default=Path("configs/region_registry.csv")
    )
    parser.add_argument("--created-at", default=ARTIFACT_CREATED_AT)
    args = parser.parse_args()

    heavy_rule = load_rule(args.heavy_rule, "heavy_rain")
    heat_rule = load_rule(args.heat_rule, "heatwave")
    if heat_rule["status"] != "frozen":
        raise ValueError("formal heatwave generation requires a frozen rule")
    cases = read_development_cases(args.catalog)
    summaries = select_development_summaries(load_summaries(args.summaries), cases)
    all_results = evaluate_all(
        summaries,
        load_statistics(args.statistics),
        heavy_rule,
        heat_rule,
        args.created_at,
    )
    reviewed_results, _ = build_review(cases, all_results)
    results = [result for result in reviewed_results if result["hazard"] == "heatwave"]
    if len(results) != 18 or {result["rule_status"] for result in results} != {"frozen"}:
        raise ValueError("expected 18 frozen development heatwave results")
    for result in results:
        result["verification"] = {
            "status": "development_evidence_available",
            "dataset_split": "development",
            "observation_source": "NOAA SSODv2 synchronous UTC daily summary",
            "pair_qc_status": "accepted",
            "continuous_metrics_file": (
                "handoff/weather_verification/development_continuous_metrics.csv"
            ),
            "rule_review_file": "handoff/risk_dry_runs/development_v2_rule_review.csv",
            "independent_test_status": "not_opened_rule_freeze_stage_only",
            "limitation": (
                "Development-only evidence; SSOD synoptic reports may miss the true "
                "daily extrema; this is not an independent performance claim."
            ),
        }
    write_results(results, args.output_dir, filename_prefix="risk")
    paths = sorted(args.output_dir.glob("*.json"))
    report = validate_paths(paths, args.schema, args.regions, require_frozen=True)
    failures = {path: errors for path, errors in report.items() if errors}
    if failures:
        raise ValueError(f"formal heatwave risk validation failed: {failures}")
    write_manifest(args.manifest, results, args.output_dir)
    print(f"wrote and validated {len(results)} frozen development heatwave results")
    print(args.output_dir)
    print(args.manifest)


if __name__ == "__main__":
    main()
