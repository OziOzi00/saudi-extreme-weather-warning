"""Apply the frozen joint weather-plus-knowledge pipeline to one new case.

This module is deliberately truth-free.  It reads forecast summaries, the
development-fitted correction inputs, and the immutable joint selection lock;
it never reads observations for the case being inferred.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from saudi_warning.knowledge_graph.joint_runtime import FORBIDDEN_COLUMNS
from saudi_warning.risk.benchmark_integrated_candidates import (
    _regional_thresholds,
    load_heatwave_development,
)
from saudi_warning.risk.engine import (
    _group_summaries,
    evaluate_heavy_rain,
    load_rule,
    load_statistics,
)
from saudi_warning.risk.evaluate_joint_pipeline import _selected_base_details
from saudi_warning.risk.select_joint_pipeline import (
    apply_locked_heatwave_candidate,
    apply_locked_heavy_rain_candidate,
)


LEADS = (24, 48, 72)


def _season(month: int) -> str:
    if month in {12, 1, 2}:
        return "DJF"
    if month in {3, 4, 5}:
        return "MAM"
    if month in {6, 7, 8}:
        return "JJA"
    return "SON"


def _assert_truth_free(frame: pd.DataFrame) -> None:
    forbidden = FORBIDDEN_COLUMNS & set(frame.columns)
    if forbidden:
        raise ValueError("truth fields found in runtime prediction lock: " + ", ".join(sorted(forbidden)))
    lowered = {str(column).lower() for column in frame.columns}
    suspicious = {column for column in lowered if column.startswith("observed_")}
    if suspicious:
        raise ValueError("observed fields found in runtime prediction lock")


def _validate_shape(frame: pd.DataFrame, case_id: str, region_ids: list[str]) -> None:
    if set(frame["case_id"].astype(str)) != {case_id}:
        raise ValueError("runtime prediction lock contains a different case")
    if set(frame["region_id"].astype(str)) != set(region_ids):
        raise ValueError("runtime prediction lock does not cover exactly the requested regions")
    for region_id, group in frame.groupby("region_id"):
        if tuple(sorted(group["lead_time_hours"].astype(int))) != LEADS:
            raise ValueError(f"{region_id} does not contain exactly 24/48/72-hour windows")
    if frame.duplicated(["case_id", "region_id", "lead_time_hours"]).any():
        raise ValueError("runtime prediction lock contains duplicate windows")
    _assert_truth_free(frame)


def _rain_lock(
    root: Path,
    summaries: list[dict[str, Any]],
    case_id: str,
    region_ids: list[str],
    selected: dict[str, Any],
) -> pd.DataFrame:
    statistics = load_statistics(
        root / "handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv"
    )
    rule = load_rule(root / "configs/heavy_rain_rules_v2.yaml", "heavy_rain")
    if rule["status"] != "frozen":
        raise ValueError("runtime rain inference requires the frozen v2 rule")
    rows: list[dict[str, Any]] = []
    for group in _group_summaries(summaries):
        result = evaluate_heavy_rain(
            group, statistics, rule, created_at="1970-01-01T00:00:00Z"
        )
        summary = result["indicator_summary"]
        threshold = float(summary["precip_medium_threshold_mm"])
        primary = float(summary["precip_spatial_p95_mm"])
        rows.append(
            {
                "case_id": case_id,
                "prediction_case_id": result["case_id"],
                "region_id": result["region_id"],
                "lead_time_hours": int(result["lead_time_hours"]),
                "risk_level": result["risk_level"],
                "v1_positive": False,
                "v2_positive": result["risk_level"] in {"medium", "high"},
                "primary_ratio": primary / threshold,
                "support_count": int(summary["support_count"]),
            }
        )
    base = pd.DataFrame(rows)
    locked = apply_locked_heavy_rain_candidate(base, selected)
    locked["base_risk_level"] = locked["risk_level"]
    locked["joint_final_risk_level"] = np.where(
        locked["knowledge_triggered"] & locked["risk_level"].eq("low"),
        "medium",
        locked["risk_level"],
    )
    columns = [
        "case_id",
        "prediction_case_id",
        "region_id",
        "lead_time_hours",
        "base_method",
        "knowledge_mode",
        "base_risk_level",
        "knowledge_triggered",
        "joint_final_risk_level",
        "primary_ratio",
        "support_count",
    ]
    output = locked[columns].sort_values(["region_id", "lead_time_hours"]).reset_index(drop=True)
    _validate_shape(output, case_id, region_ids)
    return output


def _heat_lock(
    root: Path,
    summaries: list[dict[str, Any]],
    case_id: str,
    region_ids: list[str],
    selected: dict[str, Any],
) -> pd.DataFrame:
    summary_frame = pd.DataFrame(summaries)
    tmax = summary_frame[summary_frame["indicator"].eq("tmax_c")].copy()
    if len(tmax) != len(region_ids) * len(LEADS):
        raise ValueError("heatwave runtime input needs one tmax row per region and lead")
    stats = pd.read_csv(
        root / "handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv"
    )
    month = datetime.strptime(case_id[:8], "%Y%m%d").month
    period = _season(month)
    forecast_rows: list[dict[str, Any]] = []
    for row in tmax.itertuples(index=False):
        hot, severe = _regional_thresholds(stats, str(row.region_id), period)
        lead = int(row.lead_time_hours)
        forecast_rows.append(
            {
                "source_group": "runtime_truth_free",
                "case_id": case_id,
                "region_id": str(row.region_id),
                "lead_time_hours": lead,
                "evaluation_scope": "forecast_window",
                "raw_forecast_tmax_degc": float(row.spatial_p95),
                "source_maximum_degc": float(row.maximum),
                "hot_day_threshold_degc": hot,
                "severe_hot_day_threshold_degc": severe,
                "valid_date": str(row.valid_start_time)[:10],
            }
        )
    forecast = pd.DataFrame(forecast_rows)
    search = yaml.safe_load(
        (root / "configs/joint_pipeline_candidate_search_v2.yaml").read_text(encoding="utf-8")
    )
    base_config = yaml.safe_load((root / search["heatwave"]["base_config"]).read_text(encoding="utf-8"))
    development = load_heatwave_development(root)
    base = _selected_base_details(
        development, forecast, str(selected["base_method"]), base_config
    )
    locked = apply_locked_heatwave_candidate(base, selected)
    locked["base_risk_level"] = np.select(
        [
            locked["base_candidate_positive"].astype(bool),
            locked["candidate_hot_day"].astype(bool),
        ],
        ["high", "medium"],
        default="low",
    )
    locked["joint_final_risk_level"] = np.select(
        [
            locked["candidate_positive"].astype(bool),
            locked["integrated_hot_day"].astype(bool),
        ],
        ["high", "medium"],
        default="low",
    )
    columns = [
        "case_id",
        "region_id",
        "lead_time_hours",
        "valid_date",
        "base_method",
        "knowledge_mode",
        "base_risk_level",
        "knowledge_triggered",
        "joint_final_risk_level",
        "candidate_tmax_degc",
        "hot_day_threshold_degc",
    ]
    output = locked[columns].sort_values(["region_id", "lead_time_hours"]).reset_index(drop=True)
    _validate_shape(output, case_id, region_ids)
    return output


def build_runtime_prediction_lock(
    root: Path,
    *,
    summary_path: Path,
    hazard: str,
    case_id: str,
    region_ids: list[str],
    output_path: Path,
) -> pd.DataFrame:
    """Create one immutable, truth-free runtime prediction lock."""
    selection_path = root / "manifests/joint_pipeline_selection_lock_v2.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    summary_frame = pd.read_csv(summary_path)
    stamps = pd.to_datetime(summary_frame["initial_time"], utc=True).dt.strftime("%Y%m%d_%H")
    summary_frame = summary_frame[
        stamps.eq(case_id) & summary_frame["region_id"].astype(str).isin(region_ids)
    ]
    summaries = summary_frame.to_dict(orient="records")
    if hazard == "heavy_rain":
        frame = _rain_lock(root, summaries, case_id, region_ids, selection[hazard]["selected"])
    elif hazard == "heatwave":
        frame = _heat_lock(root, summaries, case_id, region_ids, selection[hazard]["selected"])
    else:
        raise ValueError(f"unsupported hazard: {hazard}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(output_path)
    return frame
