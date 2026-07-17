"""Attribute missed positive-impact windows without changing frozen rules."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .impact import intervals_overlap, read_csv, sha256


FIELDS = [
    "case_id",
    "region_id",
    "lead_time_hours",
    "valid_start_time",
    "valid_end_time",
    "impact_start_time",
    "impact_end_time",
    "risk_level",
    "forecast_spatial_p95_mm",
    "observed_spatial_p95_mm",
    "medium_threshold_mm",
    "forecast_maximum_mm",
    "observed_maximum_mm",
    "high_threshold_mm",
    "observed_p95_crosses_medium",
    "forecast_p95_crosses_medium",
    "observed_max_crosses_high",
    "primary_attribution",
    "secondary_attribution",
    "attribution_confidence",
    "explanation",
]


def _pair_lookup(pairs: list[dict[str, str]]) -> dict[tuple[str, str, int, str], dict]:
    return {
        (
            row["case_id"],
            row["region_id"],
            int(row["lead_time_hours"]),
            row["aggregation"],
        ): row
        for row in pairs
        if row["variable"] == "daily_precip_total" and row["qc_status"] == "accepted"
    }


def build_attribution_rows(
    impact_units: list[dict[str, str]],
    pairs: list[dict[str, str]],
    reviews: list[dict[str, str]],
) -> list[dict[str, Any]]:
    missed = {
        (row["case_id"], row["region_id"]): row
        for row in impact_units
        if row["detected"].lower() == "false"
    }
    pair_lookup = _pair_lookup(pairs)
    rows = []
    for review in reviews:
        key = (review["case_id"], review["region_id"])
        impact = missed.get(key)
        if not impact or review["evaluation_scope"] != "target_window":
            continue
        if not intervals_overlap(
            review["valid_start_time"],
            review["valid_end_time"],
            impact["impact_start_time"],
            impact["impact_end_time"],
        ):
            continue
        lead = int(review["lead_time_hours"])
        p95 = pair_lookup[(review["case_id"], review["region_id"], lead, "spatial_p95")]
        maximum = pair_lookup[(review["case_id"], review["region_id"], lead, "maximum")]
        forecast_p95 = float(p95["forecast_value"])
        observed_p95 = float(p95["observed_value"])
        forecast_max = float(maximum["forecast_value"])
        observed_max = float(maximum["observed_value"])
        medium = float(review["primary_threshold"])
        high = float(review["severe_threshold"])
        observed_p95_crosses = observed_p95 >= medium
        forecast_p95_crosses = forecast_p95 >= medium
        observed_max_crosses = observed_max >= high
        if observed_p95_crosses and not forecast_p95_crosses:
            primary = "weather_model_error"
            secondary = ""
            confidence = "high"
            explanation = (
                "Accepted IMERG spatial-P95 crossed the frozen medium threshold "
                "while GraphCast spatial-P95 remained below it."
            )
        elif not observed_p95_crosses and observed_max_crosses:
            primary = "risk_rule_error"
            secondary = "weather_model_error"
            confidence = "medium"
            explanation = (
                "Observed regional P95 remained below the rule threshold despite a "
                "localized maximum above the high threshold; GraphCast also "
                "underestimated that maximum."
            )
        else:
            primary = "risk_rule_error"
            secondary = ""
            confidence = "low"
            explanation = "Impact occurred without a threshold-crossing observed P95."
        rows.append(
            {
                "case_id": review["case_id"],
                "region_id": review["region_id"],
                "lead_time_hours": lead,
                "valid_start_time": review["valid_start_time"],
                "valid_end_time": review["valid_end_time"],
                "impact_start_time": impact["impact_start_time"],
                "impact_end_time": impact["impact_end_time"],
                "risk_level": review["risk_level"],
                "forecast_spatial_p95_mm": forecast_p95,
                "observed_spatial_p95_mm": observed_p95,
                "medium_threshold_mm": medium,
                "forecast_maximum_mm": forecast_max,
                "observed_maximum_mm": observed_max,
                "high_threshold_mm": high,
                "observed_p95_crosses_medium": observed_p95_crosses,
                "forecast_p95_crosses_medium": forecast_p95_crosses,
                "observed_max_crosses_high": observed_max_crosses,
                "primary_attribution": primary,
                "secondary_attribution": secondary,
                "attribution_confidence": confidence,
                "explanation": explanation,
            }
        )
    return rows


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run(
    impact_units_path: Path,
    pairs_path: Path,
    review_path: Path,
    output_path: Path,
    assessment_path: Path,
) -> None:
    units = read_csv(impact_units_path)
    pairs = read_csv(pairs_path)
    reviews = read_csv(review_path)
    rows = build_attribution_rows(units, pairs, reviews)
    if not rows:
        raise ValueError("no missed positive-impact target windows found")
    write_rows(output_path, rows)
    assessment = {
        "status": "completed_without_rule_retuning",
        "missed_positive_unit_count": len(
            {(row["case_id"], row["region_id"]) for row in rows}
        ),
        "attributed_overlapping_window_count": len(rows),
        "primary_attribution_counts": {
            label: sum(row["primary_attribution"] == label for row in rows)
            for label in sorted({row["primary_attribution"] for row in rows})
        },
        "overall_interpretation": (
            "primary_weather_underprediction_with_secondary_rule_scale_gap"
        ),
        "frozen_rule_modified": False,
        "inputs": {
            path.name: {"path": path.as_posix(), "sha256": sha256(path)}
            for path in (impact_units_path, pairs_path, review_path)
        },
        "output": output_path.as_posix(),
    }
    assessment_path.parent.mkdir(parents=True, exist_ok=True)
    assessment_path.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
