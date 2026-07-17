from __future__ import annotations

import pytest

from saudi_warning.knowledge_graph.load_neo4j import _group_relations


def relation(record_id: str | None) -> dict:
    properties = {"record_id": record_id} if record_id else {}
    return {
        "type": "EVALUATED_BY",
        "start_label": "HistoricalEvent",
        "start_id": "event-1",
        "end_label": "Evidence",
        "end_id": "source-1",
        "properties": properties,
    }


def test_group_relations_preserves_parallel_evidence_records() -> None:
    grouped = _group_relations([relation("impact-1"), relation("impact-2")])

    [key] = grouped
    assert key == (
        "EVALUATED_BY",
        "HistoricalEvent",
        "Evidence",
        "record_id",
    )
    assert len(grouped[key]) == 2


def test_group_relations_rejects_duplicate_stable_identity() -> None:
    with pytest.raises(ValueError, match="duplicate relationship identity"):
        _group_relations([relation("impact-1"), relation("impact-1")])


def test_group_relations_keeps_endpoint_identity_without_record_id() -> None:
    grouped = _group_relations([relation(None)])

    [key] = grouped
    assert key[-1] is None
