from __future__ import annotations

from pathlib import Path

from saudi_warning.knowledge_graph.verify_neo4j import (
    _expected_node_identities,
    _expected_relation_identities,
    _read_query,
)


ROOT = Path(__file__).resolve().parents[1]


def test_expected_identities_preserve_parallel_evidence() -> None:
    bundle = {
        "nodes": [{"label": "Region", "id": "SA-01"}],
        "relations": [
            {
                "type": "EVALUATED_BY",
                "start_label": "HistoricalEvent",
                "start_id": "event-1",
                "end_label": "Evidence",
                "end_id": "source-1",
                "properties": {"record_id": record_id},
            }
            for record_id in ("impact-1", "impact-2")
        ],
    }

    assert sum(_expected_node_identities(bundle).values()) == 1
    assert sum(_expected_relation_identities(bundle).values()) == 2


def test_all_fixed_queries_are_driver_ready() -> None:
    for path in sorted((ROOT / "neo4j" / "queries").glob("*.cypher")):
        query = _read_query(path)
        assert not query.startswith("//")
        assert not query.endswith(";")
        assert "MATCH" in query
