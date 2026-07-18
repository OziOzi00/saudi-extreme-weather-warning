"""Audit static context and conservative attention flags on development cases only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from saudi_warning.agent.forecast_evidence import build_forecast_evidence_packet


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _confusion(rows: list[dict[str, Any]], field: str) -> dict[str, float | int | None]:
    hits = sum(row["case_role"] == "event" and row[field] for row in rows)
    misses = sum(row["case_role"] == "event" and not row[field] for row in rows)
    false_alarms = sum(row["case_role"] == "control" and row[field] for row in rows)
    correct_negatives = sum(
        row["case_role"] == "control" and not row[field] for row in rows
    )
    pod = hits / (hits + misses) if hits + misses else None
    far = false_alarms / (hits + false_alarms) if hits + false_alarms else None
    return {
        "hits": hits,
        "misses": misses,
        "false_alarms": false_alarms,
        "correct_negatives": correct_negatives,
        "pod": pod,
        "far": far,
    }


def assess_development_context(
    review_path: Path,
    risk_dir: Path,
    generated_at: str,
    spatial_diagnostics_path: Path = Path(
        "handoff/knowledge_prior/development_spatial_diagnostics_v1.json"
    ),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if "development" not in review_path.as_posix().lower():
        raise ValueError("this audit accepts development review input only")
    with review_path.open(encoding="utf-8-sig", newline="") as stream:
        review_rows = [
            row
            for row in csv.DictReader(stream)
            if row["hazard"] == "heavy_rain" and row["evaluation_scope"] == "target_window"
        ]
    risk_paths = list(risk_dir.glob("*.json"))
    risk_index: dict[tuple[str, str], Path] = {}
    for path in risk_paths:
        risk = json.loads(path.read_text(encoding="utf-8"))
        risk_index[(str(risk["case_id"]), str(risk["region_id"]))] = path
    spatial_bundle = json.loads(spatial_diagnostics_path.read_text(encoding="utf-8"))
    if spatial_bundle.get("truth_accessed") is not False:
        raise ValueError("spatial diagnostics must be truth-sealed before evaluation")
    spatial_index = {
        (str(item["case_id"]), str(item["region_id"])): item
        for item in spatial_bundle["diagnostics"]
    }

    details: list[dict[str, Any]] = []
    for review in review_rows:
        key = (review["prediction_case_id"], review["region_id"])
        if key not in risk_index:
            raise ValueError(f"missing development Risk JSON for {key}")
        if key not in spatial_index:
            raise ValueError(f"missing preregistered spatial diagnostic for {key}")
        packet = build_forecast_evidence_packet(
            risk_index[key], generated_at=generated_at
        )
        risk = packet["risk"]
        context = packet["knowledge_prior"].get("context")
        base_alert = risk["risk_level"] in {"medium", "high"}
        augmented_attention = base_alert or packet["consistency_check"][
            "conflict_flag"
        ] in {"possible_underestimation", "insufficient_primary_evidence"}
        spatial = spatial_index[key]
        spatial_attention = base_alert or bool(spatial["candidate_triggered"])
        details.append(
            {
                "prediction_case_id": review["prediction_case_id"],
                "region_id": review["region_id"],
                "case_role": review["case_role"],
                "candidate_outcome": review["candidate_outcome"],
                "risk_level": risk["risk_level"],
                "base_alert": base_alert,
                "conflict_flag": packet["consistency_check"]["conflict_flag"],
                "attention_level": packet["consistency_check"]["attention_level"],
                "augmented_attention": augmented_attention,
                "spatial_candidate_triggered": spatial["candidate_triggered"],
                "spatial_conflict_flag": spatial["candidate_conflict_flag"],
                "spatial_attention": spatial_attention,
                "precip_spatial_p99_mm": spatial["precip_spatial_p99_mm"],
                "precip_spatial_max_mm": spatial["precip_spatial_max_mm"],
                "area_fraction_ge_medium": spatial["area_fraction_ge_medium"],
                "knowledge_prior_status": packet["knowledge_prior"]["status"],
                "knowledge_prior_risk": packet["knowledge_prior"]["risk_level"],
                "static_profile_id": context["id"] if context else None,
                "static_available_at": (
                    context["temporal"]["available_at"] if context else None
                ),
                "truth_accessed_by_forecast": packet["truth_accessed"],
            }
        )
    assessment = {
        "schema_version": "static_context_development_assessment_v1",
        "generated_at": generated_at,
        "dataset_split": "development",
        "hazard": "heavy_rain",
        "target_window_count": len(details),
        "context_coverage_count": sum(
            row["knowledge_prior_status"] == "context_only" for row in details
        ),
        "context_changes_risk_count": sum(
            row["knowledge_prior_risk"] is not None for row in details
        ),
        "base_risk_alert": _confusion(details, "base_alert"),
        "risk_plus_unvalidated_attention": _confusion(details, "augmented_attention"),
        "risk_plus_preregistered_spatial_attention": _confusion(
            details, "spatial_attention"
        ),
        "interpretation": (
            "Static WorldClim context has no classification effect by design. The attention comparison "
            "evaluates the separate, post-hoc internal consistency candidate on development only."
        ),
        "spatial_candidate_trigger_count": sum(
            row["spatial_candidate_triggered"] for row in details
        ),
        "spatial_candidate_decision": "reject_no_miss_reduction_do_not_connect_to_agent_attention",
        "decision": "retain_context_only_do_not_promote_to_knowledge_risk",
        "independent_data_accessed": False,
        "may_change_frozen_risk": False,
        "inputs": {
            "review_path": review_path.as_posix(),
            "review_sha256": _sha256(review_path),
            "risk_dir": risk_dir.as_posix(),
            "risk_file_count": len(risk_paths),
            "spatial_diagnostics_path": spatial_diagnostics_path.as_posix(),
            "spatial_diagnostics_sha256": _sha256(spatial_diagnostics_path),
        },
    }
    return details, assessment


def _write_details(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review",
        type=Path,
        default=Path("handoff/risk_dry_runs/development_v2_rule_review.csv"),
    )
    parser.add_argument(
        "--risk-dir",
        type=Path,
        default=Path("handoff/risk_results/development_heavy_rain"),
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--spatial-diagnostics",
        type=Path,
        default=Path("handoff/knowledge_prior/development_spatial_diagnostics_v1.json"),
    )
    parser.add_argument(
        "--details-output",
        type=Path,
        default=Path("handoff/knowledge_prior/development_context_audit.csv"),
    )
    parser.add_argument(
        "--assessment-output",
        type=Path,
        default=Path("manifests/static_knowledge_context_development_assessment.json"),
    )
    args = parser.parse_args()
    rows, assessment = assess_development_context(
        args.review,
        args.risk_dir,
        args.generated_at,
        args.spatial_diagnostics,
    )
    _write_details(rows, args.details_output)
    args.assessment_output.parent.mkdir(parents=True, exist_ok=True)
    args.assessment_output.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.details_output}")
    print(f"wrote {args.assessment_output}")
    print(f"target_windows={assessment['target_window_count']}")
    print(f"decision={assessment['decision']}")
    print("independent_data_accessed=false")


if __name__ == "__main__":
    main()
