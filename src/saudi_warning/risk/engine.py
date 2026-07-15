"""Auditable region-level candidate risk engine.

Draft rules are intentionally separated from formal ``handoff/risk_results``.
They support interface development and team review, not independent evaluation.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


SEASONS = {
    1: "DJF",
    2: "DJF",
    3: "MAM",
    4: "MAM",
    5: "MAM",
    6: "JJA",
    7: "JJA",
    8: "JJA",
    9: "SON",
    10: "SON",
    11: "SON",
    12: "DJF",
}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _season(valid_start: str, valid_end: str) -> str:
    midpoint = _utc(valid_start) + (_utc(valid_end) - _utc(valid_start)) / 2
    return SEASONS[midpoint.month]


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def load_rule(path: Path, expected_hazard: str) -> dict[str, Any]:
    rule = yaml.safe_load(path.read_text(encoding="utf-8"))
    if rule.get("hazard") != expected_hazard:
        raise ValueError(f"{path} does not define {expected_hazard}")
    if rule.get("status") not in {"draft", "frozen"}:
        raise ValueError(f"unsupported rule status in {path}")
    return rule


def load_statistics(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    frame = pd.read_csv(path)
    required = {"period", "region_id", "indicator"}
    if not required.issubset(frame.columns):
        raise ValueError(f"statistics missing columns: {sorted(required - set(frame.columns))}")
    return {
        (str(row.period), str(row.region_id), str(row.indicator)): row._asdict()
        for row in frame.itertuples(index=False)
    }


def load_summaries(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    required = {
        "source_file",
        "initial_time",
        "lead_time_hours",
        "valid_start_time",
        "valid_end_time",
        "region_id",
        "region_name_en",
        "indicator",
        "unit",
        "weighted_mean",
        "spatial_p95",
        "maximum",
    }
    if not required.issubset(frame.columns):
        raise ValueError(f"summaries missing columns: {sorted(required - set(frame.columns))}")
    return [row._asdict() for row in frame.itertuples(index=False)]


def _group_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["initial_time"]), int(row["lead_time_hours"]), str(row["region_id"]))
        group = groups.setdefault(
            key,
            {
                "source_file": str(row["source_file"]),
                "initial_time": str(row["initial_time"]),
                "lead_time_hours": int(row["lead_time_hours"]),
                "valid_start_time": str(row["valid_start_time"]),
                "valid_end_time": str(row["valid_end_time"]),
                "region_id": str(row["region_id"]),
                "region_name": str(row["region_name_en"]),
                "indicators": {},
            },
        )
        group["indicators"][str(row["indicator"])] = row
    return sorted(
        groups.values(),
        key=lambda item: (item["initial_time"], item["region_id"], item["lead_time_hours"]),
    )


def _reference(
    statistics: dict[tuple[str, str, str], dict[str, Any]],
    period: str,
    region_id: str,
    indicator: str,
    column: str,
) -> float | None:
    row = statistics.get((period, region_id, indicator))
    return None if row is None else _number(row.get(column))


def _metric(group: dict[str, Any], indicator: str, metric: str) -> float | None:
    row = group["indicators"].get(indicator)
    return None if row is None else _number(row.get(metric))


def _evidence(
    indicator: str,
    metric: str,
    value: float | None,
    comparison: str,
    threshold: float | None,
    unit: str,
    role: str,
    reference_period: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "indicator": indicator,
        "metric": metric,
        "value": value,
        "comparison": comparison,
        "threshold": threshold,
        "unit": unit,
        "role": role,
    }
    if reference_period is not None:
        item["reference_period"] = reference_period
    return item


def _case_id(group: dict[str, Any]) -> str:
    stamp = _utc(group["initial_time"]).strftime("%Y%m%d_%H")
    return f"{stamp}_{group['lead_time_hours']:03d}"


def _base_result(
    group: dict[str, Any],
    hazard: str,
    rule: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "risk_result_v1",
        "case_id": _case_id(group),
        "source_file": group["source_file"],
        "initial_time": group["initial_time"],
        "lead_time_hours": group["lead_time_hours"],
        "valid_start_time": group["valid_start_time"],
        "valid_end_time": group["valid_end_time"],
        "region_id": group["region_id"],
        "region_name": group["region_name"],
        "hazard": hazard,
        "rule_id": rule["rule_id"],
        "rule_status": rule["status"],
        "indicator_summary": {},
        "supporting_evidence": [],
        "contradicting_evidence": [],
        "missing_evidence": [],
        "verification": None,
        "created_at": created_at,
    }


def evaluate_heavy_rain(
    group: dict[str, Any],
    statistics: dict[tuple[str, str, str], dict[str, Any]],
    rule: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    result = _base_result(group, "heavy_rain", rule, created_at)
    period = _season(group["valid_start_time"], group["valid_end_time"])
    region_id = group["region_id"]
    precip = _metric(group, "daily_precip_total", "spatial_p95")
    medium_cfg = rule["thresholds"]["precipitation"]["medium"]
    high_cfg = rule["thresholds"]["precipitation"]["high"]
    medium_ref = _reference(
        statistics, period, region_id, "daily_precip_total", medium_cfg["reference_column"]
    )
    high_ref = _reference(
        statistics, period, region_id, "daily_precip_total", high_cfg["reference_column"]
    )
    medium_threshold = (
        None if medium_ref is None else max(float(medium_cfg["absolute_floor"]), medium_ref)
    )
    high_threshold = (
        None if high_ref is None else max(float(high_cfg["absolute_floor"]), high_ref)
    )
    summary = result["indicator_summary"]
    summary.update(
        {
            "reference_period": period,
            "precip_spatial_p95_mm": precip,
            "precip_medium_threshold_mm": medium_threshold,
            "precip_high_threshold_mm": high_threshold,
        }
    )

    if precip is None or medium_threshold is None or high_threshold is None:
        result["missing_evidence"].append(
            _evidence(
                "daily_precip_total",
                "spatial_p95",
                precip,
                ">=",
                medium_threshold,
                "mm",
                "primary",
                period,
            )
        )
        result.update(
            risk_level="low",
            risk_score=0.0,
            confidence="low",
            description_zh="主降水指标或参考阈值缺失；草案引擎不作正风险判定。",
        )
        return result

    if precip >= high_threshold:
        precipitation_stage = "high"
        score = float(rule["scoring"]["precipitation_high"])
        threshold = high_threshold
    elif precip >= medium_threshold:
        precipitation_stage = "medium"
        score = float(rule["scoring"]["precipitation_medium"])
        threshold = medium_threshold
    else:
        precipitation_stage = "below_medium"
        score = 0.0
        threshold = medium_threshold

    precip_item = _evidence(
        "daily_precip_total", "spatial_p95", precip, ">=", threshold, "mm", "primary", period
    )
    precip_evidence = (
        result["supporting_evidence"]
        if precipitation_stage != "below_medium"
        else result["contradicting_evidence"]
    )
    precip_evidence.append(precip_item)
    summary["precipitation_stage"] = precipitation_stage

    support_count = 0
    support_column = rule["thresholds"]["supporting_percentile"]["reference_column"]
    support_units = {
        "pwat": "kg m-2",
        "ivt": "kg m-1 s-1",
        "wind850_speed": "m s-1",
    }
    for indicator, unit in support_units.items():
        value = _metric(group, indicator, "weighted_mean")
        reference = _reference(statistics, period, region_id, indicator, support_column)
        summary[f"{indicator}_weighted_mean"] = value
        if value is None or reference is None:
            result["missing_evidence"].append(
                _evidence(
                    indicator, "weighted_mean", value, ">=", reference, unit, "support", period
                )
            )
        elif value >= reference:
            support_count += 1
            if precipitation_stage != "below_medium":
                score += float(rule["scoring"]["each_supporting_indicator"])
            result["supporting_evidence"].append(
                _evidence(
                    indicator, "weighted_mean", value, ">=", reference, unit, "support", period
                )
            )
        else:
            result["contradicting_evidence"].append(
                _evidence(
                    indicator, "weighted_mean", value, ">=", reference, unit, "support", period
                )
            )

    omega = _metric(group, "omega500", "weighted_mean")
    omega_threshold = float(rule["thresholds"]["upward_motion"]["maximum"])
    summary["omega500_weighted_mean_pa_s-1"] = omega
    if omega is None:
        result["missing_evidence"].append(
            _evidence("omega500", "weighted_mean", None, "<", omega_threshold, "Pa s-1", "support")
        )
    elif omega < omega_threshold:
        support_count += 1
        if precipitation_stage != "below_medium":
            score += float(rule["scoring"]["each_supporting_indicator"])
        result["supporting_evidence"].append(
            _evidence("omega500", "weighted_mean", omega, "<", omega_threshold, "Pa s-1", "support")
        )
    else:
        result["contradicting_evidence"].append(
            _evidence("omega500", "weighted_mean", omega, "<", omega_threshold, "Pa s-1", "support")
        )

    summary["support_count"] = support_count
    if precipitation_stage == "high" and support_count >= int(
        rule["classification"]["high_minimum_support_count"]
    ):
        level = "high"
    elif precipitation_stage in {"medium", "high"}:
        level = "medium"
    else:
        level = "low"
    available_support = 4 - len(result["missing_evidence"])
    # The draft rule caps confidence because MAZU support fields are representative
    # times while the GraphCast values are 24-hour means.
    confidence = "medium" if available_support >= 1 else "low"
    result.update(
        risk_level=level,
        risk_score=score,
        confidence=confidence,
        description_zh=f"候选暴雨规则草案：降水阶段 {precipitation_stage}，辅助支持 {support_count}/4。",
    )
    return result


def _heat_thresholds(
    group: dict[str, Any],
    statistics: dict[tuple[str, str, str], dict[str, Any]],
    rule: dict[str, Any],
) -> tuple[str, float | None, float | None, float | None]:
    period = _season(group["valid_start_time"], group["valid_end_time"])
    region_id = group["region_id"]
    values: list[float | None] = []
    definitions = (
        ("hot_day", "tmax_c"),
        ("severe_hot_day", "tmax_c"),
        ("warm_night", "tmin_c"),
    )
    for name, indicator in definitions:
        config = rule["thresholds"][name]
        reference = _reference(statistics, period, region_id, indicator, config["reference_column"])
        values.append(
            None if reference is None else max(float(config["absolute_floor"]), reference)
        )
    return period, values[0], values[1], values[2]


def _heat_streaks(
    groups: list[dict[str, Any]],
    statistics: dict[tuple[str, str, str], dict[str, Any]],
    rule: dict[str, Any],
) -> dict[tuple[str, str, int], int]:
    by_case: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        by_case[(group["initial_time"], group["region_id"])].append(group)
    streaks: dict[tuple[str, str, int], int] = {}
    for key, items in by_case.items():
        streak = 0
        previous_end: datetime | None = None
        for group in sorted(items, key=lambda item: item["lead_time_hours"]):
            _, hot_threshold, _, _ = _heat_thresholds(group, statistics, rule)
            tmax = _metric(group, "tmax_c", "spatial_p95")
            start = _utc(group["valid_start_time"])
            if previous_end is not None and start != previous_end:
                streak = 0
            is_hot = tmax is not None and hot_threshold is not None and tmax >= hot_threshold
            streak = streak + 1 if is_hot else 0
            streaks[(key[0], key[1], group["lead_time_hours"])] = streak
            previous_end = _utc(group["valid_end_time"])
    return streaks


def evaluate_heatwave(
    group: dict[str, Any],
    statistics: dict[tuple[str, str, str], dict[str, Any]],
    rule: dict[str, Any],
    streak: int,
    created_at: str,
) -> dict[str, Any]:
    result = _base_result(group, "heatwave", rule, created_at)
    period, hot_threshold, severe_threshold, warm_threshold = _heat_thresholds(
        group, statistics, rule
    )
    tmax = _metric(group, "tmax_c", "spatial_p95")
    tmin = _metric(group, "tmin_c", "spatial_p95")
    summary = result["indicator_summary"]
    summary.update(
        {
            "reference_period": period,
            "tmax_spatial_p95_degc": tmax,
            "tmin_spatial_p95_degc": tmin,
            "hot_day_threshold_degc": hot_threshold,
            "severe_hot_day_threshold_degc": severe_threshold,
            "warm_night_threshold_degc": warm_threshold,
            "forecast_hot_day_duration": streak,
        }
    )
    result["missing_evidence"].append(
        {
            "indicator": "pre_initialization_heatwave_duration",
            "role": "duration_context",
            "reason": "not_available_from_forecast_windows",
        }
    )
    if tmax is None or hot_threshold is None or severe_threshold is None:
        result["missing_evidence"].append(
            _evidence("tmax_c", "spatial_p95", tmax, ">=", hot_threshold, "degC", "primary", period)
        )
        result.update(
            risk_level="low",
            risk_score=0.0,
            confidence="low",
            description_zh="Tmax 或候选参考阈值缺失；草案引擎不作正风险判定。",
        )
        return result

    severe = tmax >= severe_threshold
    hot = tmax >= hot_threshold
    score = float(rule["scoring"]["severe_hot_day" if severe else "hot_day"]) if hot else 0.0
    hot_item = _evidence(
        "tmax_c",
        "spatial_p95",
        tmax,
        ">=",
        severe_threshold if severe else hot_threshold,
        "degC",
        "primary",
        period,
    )
    (result["supporting_evidence"] if hot else result["contradicting_evidence"]).append(hot_item)

    warm_night = False
    if tmin is None or warm_threshold is None:
        result["missing_evidence"].append(
            _evidence(
                "tmin_c",
                "spatial_p95",
                tmin,
                ">=",
                warm_threshold,
                "degC",
                "support",
                period,
            )
        )
    else:
        warm_night = tmin >= warm_threshold
        night_item = _evidence(
            "tmin_c", "spatial_p95", tmin, ">=", warm_threshold, "degC", "support", period
        )
        night_evidence = (
            result["supporting_evidence"]
            if warm_night
            else result["contradicting_evidence"]
        )
        night_evidence.append(night_item)
        if warm_night and hot:
            score += float(rule["scoring"]["warm_night_support"])
    if hot:
        score += streak * float(rule["scoring"]["each_forecast_duration_day"])

    if severe and streak >= 3:
        level = "high"
    elif hot and (streak >= 2 or severe):
        level = "medium"
    else:
        level = "low"
    confidence = "low" if tmin is None or warm_threshold is None else "medium"
    result.update(
        risk_level=level,
        risk_score=score,
        confidence=confidence,
        description_zh=(
            f"候选高温规则草案：热日={hot}，严重热日={severe}，"
            f"预报内连续 {streak} 天，暖夜支持={warm_night}；起报前持续性未知。"
        ),
    )
    return result


def evaluate_all(
    summary_rows: list[dict[str, Any]],
    statistics: dict[tuple[str, str, str], dict[str, Any]],
    heavy_rule: dict[str, Any],
    heat_rule: dict[str, Any],
    created_at: str,
) -> list[dict[str, Any]]:
    groups = _group_summaries(summary_rows)
    streaks = _heat_streaks(groups, statistics, heat_rule)
    results: list[dict[str, Any]] = []
    for group in groups:
        results.append(evaluate_heavy_rain(group, statistics, heavy_rule, created_at))
        key = (group["initial_time"], group["region_id"], group["lead_time_hours"])
        results.append(evaluate_heatwave(group, statistics, heat_rule, streaks[key], created_at))
    return results


def write_results(results: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        filename = (
            f"risk_draft_{result['case_id']}_{result['region_id']}_{result['hazard']}.json"
        )
        (output_dir / filename).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def write_evidence_audit(results: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id",
        "region_id",
        "hazard",
        "lead_time_hours",
        "risk_level",
        "risk_score",
        "confidence",
        "rule_id",
        "rule_status",
        "supporting_count",
        "contradicting_count",
        "missing_count",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    **{field: result.get(field) for field in fields},
                    "supporting_count": len(result["supporting_evidence"]),
                    "contradicting_count": len(result["contradicting_evidence"]),
                    "missing_count": len(result["missing_evidence"]),
                }
            )


def write_threshold_audit(
    statistics: dict[tuple[str, str, str], dict[str, Any]],
    heavy_rule: dict[str, Any],
    heat_rule: dict[str, Any],
    output_path: Path,
) -> None:
    """Materialize every region/season candidate threshold for team review."""
    definitions = [
        (
            "heavy_rain",
            "daily_precip_total",
            "medium",
            heavy_rule["thresholds"]["precipitation"]["medium"],
        ),
        (
            "heavy_rain",
            "daily_precip_total",
            "high",
            heavy_rule["thresholds"]["precipitation"]["high"],
        ),
        ("heatwave", "tmax_c", "hot_day", heat_rule["thresholds"]["hot_day"]),
        ("heatwave", "tmax_c", "severe_hot_day", heat_rule["thresholds"]["severe_hot_day"]),
        ("heatwave", "tmin_c", "warm_night", heat_rule["thresholds"]["warm_night"]),
    ]
    regions = sorted({key[1] for key in statistics if key[0] in set(SEASONS.values())})
    fields = [
        "hazard",
        "period",
        "region_id",
        "indicator",
        "classification",
        "reference_column",
        "reference_value",
        "absolute_floor",
        "applied_threshold",
        "unit",
        "rule_status",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for hazard, indicator, classification, config in definitions:
            rule = heavy_rule if hazard == "heavy_rain" else heat_rule
            for period in ("DJF", "MAM", "JJA", "SON"):
                for region_id in regions:
                    reference = _reference(
                        statistics,
                        period,
                        region_id,
                        indicator,
                        config["reference_column"],
                    )
                    floor = float(config["absolute_floor"])
                    writer.writerow(
                        {
                            "hazard": hazard,
                            "period": period,
                            "region_id": region_id,
                            "indicator": indicator,
                            "classification": classification,
                            "reference_column": config["reference_column"],
                            "reference_value": reference,
                            "absolute_floor": floor,
                            "applied_threshold": (
                                None if reference is None else max(reference, floor)
                            ),
                            "unit": config["unit"],
                            "rule_status": rule["status"],
                        }
                    )
