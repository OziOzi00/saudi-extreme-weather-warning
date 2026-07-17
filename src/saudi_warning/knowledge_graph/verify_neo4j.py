"""Verify a live Neo4j instance against a versioned knowledge-graph bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_CONSTRAINTS = {
    "region_id",
    "forecast_case_id",
    "historical_event_id",
    "risk_assessment_id",
    "rule_id",
    "evidence_id",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("handoff/knowledge_graph/heavy_rain_evaluation_bundle.json"),
    )
    parser.add_argument("--queries", type=Path, default=Path("neo4j/queries"))
    parser.add_argument(
        "--output", type=Path, default=Path("manifests/neo4j_live_verification.json")
    )
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _expected_node_identities(bundle: dict[str, Any]) -> Counter:
    return Counter((row["label"], row["id"]) for row in bundle["nodes"])


def _expected_relation_identities(bundle: dict[str, Any]) -> Counter:
    return Counter(
        (
            row["type"],
            row["start_label"],
            row["start_id"],
            row["end_label"],
            row["end_id"],
            row.get("properties", {}).get("record_id"),
        )
        for row in bundle["relations"]
    )


def _read_query(path: Path) -> str:
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    ]
    return "\n".join(lines).strip().removesuffix(";")


def _sample_id(bundle: dict[str, Any], label: str) -> str:
    return next(row["id"] for row in bundle["nodes"] if row["label"] == label)


def verify_live_graph(
    bundle: dict[str, Any], uri: str, user: str, password: str, queries: Path
) -> dict[str, Any]:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("install graph dependencies with: pip install -e .[graph]") from exc

    expected_nodes = _expected_node_identities(bundle)
    expected_relations = _expected_relation_identities(bundle)
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver:
        driver.verify_connectivity()
        with driver.session() as session:
            components = list(
                session.run(
                    "CALL dbms.components() YIELD name, versions, edition "
                    "RETURN name, versions[0] AS version, edition"
                )
            )
            actual_nodes = Counter(
                (row["label"], row["id"])
                for row in session.run(
                    "MATCH (n) RETURN labels(n)[0] AS label, n.id AS id"
                )
            )
            actual_relations = Counter(
                (
                    row["type"],
                    row["start_label"],
                    row["start_id"],
                    row["end_label"],
                    row["end_id"],
                    row["record_id"],
                )
                for row in session.run(
                    "MATCH (a)-[r]->(b) "
                    "RETURN type(r) AS type, labels(a)[0] AS start_label, "
                    "a.id AS start_id, labels(b)[0] AS end_label, "
                    "b.id AS end_id, r.record_id AS record_id"
                )
            )
            constraints = {
                row["name"]
                for row in session.run("SHOW CONSTRAINTS YIELD name RETURN name")
            }
            query_specs = {
                "case_trace": (
                    "case_trace.cypher",
                    {"case_id": _sample_id(bundle, "ForecastCase")},
                ),
                "risk_trace": (
                    "risk_trace.cypher",
                    {"risk_id": _sample_id(bundle, "RiskAssessment")},
                ),
                "region_events": (
                    "region_events.cypher",
                    {"region_id": _sample_id(bundle, "Region")},
                ),
            }
            query_results = {}
            for name, (filename, parameters) in query_specs.items():
                records = list(
                    session.run(_read_query(queries / filename), parameters)
                )
                if not records:
                    raise ValueError(f"fixed query returned no rows: {name}")
                query_results[name] = {
                    "parameters": parameters,
                    "row_count": len(records),
                    "status": "passed",
                }

    errors = []
    if actual_nodes != expected_nodes:
        errors.append("node_identities_do_not_match_bundle")
    if actual_relations != expected_relations:
        errors.append("relationship_identities_do_not_match_bundle")
    if constraints != EXPECTED_CONSTRAINTS:
        errors.append("constraints_do_not_match_schema")
    if errors:
        raise ValueError(";".join(errors))

    label_counts = Counter(label for label, _ in actual_nodes)
    relation_counts = Counter(item[0] for item in actual_relations)
    return {
        "status": "passed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "database_uri": uri,
        "database_components": [dict(row) for row in components],
        "node_count": sum(actual_nodes.values()),
        "relationship_count": sum(actual_relations.values()),
        "constraint_count": len(constraints),
        "constraints": sorted(constraints),
        "node_counts_by_label": dict(sorted(label_counts.items())),
        "relationship_counts_by_type": dict(sorted(relation_counts.items())),
        "fixed_queries": query_results,
        "password_recorded": False,
    }


def main() -> None:
    args = parse_args()
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise SystemExit("NEO4J_PASSWORD is required; do not put it in the repository")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    result = verify_live_graph(bundle, args.uri, args.user, password, args.queries)
    result["bundle_path"] = args.bundle.as_posix()
    result["bundle_sha256"] = _sha256(args.bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"status={result['status']} nodes={result['node_count']} "
        f"relationships={result['relationship_count']} "
        f"constraints={result['constraint_count']}"
    )
    print(args.output)


if __name__ == "__main__":
    main()
