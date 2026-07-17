"""Run the descriptive positive-impact coverage evaluation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .impact import (
    build_positive_units,
    load_risks,
    read_csv,
    risk_set_sha256,
    sha256,
    summarize,
    write_units,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--truth",
        type=Path,
        default=Path("handoff/disaster_truth/disaster_impact_truth.csv"),
    )
    parser.add_argument(
        "--catalog", type=Path, default=Path("configs/case_catalog_candidates.csv")
    )
    parser.add_argument(
        "--development-risk",
        type=Path,
        default=Path("handoff/risk_results/development_heavy_rain"),
    )
    parser.add_argument(
        "--independent-risk",
        type=Path,
        default=Path("handoff/risk_results/independent_heavy_rain"),
    )
    parser.add_argument(
        "--units-output",
        type=Path,
        default=Path("handoff/impact_verification/positive_impact_units.csv"),
    )
    parser.add_argument(
        "--assessment-output",
        type=Path,
        default=Path("manifests/impact_layer_assessment.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    truth = read_csv(args.truth)
    catalog = read_csv(args.catalog)
    risks = load_risks(
        [
            (args.development_risk, "development"),
            (args.independent_risk, "independent_test"),
        ]
    )
    units = build_positive_units(truth, catalog, risks)
    assessment = summarize(units, truth)
    assessment["generated_at"] = datetime.now(timezone.utc).isoformat()
    assessment["inputs"] = {
        "truth": {"path": args.truth.as_posix(), "sha256": sha256(args.truth)},
        "catalog": {"path": args.catalog.as_posix(), "sha256": sha256(args.catalog)},
        "development_risk_directory": args.development_risk.as_posix(),
        "independent_risk_directory": args.independent_risk.as_posix(),
        "frozen_risk_result_count": len(risks),
        "frozen_risk_result_set_sha256": risk_set_sha256(risks),
    }
    assessment["units_output"] = args.units_output.as_posix()
    write_units(args.units_output, units)
    args.assessment_output.parent.mkdir(parents=True, exist_ok=True)
    args.assessment_output.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    all_metrics = assessment["partitions"]["all"]
    print(
        "status=complete_with_scope_limitations "
        f"detected={all_metrics['detected_positive_units']}/"
        f"{all_metrics['eligible_positive_units']}"
    )
    print(args.units_output)
    print(args.assessment_output)


if __name__ == "__main__":
    main()
