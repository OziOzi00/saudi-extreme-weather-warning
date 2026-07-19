"""Build a truth-sealed knowledge-graph snapshot for one forecast report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = "prediction_kg_bundle_v2"
TEMPORAL_MODE = "retrospective_transfer_replay"
ALLOWED_LABELS = {
    "ForecastCase",
    "ForecastWindow",
    "ConsistencyRule",
    "PriorSource",
    "Region",
    "RiskAssessment",
    "Rule",
    "StaticPriorProfile",
}
FORBIDDEN_LABELS = {
    "Evidence",
    "HistoricalEvent",
    "ImpactRecord",
    "ObservationTruth",
    "TruthRecord",
    "VerificationResult",
}
FORBIDDEN_PROPERTY_KEYS = {
    "case_role",
    "event_id",
    "fatalities_max",
    "fatalities_min",
    "impact_evidence_status",
    "impact_status",
    "observed_value",
    "source_ids",
    "verification",
    "verification_json",
    "weather_screening_status",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_region(path: Path, region_id: str) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["region_id"] == region_id]
    if len(rows) != 1:
        raise ValueError(f"expected one region registry row for {region_id}")
    return rows[0]


def _node(label: str, identifier: str, properties: dict[str, Any]) -> dict[str, Any]:
    if label not in ALLOWED_LABELS:
        raise ValueError(f"label is not permitted in a prediction snapshot: {label}")
    return {
        "label": label,
        "id": identifier,
        "properties": {key: value for key, value in properties.items() if value is not None},
    }


def _relation(
    relation_type: str,
    start_label: str,
    start_id: str,
    end_label: str,
    end_id: str,
) -> dict[str, str]:
    return {
        "type": relation_type,
        "start_label": start_label,
        "start_id": start_id,
        "end_label": end_label,
        "end_id": end_id,
    }


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _select_static_context(
    path: Path | None, region_id: str, initial_time: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    if path is None or not path.exists():
        return None, [], None
    context = json.loads(path.read_text(encoding="utf-8"))
    if context.get("schema_version") != "static_knowledge_context_v1":
        raise ValueError("unexpected static-context schema")
    if context.get("status") != "context_only_not_validated":
        raise ValueError("static context must remain context_only_not_validated")
    if context.get("truth_access") != "forbidden" or context.get("truth_accessed") is not False:
        raise ValueError("static context is not truth-sealed")
    if context.get("may_change_meteorological_risk") is not False:
        raise ValueError("static context may not change meteorological risk")
    initial = _parse_time(initial_time)
    month = initial.month
    matches = [
        profile
        for profile in context.get("profiles", [])
        if profile.get("region_id") == region_id and profile.get("month") == month
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one static profile for {region_id} month {month}")
    profile = matches[0]
    if _parse_time(profile["temporal"]["available_at"]) > initial:
        return None, [], _sha256(path)
    source_ids = set(profile.get("source_ids", []))
    sources = [source for source in context.get("sources", []) if source.get("id") in source_ids]
    if {source.get("id") for source in sources} != source_ids:
        raise ValueError("static profile references unknown source IDs")
    return profile, sources, _sha256(path)


def forecast_risk_view(risk: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable prediction facts without any post-event verification."""

    allowed = {
        "case_id",
        "source_file",
        "initial_time",
        "lead_time_hours",
        "valid_start_time",
        "valid_end_time",
        "region_id",
        "region_name",
        "hazard",
        "risk_level",
        "risk_score",
        "confidence",
        "rule_id",
        "rule_status",
        "indicator_summary",
        "supporting_evidence",
        "contradicting_evidence",
        "missing_evidence",
        "description_zh",
    }
    return {key: risk[key] for key in allowed if key in risk}


def validate_prediction_bundle(bundle: dict[str, Any]) -> list[str]:
    """Return temporal-leakage and structural errors for one prediction snapshot."""

    errors: list[str] = []
    if bundle.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if bundle.get("knowledge_role") != "prediction_context":
        errors.append("knowledge_role must be prediction_context")
    if bundle.get("truth_access") != "forbidden":
        errors.append("truth_access must be forbidden")
    if bundle.get("truth_accessed") is not False:
        errors.append("truth_accessed must be false")
    nodes = bundle.get("nodes")
    relations = bundle.get("relations")
    if not isinstance(nodes, list) or not isinstance(relations, list):
        return [*errors, "nodes and relations must be arrays"]
    for node in nodes:
        label = str(node.get("label"))
        if label in FORBIDDEN_LABELS or label not in ALLOWED_LABELS:
            errors.append(f"forbidden prediction node label: {label}")
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            errors.append(f"node properties must be an object: {label}")
            continue
        forbidden = sorted(set(properties) & FORBIDDEN_PROPERTY_KEYS)
        if forbidden:
            errors.append(f"forbidden properties on {label}: {', '.join(forbidden)}")
    for relation in relations:
        if relation.get("start_label") in FORBIDDEN_LABELS:
            errors.append("relation starts from a truth-only label")
        if relation.get("end_label") in FORBIDDEN_LABELS:
            errors.append("relation ends at a truth-only label")
    return errors


def build_prediction_bundle(
    risk_path: Path,
    regions_path: Path,
    generated_at: str,
    consistency_rules_path: Path = Path("configs/knowledge_consistency_rules_v2.yaml"),
    static_context_path: Path | None = Path(
        "handoff/knowledge_prior/static_context_v1.json"
    ),
) -> dict[str, Any]:
    """Build a per-forecast graph snapshot that cannot contain evaluation truth."""

    risk = json.loads(risk_path.read_text(encoding="utf-8"))
    if not isinstance(risk, dict):
        raise ValueError("Risk JSON must be an object")
    region = _read_region(regions_path, str(risk["region_id"]))
    consistency_rules = yaml.safe_load(
        consistency_rules_path.read_text(encoding="utf-8")
    )
    if consistency_rules.get("truth_access") != "forbidden":
        raise ValueError("consistency rules must forbid truth access")
    if consistency_rules.get("may_change_meteorological_risk") is not False:
        raise ValueError("consistency rules may not change meteorological risk")
    risk_view = forecast_risk_view(risk)
    static_profile, static_sources, static_context_sha256 = _select_static_context(
        static_context_path, str(risk["region_id"]), str(risk["initial_time"])
    )
    base_case_id = str(risk["case_id"]).removesuffix(
        f"_{int(risk['lead_time_hours']):03d}"
    )
    forecast_window_id = str(risk["case_id"])
    risk_id = f"{risk['case_id']}:{risk['region_id']}:{risk['hazard']}"
    nodes = [
        _node(
            "ForecastCase",
            base_case_id,
            {
                "initial_time": risk["initial_time"],
                "temporal_mode": TEMPORAL_MODE,
                "knowledge_cutoff": risk["initial_time"],
            },
        ),
        _node(
            "ForecastWindow",
            forecast_window_id,
            {
                "initial_time": risk["initial_time"],
                "lead_time_hours": risk["lead_time_hours"],
                "valid_start_time": risk["valid_start_time"],
                "valid_end_time": risk["valid_end_time"],
            },
        ),
        _node(
            "Region",
            str(risk["region_id"]),
            {
                "region_id": region["region_id"],
                "region_name_en": region["region_name_en"],
                "region_name_ar": region["region_name_ar"],
                "admin_level": region["admin_level"],
                "country_iso3": region["country_iso3"],
                "boundary_year_represented": region["boundary_year_represented"],
                "availability_basis": "static_reference_assumed_available",
            },
        ),
        _node("RiskAssessment", risk_id, risk_view),
        _node(
            "Rule",
            str(risk["rule_id"]),
            {
                "rule_id": risk["rule_id"],
                "rule_status": risk["rule_status"],
                "reference_role": "method_reference",
            },
        ),
        _node(
            "ConsistencyRule",
            str(consistency_rules["version"]),
            {
                "version": consistency_rules["version"],
                "status": consistency_rules["status"],
                "scope": consistency_rules["scope"],
                "truth_access": consistency_rules["truth_access"],
                "may_change_meteorological_risk": consistency_rules[
                    "may_change_meteorological_risk"
                ],
                "input_path": consistency_rules_path.as_posix(),
                "input_sha256": _sha256(consistency_rules_path),
            },
        ),
    ]
    if static_profile is not None:
        profile_properties = {
            key: value
            for key, value in static_profile.items()
            if key not in {"id", "source_ids"}
        }
        nodes.append(
            _node(
                "StaticPriorProfile",
                str(static_profile["id"]),
                profile_properties,
            )
        )
        for source in static_sources:
            nodes.append(
                _node(
                    "PriorSource",
                    str(source["id"]),
                    {key: value for key, value in source.items() if key != "id"},
                )
            )
    relations = [
        _relation(
            "HAS_WINDOW",
            "ForecastCase",
            base_case_id,
            "ForecastWindow",
            forecast_window_id,
        ),
        _relation(
            "ASSESSED_AS",
            "ForecastWindow",
            forecast_window_id,
            "RiskAssessment",
            risk_id,
        ),
        _relation(
            "CONCERNS",
            "RiskAssessment",
            risk_id,
            "Region",
            str(risk["region_id"]),
        ),
        _relation(
            "USES_RULE",
            "RiskAssessment",
            risk_id,
            "Rule",
            str(risk["rule_id"]),
        ),
        _relation(
            "CHECKED_BY",
            "RiskAssessment",
            risk_id,
            "ConsistencyRule",
            str(consistency_rules["version"]),
        ),
    ]
    if static_profile is not None:
        relations.append(
            _relation(
                "CONTEXTUALIZED_BY",
                "RiskAssessment",
                risk_id,
                "StaticPriorProfile",
                str(static_profile["id"]),
            )
        )
        for source in static_sources:
            relations.append(
                _relation(
                    "DERIVED_FROM",
                    "StaticPriorProfile",
                    str(static_profile["id"]),
                    "PriorSource",
                    str(source["id"]),
                )
            )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "knowledge_role": "prediction_context",
        "temporal_mode": TEMPORAL_MODE,
        "knowledge_cutoff": risk["initial_time"],
        "truth_access": "forbidden",
        "truth_accessed": False,
        "limitations": [
            "MAZU 2025 and the frozen rule are later method references, so this is a retrospective transfer replay rather than a literal 2020 operational forecast.",
            "No same-event observation, impact, source, verification result, or future regional case is present in this snapshot.",
            (
                "WorldClim terrain and monthly climatology are context-only and cannot identify an event day or change meteorological risk."
                if static_profile is not None
                else "Terrain, exposure, vulnerability, and pre-cutoff historical priors are not available for this cutoff."
            ),
            "Exposure, vulnerability, and validated pre-cutoff historical-event priors are not yet available.",
        ],
        "nodes": nodes,
        "relations": relations,
        "provenance": {
            "risk_path": risk_path.as_posix(),
            "risk_sha256": _sha256(risk_path),
            "regions_path": regions_path.as_posix(),
            "regions_sha256": _sha256(regions_path),
            "consistency_rules_path": consistency_rules_path.as_posix(),
            "consistency_rules_sha256": _sha256(consistency_rules_path),
            "static_context_path": (
                static_context_path.as_posix() if static_context_path is not None else None
            ),
            "static_context_sha256": static_context_sha256,
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    payload["content_sha256"] = _sha256_bytes(canonical)
    errors = validate_prediction_bundle(payload)
    if errors:
        raise ValueError("invalid prediction bundle: " + "; ".join(errors))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--risk", type=Path, required=True)
    parser.add_argument(
        "--regions", type=Path, default=Path("configs/region_registry.csv")
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--consistency-rules",
        type=Path,
        default=Path("configs/knowledge_consistency_rules_v2.yaml"),
    )
    parser.add_argument(
        "--static-context",
        type=Path,
        default=Path("handoff/knowledge_prior/static_context_v1.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/prediction_context_bundle.json")
    )
    args = parser.parse_args()
    payload = build_prediction_bundle(
        args.risk,
        args.regions,
        args.generated_at,
        args.consistency_rules,
        args.static_context,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    main()
