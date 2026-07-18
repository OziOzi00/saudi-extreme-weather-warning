"""Build and validate the deterministic v0.1.0 prototype demonstration summary."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from saudi_warning.risk.validation import validate_paths

RELEASE_TAG = "v0.1.0-prototype"
RELEASE_DATE = "2026-07-17"


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_risk_directory(root: Path, relative: str) -> tuple[int, str]:
    directory = root / relative
    paths = sorted(directory.glob("*.json"))
    report = validate_paths(
        paths,
        root / "schemas/risk_result.schema.json",
        root / "configs/region_registry.csv",
        require_frozen=True,
    )
    failures = {path: errors for path, errors in report.items() if errors}
    _require(bool(paths), f"no Risk JSON found in {relative}")
    _require(not failures, f"Risk JSON validation failed: {failures}")
    set_digest = hashlib.sha256()
    for path in paths:
        set_digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        set_digest.update(bytes.fromhex(_sha256(path)))
    return len(paths), set_digest.hexdigest()


def build_demo_summary(root: Path) -> dict[str, Any]:
    """Validate versioned artifacts and return a deterministic release summary."""
    root = root.resolve()
    delivery_path = root / "manifests/delivery_manifest.csv"
    pairing_path = root / "manifests/development_pairing_coverage.csv"
    freeze_path = root / "manifests/development_v2_freeze_assessment.csv"
    independent_metrics_path = (
        root / "handoff/weather_verification/independent_heavy_rain_metrics.csv"
    )
    neo4j_path = root / "manifests/neo4j_live_verification.json"
    impact_path = root / "manifests/impact_layer_assessment.json"
    miss_path = root / "manifests/impact_miss_attribution.json"
    heatwave_cv_v2_path = root / "manifests/heatwave_bias_cv_v2_assessment.csv"

    delivery = _csv_rows(delivery_path)
    _require(
        len(delivery) >= 51 and len(delivery) % 3 == 0,
        f"expected at least 51 complete lead deliveries, got {len(delivery)}",
    )
    _require(
        all(row["validation_status"] == "passed" for row in delivery),
        "delivery manifest contains a failed file",
    )
    _require(
        len({row["sha256"] for row in delivery}) == len(delivery),
        "delivery SHA-256 values are not unique",
    )

    pairs = _csv_rows(pairing_path)
    pair_statuses = Counter(row["pair_status"] for row in pairs)
    _require(len(pairs) >= 153, f"expected at least 153 development pairs, got {len(pairs)}")
    _require(
        pair_statuses == {"paired_accepted": len(pairs)},
        f"unexpected pair statuses: {pair_statuses}",
    )

    freeze_rows = {row["hazard"]: row for row in _csv_rows(freeze_path)}
    heavy_rain = freeze_rows["heavy_rain"]
    heatwave = freeze_rows["heatwave"]
    _require(heavy_rain["rule_status"] == "frozen", "heavy-rain rule is not frozen")
    _require(
        heavy_rain["freeze_recommendation"] == "eligible_to_freeze",
        "heavy-rain freeze gate failed",
    )
    _require(heatwave["rule_status"] == "draft", "heatwave rule must remain draft")
    _require(heatwave["freeze_recommendation"] == "blocked", "heatwave should remain blocked")

    dev_risk_count, dev_risk_sha = _validate_risk_directory(
        root, "handoff/risk_results/development_heavy_rain"
    )
    independent_risk_count, independent_risk_sha = _validate_risk_directory(
        root, "handoff/risk_results/independent_heavy_rain"
    )
    _require(dev_risk_count == 15, f"expected 15 development Risk JSON, got {dev_risk_count}")
    _require(
        independent_risk_count == 18,
        f"expected 18 independent Risk JSON, got {independent_risk_count}",
    )

    metric_rows = _csv_rows(independent_metrics_path)
    p95 = next(
        row
        for row in metric_rows
        if row["aggregation"] == "spatial_p95" and row["scope"] == "all_leads"
    )
    contingency = {
        key: int(p95[key]) for key in ("hits", "misses", "false_alarms", "correct_negatives")
    }
    _require(
        contingency == {"hits": 6, "misses": 0, "false_alarms": 0, "correct_negatives": 12},
        f"independent heavy-rain contingency changed: {contingency}",
    )

    neo4j = _json(neo4j_path)
    _require(neo4j.get("status") == "passed", "Neo4j verification did not pass")
    impact = _json(impact_path)
    _require(
        impact.get("status") == "complete_with_scope_limitations",
        "impact assessment status changed",
    )
    _require(
        impact["partitions"]["all"]["eligible_positive_units"] == 6,
        "impact positive-unit count changed",
    )
    _require(
        impact["partitions"]["all"]["detected_positive_units"] == 5,
        "impact covered-unit count changed",
    )
    _require(
        impact.get("reviewed_negative_record_count") == 0,
        "reviewed negative evidence status changed",
    )
    miss = _json(miss_path)
    _require(miss.get("missed_positive_unit_count") == 1, "impact miss count changed")
    _require(miss.get("frozen_rule_modified") is False, "frozen rule was unexpectedly modified")
    [heatwave_cv_v2] = _csv_rows(heatwave_cv_v2_path)
    _require(heatwave_cv_v2["recommendation"] == "blocked", "latest heatwave CV status changed")
    _require(
        heatwave_cv_v2["independent_heatwave_opened"] == "False",
        "independent heatwave was unexpectedly opened",
    )

    success_48_path = root / (
        "handoff/risk_results/independent_heavy_rain/"
        "risk_20200725_00_048_SA-14_heavy_rain.json"
    )
    success_72_path = root / (
        "handoff/risk_results/independent_heavy_rain/"
        "risk_20200725_00_072_SA-14_heavy_rain.json"
    )
    miss_24_path = root / (
        "handoff/risk_results/development_heavy_rain/"
        "risk_20200501_00_024_SA-09_heavy_rain.json"
    )
    miss_48_path = root / (
        "handoff/risk_results/development_heavy_rain/"
        "risk_20200501_00_048_SA-09_heavy_rain.json"
    )
    success_48, success_72 = _json(success_48_path), _json(success_72_path)
    miss_24, miss_48 = _json(miss_24_path), _json(miss_48_path)
    _require(
        (success_48["risk_level"], success_72["risk_level"]) == ("medium", "high"),
        "success case levels changed",
    )
    _require(
        (miss_24["risk_level"], miss_48["risk_level"]) == ("low", "low"),
        "miss case levels changed",
    )

    return {
        "schema_version": "prototype_demo_summary_v1",
        "release_tag": RELEASE_TAG,
        "release_date": RELEASE_DATE,
        "release_status": "stable_research_prototype",
        "primary_demonstrable_hazard": "heavy_rain",
        "pipeline": {
            "name": "GraphCast_to_MAZU_like_to_frozen_risk_to_graph_and_report",
            "delivered_netcdf_count": len(delivery),
            "delivery_validation": f"{len(delivery)}_of_{len(delivery)}_passed",
            "development_pair_count": len(pairs),
            "development_pair_validation": f"{len(pairs)}_of_{len(pairs)}_accepted",
            "frozen_risk_json_count": dev_risk_count + independent_risk_count,
            "development_risk_json_count": dev_risk_count,
            "independent_risk_json_count": independent_risk_count,
        },
        "heavy_rain": {
            "rule_id": heavy_rain["rule_id"],
            "rule_status": heavy_rain["rule_status"],
            "independent_evaluation_status": p95["evaluation_status"],
            "independent_spatial_p95_contingency": contingency,
            "retuning_after_independent_evaluation": False,
        },
        "heatwave": {
            "rule_id": heatwave["rule_id"],
            "rule_status": heatwave["rule_status"],
            "freeze_recommendation": heatwave["freeze_recommendation"],
            "target_window_recall": float(heatwave["target_window_recall"]),
            "independent_evaluation_opened": False,
            "latest_development_bias_cv": {
                "version": "heatwave_bias_correction_cv_v2_20260718",
                "recommendation": heatwave_cv_v2["recommendation"],
                "event_target_window_recall": float(heatwave_cv_v2["target_window_recall"]),
                "event_case_detection_fraction": float(
                    heatwave_cv_v2["event_case_detection_fraction"]
                ),
                "target_window_specificity": float(
                    heatwave_cv_v2["target_window_specificity"]
                ),
            },
        },
        "knowledge_graph_live_development_verification": {
            "status": neo4j["status"],
            "node_count": neo4j["node_count"],
            "relationship_count": neo4j["relationship_count"],
            "constraint_count": neo4j["constraint_count"],
            "production_deployment": False,
        },
        "impact_layer": {
            "status": impact["status"],
            "eligible_positive_units": 6,
            "covered_positive_units": 5,
            "positive_coverage_fraction": impact["partitions"]["all"]["positive_coverage_fraction"],
            "reviewed_negative_units": 0,
            "negative_class_metrics_available": False,
            "interpretation": impact["interpretation"],
        },
        "demonstration_cases": {
            "covered_positive": {
                "case_id": "20200725_00",
                "region_id": "SA-14",
                "hazard": "heavy_rain",
                "lead048_risk_level": success_48["risk_level"],
                "lead072_risk_level": success_72["risk_level"],
                "artifacts": [
                    success_48_path.relative_to(root).as_posix(),
                    success_72_path.relative_to(root).as_posix(),
                    "handoff/reports/independent_heavy_rain/warning_20200725_00_072_SA-14.md",
                ],
            },
            "known_miss": {
                "case_id": "20200501_00",
                "region_id": "SA-09",
                "hazard": "heavy_rain",
                "lead024_risk_level": miss_24["risk_level"],
                "lead048_risk_level": miss_48["risk_level"],
                "attribution": "weather_underprediction_with_secondary_rule_scale_gap",
                "frozen_rule_modified": False,
                "artifacts": [
                    miss_24_path.relative_to(root).as_posix(),
                    miss_48_path.relative_to(root).as_posix(),
                    "handoff/impact_verification/missed_impact_attribution.csv",
                ],
            },
        },
        "release_limitations": [
            "research_prototype_not_operational_forecast_service",
            "historical_2020_replay_not_live_graphcast_inference",
            "heavy_rain_independent_sample_is_small_and_selected",
            "impact_layer_has_no_reviewed_negative_truth",
            "heatwave_rule_is_draft_and_blocked",
            "neo4j_verification_is_local_development_not_production",
        ],
        "artifact_fingerprints": {
            "delivery_manifest_sha256": _sha256(delivery_path),
            "development_pairing_coverage_sha256": _sha256(pairing_path),
            "development_risk_set_sha256": dev_risk_sha,
            "independent_risk_set_sha256": independent_risk_sha,
            "independent_metrics_sha256": _sha256(independent_metrics_path),
            "impact_assessment_sha256": _sha256(impact_path),
            "heatwave_bias_cv_v2_assessment_sha256": _sha256(heatwave_cv_v2_path),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output", type=Path, default=Path("handoff/prototype_demo/demo_summary.json")
    )
    args = parser.parse_args()
    summary = build_demo_summary(args.root)
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"prototype demo verified: {summary['release_tag']}")
    print(f"summary written: {output}")


if __name__ == "__main__":
    main()
