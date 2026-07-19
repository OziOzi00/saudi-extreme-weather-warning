"""Truth-free Neo4j runtime for locked joint weather predictions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


FORBIDDEN_COLUMNS = {
    "case_role",
    "observed_hot_day",
    "observed_tmax_degc",
    "observation_station_count",
    "candidate_outcome",
    "hits",
    "misses",
    "false_alarms",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def prediction_rows(
    predictions: pd.DataFrame,
    *,
    hazard: str,
    split: str,
    selected_rule: str,
    prediction_lock_sha256: str,
) -> list[dict[str, Any]]:
    """Convert a truth-free prediction lock into parameterized Neo4j rows."""
    forbidden = FORBIDDEN_COLUMNS & set(predictions.columns)
    if forbidden:
        raise ValueError("truth fields found in prediction lock: " + ", ".join(sorted(forbidden)))
    required = {
        "case_id",
        "region_id",
        "lead_time_hours",
        "base_method",
        "knowledge_mode",
        "base_risk_level",
        "knowledge_triggered",
        "joint_final_risk_level",
    }
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError("prediction lock missing fields: " + ", ".join(sorted(missing)))
    rows: list[dict[str, Any]] = []
    for item in predictions.to_dict(orient="records"):
        case_id = str(item["case_id"])
        region_id = str(item["region_id"])
        lead = int(item["lead_time_hours"])
        feature_names = (
            ("primary_ratio", "support_count")
            if hazard == "heavy_rain"
            else ("candidate_tmax_degc", "hot_day_threshold_degc")
        )
        features = {
            name: float(item[name]) if name in item and pd.notna(item[name]) else None
            for name in feature_names
        }
        rows.append(
            {
                "case_key": f"joint-case:{hazard}:{split}:{case_id}",
                "case_id": case_id,
                "region_key": f"joint-region:{region_id}",
                "region_id": region_id,
                "window_key": f"joint-window:{hazard}:{split}:{case_id}:{region_id}:{lead}",
                "lead_time_hours": lead,
                "hazard": hazard,
                "dataset_split": split,
                "base_method": str(item["base_method"]),
                "knowledge_mode": str(item["knowledge_mode"]),
                "base_risk_level": str(item["base_risk_level"]),
                "knowledge_triggered": _as_bool(item["knowledge_triggered"]),
                "joint_final_risk_level": str(item["joint_final_risk_level"]),
                "forecast_features_json": json.dumps(
                    features, ensure_ascii=False, sort_keys=True
                ),
                "selected_rule": selected_rule,
                "prediction_lock_sha256": prediction_lock_sha256,
            }
        )
    return rows


def upsert_joint_predictions(
    rows: list[dict[str, Any]], *, uri: str, user: str, password: str
) -> dict[str, int]:
    """Idempotently load only prediction-time facts into a dedicated graph namespace."""
    from neo4j import GraphDatabase

    constraints = [
        "CREATE CONSTRAINT joint_prediction_case_id IF NOT EXISTS "
        "FOR (n:JointPredictionCase) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT joint_prediction_region_id IF NOT EXISTS "
        "FOR (n:JointPredictionRegion) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT joint_forecast_window_id IF NOT EXISTS "
        "FOR (n:JointForecastWindow) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT joint_rule_id IF NOT EXISTS "
        "FOR (n:JointRule) REQUIRE n.id IS UNIQUE",
    ]
    query = """
UNWIND $rows AS row
MERGE (c:JointPredictionCase {id: row.case_key})
SET c.case_id = row.case_id,
    c.hazard = row.hazard,
    c.dataset_split = row.dataset_split,
    c.truth_accessed = false,
    c.knowledge_role = 'forecast'
MERGE (g:JointPredictionRegion {id: row.region_key})
SET g.region_id = row.region_id,
    g.knowledge_role = 'forecast_context'
MERGE (w:JointForecastWindow {id: row.window_key})
SET w.case_id = row.case_id,
    w.region_id = row.region_id,
    w.lead_time_hours = row.lead_time_hours,
    w.hazard = row.hazard,
    w.dataset_split = row.dataset_split,
    w.base_method = row.base_method,
    w.knowledge_mode = row.knowledge_mode,
    w.base_risk_level = row.base_risk_level,
    w.knowledge_triggered = row.knowledge_triggered,
    w.joint_final_risk_level = row.joint_final_risk_level,
    w.forecast_features_json = row.forecast_features_json,
    w.prediction_lock_sha256 = row.prediction_lock_sha256,
    w.truth_accessed = false
MERGE (rule:JointRule {id: row.selected_rule})
SET rule.hazard = row.hazard,
    rule.knowledge_mode = row.knowledge_mode,
    rule.truth_accessed = false
MERGE (c)-[:HAS_JOINT_WINDOW]->(w)
MERGE (w)-[:CONCERNS_PREDICTION_REGION]->(g)
MERGE (w)-[:USES_JOINT_RULE]->(rule)
"""
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver:
        driver.verify_connectivity()
        with driver.session() as session:
            for statement in constraints:
                session.run(statement).consume()
            session.run(query, rows=rows).consume()
            counts = session.run(
                """
MATCH (w:JointForecastWindow {prediction_lock_sha256: $sha})
RETURN count(w) AS windows,
       count(DISTINCT w.case_id) AS cases,
       count(DISTINCT w.region_id) AS regions
""",
                sha=rows[0]["prediction_lock_sha256"],
            ).single()
    return {
        "windows": int(counts["windows"]),
        "cases": int(counts["cases"]),
        "regions": int(counts["regions"]),
    }


def query_joint_context(
    *,
    uri: str,
    user: str,
    password: str,
    hazard: str,
    split: str,
    case_id: str,
    region_id: str,
) -> dict[str, Any]:
    """Query one case-region timeline only from dedicated truth-free labels."""
    from neo4j import GraphDatabase

    case_key = f"joint-case:{hazard}:{split}:{case_id}"
    query = """
MATCH (c:JointPredictionCase {id: $case_key})-[:HAS_JOINT_WINDOW]->
      (w:JointForecastWindow)-[:CONCERNS_PREDICTION_REGION]->
      (g:JointPredictionRegion {region_id: $region_id})
MATCH (w)-[:USES_JOINT_RULE]->(rule:JointRule)
RETURN c.case_id AS case_id,
       c.hazard AS hazard,
       c.dataset_split AS dataset_split,
       c.truth_accessed AS truth_accessed,
       g.region_id AS region_id,
       rule.id AS selected_rule,
       w.lead_time_hours AS lead_time_hours,
       w.base_method AS base_method,
       w.knowledge_mode AS knowledge_mode,
       w.base_risk_level AS base_risk_level,
       w.knowledge_triggered AS knowledge_triggered,
       w.joint_final_risk_level AS joint_final_risk_level,
       w.forecast_features_json AS forecast_features_json,
       w.prediction_lock_sha256 AS prediction_lock_sha256
ORDER BY w.lead_time_hours
"""
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver:
        driver.verify_connectivity()
        with driver.session() as session:
            records = [dict(record) for record in session.run(query, case_key=case_key, region_id=region_id)]
    if not records:
        raise ValueError("Neo4j returned no joint prediction context")
    for record in records:
        if record["truth_accessed"] is not False:
            raise ValueError("Neo4j joint context is not truth sealed")
        record["forecast_features"] = json.loads(record.pop("forecast_features_json"))
    return {
        "query_mode": "live_neo4j",
        "truth_accessed": False,
        "case_id": case_id,
        "region_id": region_id,
        "hazard": hazard,
        "dataset_split": split,
        "selected_rule": records[0]["selected_rule"],
        "prediction_lock_sha256": records[0]["prediction_lock_sha256"],
        "timeline": records,
    }
