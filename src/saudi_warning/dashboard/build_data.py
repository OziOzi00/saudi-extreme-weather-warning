"""Build the small, versioned data bundle consumed by the local dashboard."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "dashboard" / "data" / "dashboard_data.js"


def _read_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some historical risk files contain a mojibake-only description_zh tail.
        # The operational fields before it are valid; discard only that display field.
        repaired = re.sub(r',\s*"description_zh"\s*:\s*.*?\n}', "\n}", text, flags=re.S)
        return json.loads(repaired)


def _simplify_ring(points: list[list[float]], stride: int = 3) -> list[list[float]]:
    if len(points) <= 18:
        return points
    sampled = points[::stride]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    if sampled[0] != sampled[-1]:
        sampled.append(sampled[0])
    return [[round(p[0], 4), round(p[1], 4)] for p in sampled]


def _simplify_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    coords = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        simple = [_simplify_ring(ring) for ring in coords]
    elif geometry["type"] == "MultiPolygon":
        simple = [[_simplify_ring(ring) for ring in polygon] for polygon in coords]
    else:
        raise ValueError(f"Unsupported ADM1 geometry: {geometry['type']}")
    return {"type": geometry["type"], "coordinates": simple}


def _evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in ("indicator", "metric", "value", "comparison", "threshold", "unit", "role")
    }


def build_bundle(root: Path = ROOT) -> dict[str, Any]:
    registry_path = root / "configs" / "region_registry.csv"
    with registry_path.open(encoding="utf-8-sig", newline="") as handle:
        registry = {row["region_id"]: row for row in csv.DictReader(handle)}

    geo = _read_json(root / "data" / "reference" / "saudi_adm1_geoboundaries_2017.geojson")
    regions = []
    for feature in geo["features"]:
        props = feature["properties"]
        region_id = props["region_id"]
        record = registry[region_id]
        regions.append(
            {
                "region_id": region_id,
                "region_name": record["region_name_en"],
                "headquarters": record["headquarters_en"],
                "geometry": _simplify_geometry(feature["geometry"]),
            }
        )

    risks: list[dict[str, Any]] = []
    for split, directory in (
        ("development", root / "handoff" / "risk_results" / "development_heavy_rain"),
        ("independent_test", root / "handoff" / "risk_results" / "independent_heavy_rain"),
    ):
        for path in sorted(directory.glob("risk_*.json")):
            raw = _read_json(path)
            summary = raw["indicator_summary"]
            risks.append(
                {
                    "risk_id": f"{raw['case_id']}|{raw['region_id']}",
                    "case_id": raw["case_id"],
                    "initial_time": raw["initial_time"],
                    "lead_time_hours": raw["lead_time_hours"],
                    "valid_start_time": raw["valid_start_time"],
                    "valid_end_time": raw["valid_end_time"],
                    "region_id": raw["region_id"],
                    "region_name": raw["region_name"],
                    "risk_level": raw["risk_level"],
                    "risk_score": raw["risk_score"],
                    "confidence": raw["confidence"],
                    "rule_id": raw["rule_id"],
                    "rule_status": raw["rule_status"],
                    "dataset_split": split,
                    "summary": summary,
                    "supporting_evidence": [_evidence(x) for x in raw["supporting_evidence"]],
                    "contradicting_evidence": [_evidence(x) for x in raw["contradicting_evidence"]],
                    "source_path": path.relative_to(root).as_posix(),
                }
            )

    with (root / "handoff" / "impact_verification" / "missed_impact_attribution.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        misses = list(csv.DictReader(handle))

    with (root / "handoff" / "weather_verification" / "independent_heavy_rain_metrics.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        metrics = next(
            row
            for row in csv.DictReader(handle)
            if row["aggregation"] == "spatial_p95" and row["scope"] == "all_leads"
        )

    heatwave_path = root / "manifests" / "heatwave_bias_cv_v2_assessment.csv"
    with heatwave_path.open(encoding="utf-8-sig", newline="") as handle:
        heatwave = next(csv.DictReader(handle))
    heatwave_prospective = _read_json(
        root / "manifests" / "heatwave_v3_prospective_assessment.json"
    )

    impact = _read_json(root / "manifests" / "impact_layer_assessment.json")
    neo4j = _read_json(root / "manifests" / "neo4j_live_verification.json")
    knowledge_graph = _read_json(
        root / "handoff" / "knowledge_graph" / "heavy_rain_evaluation_bundle.json"
    )

    return {
        "meta": {
            "generated_from_repository_artifacts": True,
            "risk_result_count": len(risks),
            "region_count": len(regions),
            "boundary_source": "data/reference/saudi_adm1_geoboundaries_2017.geojson",
            "disclaimer": "研究原型；不构成官方气象预警。",
        },
        "regions": regions,
        "risks": risks,
        "evaluation": {
            "heavy_rain": {
                "status": "frozen",
                "split": metrics["dataset_split"],
                "pairs": int(metrics["pair_count"]),
                "hits": int(metrics["hits"]),
                "misses": int(metrics["misses"]),
                "false_alarms": int(metrics["false_alarms"]),
                "correct_negatives": int(metrics["correct_negatives"]),
                "pod": float(metrics["pod"]),
                "far": float(metrics["far"]),
                "csi": float(metrics["csi"]),
            },
            "heatwave": {
                "status": heatwave["recommendation"],
                "candidate_hits": int(heatwave["candidate_hits"]),
                "target_windows": int(heatwave["event_target_windows"]),
                "event_cases_detected": round(
                    float(heatwave["event_case_detection_fraction"]) * int(heatwave["event_cases"])
                ),
                "event_cases": int(heatwave["event_cases"]),
                "controls_rejected": int(heatwave["candidate_correct_negatives"]),
                "controls": int(heatwave["control_target_windows"]),
                "bias_correction_degc": float(heatwave["final_correction_degc"]),
                "blocking_reasons": heatwave["blocking_reasons"].split(";"),
                "independent_opened": heatwave["independent_heatwave_opened"].lower() == "true",
                "prospective_event_hits": heatwave_prospective["event_target_hits"],
                "prospective_event_windows": heatwave_prospective["event_target_windows"],
                "prospective_control_correct_negatives": heatwave_prospective[
                    "control_correct_negatives"
                ],
                "prospective_control_windows": heatwave_prospective["control_target_windows"],
                "prospective_recommendation": heatwave_prospective["recommendation"],
            },
            "impact": {
                "status": impact["status"],
                "detected_positive_units": impact["partitions"]["all"]["detected_positive_units"],
                "eligible_positive_units": impact["partitions"]["all"]["eligible_positive_units"],
                "negative_metrics_status": impact["negative_class_metrics_status"],
                "interpretation": impact["interpretation"],
            },
            "knowledge_graph": {
                "status": neo4j["status"],
                "nodes": neo4j["node_count"],
                "relationships": neo4j["relationship_count"],
                "constraints": neo4j["constraint_count"],
                "scope": "local development verification",
            },
        },
        "known_miss": {
            "case": "20200501_00",
            "region_id": "SA-09",
            "title": "Jazan 已知影响事件漏报",
            "records": misses,
            "scope_note": "用于误差归因，不代表独立测试集性能。",
        },
        "knowledge_graph": {
            "source": "handoff/knowledge_graph/heavy_rain_evaluation_bundle.json",
            "schema_version": knowledge_graph["schema_version"],
            "nodes": knowledge_graph["nodes"],
            "relations": knowledge_graph["relations"],
        },
    }


def write_bundle(output: Path = DEFAULT_OUTPUT, root: Path = ROOT) -> Path:
    bundle = build_bundle(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    output.write_text(f"window.DASHBOARD_DATA={payload};\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = write_bundle(args.output)
    print(f"Dashboard data written: {output}")


if __name__ == "__main__":
    main()
