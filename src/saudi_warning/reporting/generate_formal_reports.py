"""Batch-generate controlled reports from validated frozen Risk JSON files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from saudi_warning.reporting.generate_report import (
    _read_csv,
    render_report,
    validate_report_mode,
)
from saudi_warning.risk.validation import load_region_ids, validate_result


MANIFEST_FIELDS = [
    "report_file",
    "sha256",
    "risk_file",
    "case_id",
    "region_id",
    "hazard",
    "risk_level",
    "rule_id",
    "rule_status",
    "dataset_split",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--risk-dir",
        type=Path,
        default=Path("handoff/risk_results/development_heavy_rain"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("handoff/reports/development_heavy_rain"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/formal_development_report_manifest.csv"),
    )
    parser.add_argument("--expected-count", type=int, default=15)
    parser.add_argument("--regions", type=Path, default=Path("configs/region_registry.csv"))
    parser.add_argument(
        "--truth",
        type=Path,
        default=Path("handoff/disaster_truth/disaster_impact_truth.csv"),
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=Path("handoff/disaster_truth/source_catalog.csv"),
    )
    parser.add_argument(
        "--schema", type=Path, default=Path("schemas/risk_result.schema.json")
    )
    args = parser.parse_args()

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    region_ids = load_region_ids(args.regions)
    regions = {row["region_id"]: row for row in _read_csv(args.regions)}
    sources = {row["source_id"]: row for row in _read_csv(args.sources)}
    truth = _read_csv(args.truth)
    paths = sorted(args.risk_dir.glob("*.json"))
    if len(paths) != args.expected_count:
        raise ValueError(
            f"expected {args.expected_count} frozen risk files, found {len(paths)}"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, Any]] = []
    for risk_path in paths:
        risk = json.loads(risk_path.read_text(encoding="utf-8"))
        validate_report_mode(risk, "formal")
        errors = validate_result(risk, schema, region_ids, require_frozen=True)
        if errors:
            raise ValueError(f"{risk_path}: {'; '.join(errors)}")
        base_case_id = risk["case_id"].removesuffix(f"_{risk['lead_time_hours']:03d}")
        impacts = [
            row
            for row in truth
            if row["case_id"] == base_case_id
            and row["region_id"] == risk["region_id"]
            and row["hazard"] == risk["hazard"]
        ]
        report_path = args.output_dir / f"warning_{risk['case_id']}_{risk['region_id']}.md"
        report_path.write_text(
            render_report(risk, regions[risk["region_id"]], impacts, sources),
            encoding="utf-8",
        )
        dataset_split = risk.get("verification", {}).get("dataset_split")
        if dataset_split not in {"development", "independent_test"}:
            raise ValueError(f"{risk_path}: missing verification dataset_split")
        manifest_rows.append(
            {
                "report_file": report_path.as_posix(),
                "sha256": _sha256(report_path),
                "risk_file": risk_path.as_posix(),
                "case_id": risk["case_id"],
                "region_id": risk["region_id"],
                "hazard": risk["hazard"],
                "risk_level": risk["risk_level"],
                "rule_id": risk["rule_id"],
                "rule_status": risk["rule_status"],
                "dataset_split": dataset_split,
            }
        )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(f"wrote {len(manifest_rows)} controlled frozen-rule reports")
    print(args.output_dir)
    print(args.manifest)


if __name__ == "__main__":
    main()
