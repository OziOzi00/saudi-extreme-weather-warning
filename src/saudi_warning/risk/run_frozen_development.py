"""Generate validated frozen-rule outputs for development cases only."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
from typing import Any

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
from saudi_warning.risk.validation import validate_paths


MANIFEST_FIELDS = [
    "file",
    "sha256",
    "prediction_case_id",
    "initial_time",
    "lead_time_hours",
    "region_id",
    "hazard",
    "risk_level",
    "rule_id",
    "rule_status",
    "dataset_split",
    "validation_status",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    path: Path, results: list[dict[str, Any]], output_dir: Path
) -> None:
    rows: list[dict[str, Any]] = []
    for result in results:
        result_path = output_dir / (
            f"risk_{result['case_id']}_{result['region_id']}_{result['hazard']}.json"
        )
        rows.append(
            {
                "file": result_path.as_posix(),
                "sha256": _sha256(result_path),
                "prediction_case_id": result["case_id"],
                "initial_time": result["initial_time"],
                "lead_time_hours": result["lead_time_hours"],
                "region_id": result["region_id"],
                "hazard": result["hazard"],
                "risk_level": result["risk_level"],
                "rule_id": result["rule_id"],
                "rule_status": result["rule_status"],
                "dataset_split": "development",
                "validation_status": "passed",
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


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
        default=Path("handoff/risk_results/development_heavy_rain"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/formal_development_risk_manifest.csv"),
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
    if heavy_rule["status"] != "frozen":
        raise ValueError("formal heavy-rain generation requires a frozen rule")
    if heat_rule["status"] == "frozen":
        raise ValueError("this runner must be updated before formal heatwave generation")
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
    results = [result for result in reviewed_results if result["rule_status"] == "frozen"]
    if len(results) != 15 or {result["hazard"] for result in results} != {"heavy_rain"}:
        raise ValueError("expected 15 frozen development heavy-rain results")
    for result in results:
        result["verification"] = {
            "status": "development_evidence_available",
            "dataset_split": "development",
            "observation_source": "IMERG Final Run V07B",
            "pair_qc_status": "accepted",
            "continuous_metrics_file": (
                "handoff/weather_verification/development_continuous_metrics.csv"
            ),
            "rule_review_file": "handoff/risk_dry_runs/development_v2_rule_review.csv",
            "independent_test_status": "not_opened_missing_four_imerg_dates",
            "limitation": "development-only evidence; not an independent performance claim",
        }
    write_results(results, args.output_dir, filename_prefix="risk")
    paths = sorted(args.output_dir.glob("*.json"))
    report = validate_paths(paths, args.schema, args.regions, require_frozen=True)
    failures = {path: errors for path, errors in report.items() if errors}
    if failures:
        raise ValueError(f"formal risk validation failed: {failures}")
    write_manifest(args.manifest, results, args.output_dir)
    print(f"wrote and validated {len(results)} frozen development results")
    print(args.output_dir)
    print(args.manifest)


if __name__ == "__main__":
    main()
