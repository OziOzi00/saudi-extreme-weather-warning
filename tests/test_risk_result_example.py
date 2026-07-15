"""Keep the versioned Risk JSON example aligned with its lightweight schema contract."""

import json
from pathlib import Path


def test_risk_result_example_satisfies_core_schema_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "risk_result.schema.json").read_text(encoding="utf-8"))
    example = json.loads(
        (root / "handoff" / "risk_results" / "example_risk_result.json").read_text(encoding="utf-8")
    )

    assert set(schema["required"]).issubset(example)
    assert example["schema_version"] == schema["properties"]["schema_version"]["const"]
    assert example["lead_time_hours"] in schema["properties"]["lead_time_hours"]["enum"]
    assert example["hazard"] in schema["properties"]["hazard"]["enum"]
    assert example["risk_level"] in schema["properties"]["risk_level"]["enum"]
    assert example["confidence"] in schema["properties"]["confidence"]["enum"]
    assert example["rule_status"] == "example"
    assert example["verification"] is None
