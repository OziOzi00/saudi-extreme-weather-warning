"""Load a validated development bundle into Neo4j using parameterized UNWIND."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from .bundle import ALLOWED_NODE_LABELS, ALLOWED_RELATION_TYPES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle", type=Path, default=Path("handoff/knowledge_graph/import_bundle.json")
    )
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    return parser.parse_args()


def _group(items: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[str, ...], list]:
    grouped: dict[tuple[str, ...], list] = defaultdict(list)
    for item in items:
        grouped[tuple(item[key] for key in keys)].append(item)
    return grouped


def load_bundle(bundle: dict[str, Any], uri: str, user: str, password: str) -> None:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("install graph dependencies with: pip install -e .[graph]") from exc

    if bundle.get("schema_version") != "kg_bundle_v1":
        raise ValueError("unsupported bundle schema")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver:
        driver.verify_connectivity()
        with driver.session() as session:
            for label, rows in _group(bundle["nodes"], ("label",)).items():
                label_name = label[0]
                if label_name not in ALLOWED_NODE_LABELS:
                    raise ValueError(f"unsafe label: {label_name}")
                query = (
                    f"UNWIND $rows AS row MERGE (n:{label_name} {{id: row.id}}) "
                    "SET n += row.properties"
                )
                session.run(query, rows=rows).consume()
            relation_groups = _group(
                bundle["relations"], ("type", "start_label", "end_label")
            )
            for (rel_type, start_label, end_label), rows in relation_groups.items():
                if rel_type not in ALLOWED_RELATION_TYPES:
                    raise ValueError(f"unsafe relation type: {rel_type}")
                if start_label not in ALLOWED_NODE_LABELS or end_label not in ALLOWED_NODE_LABELS:
                    raise ValueError("unsafe relation label")
                query = (
                    f"UNWIND $rows AS row MATCH (a:{start_label} {{id: row.start_id}}) "
                    f"MATCH (b:{end_label} {{id: row.end_id}}) "
                    f"MERGE (a)-[r:{rel_type}]->(b) SET r += row.properties"
                )
                session.run(query, rows=rows).consume()


def main() -> None:
    args = parse_args()
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise SystemExit("NEO4J_PASSWORD is required; do not put it in the repository")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    load_bundle(bundle, args.uri, args.user, password)
    print(f"loaded {args.bundle} into {args.uri}")


if __name__ == "__main__":
    main()
