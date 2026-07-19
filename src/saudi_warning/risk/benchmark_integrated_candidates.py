"""Benchmark weather rules and forecast-only knowledge corrections on development."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


HEAT_DETAIL_COLUMNS = [
    "method",
    "source_group",
    "case_id",
    "case_role",
    "region_id",
    "lead_time_hours",
    "evaluation_scope",
    "source_spatial_p95_degc",
    "raw_forecast_tmax_degc",
    "source_maximum_degc",
    "maximum_weight",
    "base_aggregated_tmax_degc",
    "correction_degc",
    "candidate_tmax_degc",
    "observed_tmax_degc",
    "hot_day_threshold_degc",
    "severe_hot_day_threshold_degc",
    "observed_hot_day",
    "candidate_hot_day",
    "candidate_severe_hot_day",
    "forecast_hot_day_streak",
    "candidate_positive",
]


def _as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().map({"true": True, "false": False}).astype(bool)


def _regional_thresholds(
    stats: pd.DataFrame, region_id: str, period: str
) -> tuple[float, float]:
    row = stats[
        (stats["period"] == period)
        & (stats["region_id"] == region_id)
        & (stats["indicator"] == "tmax_c")
    ]
    if len(row) != 1:
        raise ValueError(f"missing unique {period} tmax thresholds for {region_id}")
    source = row.iloc[0]
    return (
        max(47.0, float(source["daily_spatial_p95_p50"])),
        max(49.0, float(source["daily_spatial_p95_p90"])),
    )


def load_heatwave_development(root: Path) -> pd.DataFrame:
    """Unify the three already-opened heatwave development batches."""
    stats = pd.read_csv(
        root / "handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv"
    )
    legacy = pd.read_csv(
        root / "handoff/weather_verification/heatwave_development_diagnostics.csv"
    )
    legacy["raw_forecast_tmax_degc"] = legacy["source_spatial_p95_degc"]
    legacy = legacy.rename(columns={"event_threshold_degc": "hot_day_threshold_degc"})
    legacy["source_group"] = "2020_retrospective_sa04"

    v3 = pd.read_csv(
        root / "handoff/weather_verification/heatwave_v3_prospective_details.csv"
    ).rename(
        columns={
            "source_spatial_p95_degc": "raw_forecast_tmax_degc",
            "event_threshold_degc": "hot_day_threshold_degc",
        }
    )
    v3["source_group"] = "2020_prospective_sa08"

    v5 = pd.read_csv(
        root / "handoff/weather_verification/heatwave_v5_prospective_details.csv"
    ).rename(columns={"source_spatial_p95_degc": "raw_forecast_tmax_degc"})
    v5_summary = pd.read_csv(
        root
        / "handoff/region_summaries/heatwave_v5_2018_adm1_indicator_summaries.csv"
    )
    v5_summary = v5_summary[v5_summary["indicator"] == "tmax_c"].copy()
    v5_summary["case_id"] = (
        pd.to_datetime(v5_summary["initial_time"], utc=True).dt.strftime("%Y%m%d_%H")
    )
    v5_summary["lead_time_hours"] = v5_summary["lead_time_hours"].astype(int)
    v5 = v5.merge(
        v5_summary[["case_id", "region_id", "lead_time_hours", "maximum"]].rename(
            columns={"maximum": "source_maximum_degc"}
        ),
        on=["case_id", "region_id", "lead_time_hours"],
        validate="one_to_one",
    )
    v5["evaluation_scope"] = "target_window"
    v5["source_group"] = "2018_cross_year_prospective"

    common = [
        "source_group",
        "case_id",
        "case_role",
        "region_id",
        "lead_time_hours",
        "evaluation_scope",
        "raw_forecast_tmax_degc",
        "source_maximum_degc",
        "observed_tmax_degc",
        "hot_day_threshold_degc",
        "observed_hot_day",
    ]
    rows = pd.concat([legacy[common], v3[common], v5[common]], ignore_index=True)
    rows["case_id"] = rows["case_id"].astype(str)
    rows["lead_time_hours"] = rows["lead_time_hours"].astype(int)
    rows["observed_hot_day"] = _as_bool(rows["observed_hot_day"])
    months = pd.to_datetime(rows["case_id"].str[:8], format="%Y%m%d").dt.month
    rows["reference_period"] = months.map(
        {
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
    )
    threshold_lookup = {
        (region, period): _regional_thresholds(stats, region, period)
        for region, period in rows[["region_id", "reference_period"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    }
    expected_hot = pd.Series(
        [
            threshold_lookup[(row.region_id, row.reference_period)][0]
            for row in rows.itertuples(index=False)
        ],
        index=rows.index,
    )
    rows["severe_hot_day_threshold_degc"] = [
        threshold_lookup[(row.region_id, row.reference_period)][1]
        for row in rows.itertuples(index=False)
    ]
    if not np.allclose(rows["hot_day_threshold_degc"].astype(float), expected_hot):
        raise ValueError("heatwave thresholds diverge across development batches")
    if len(rows) != 48 or rows["case_id"].nunique() != 16:
        raise ValueError("expected 48 rows from 16 opened heatwave development cases")
    if rows.duplicated(["case_id", "region_id", "lead_time_hours"]).any():
        raise ValueError("duplicate heatwave development row")
    return rows


def _ridge_features(rows: pd.DataFrame, regions: list[str], raw_center: float) -> np.ndarray:
    columns = [
        np.ones(len(rows)),
        rows["raw_forecast_tmax_degc"].to_numpy(dtype=float) - raw_center,
        (rows["lead_time_hours"].to_numpy(dtype=int) == 48).astype(float),
        (rows["lead_time_hours"].to_numpy(dtype=int) == 72).astype(float),
    ]
    columns.extend(
        (rows["region_id"].astype(str).to_numpy() == region).astype(float)
        for region in regions[1:]
    )
    return np.column_stack(columns)


def _fold_correction(
    method: str,
    training: pd.DataFrame,
    held: pd.DataFrame,
    config: dict[str, Any],
) -> np.ndarray:
    residual = (
        training["observed_tmax_degc"].to_numpy(dtype=float)
        - training["raw_forecast_tmax_degc"].to_numpy(dtype=float)
    )
    pooled = float(np.median(residual))
    corrections: list[float] = []
    if method == "raw_spatial_p95":
        return np.zeros(len(held), dtype=float)
    if method.startswith("ridge_state_loco_lambda"):
        ridge_lambda = float(method.removeprefix("ridge_state_loco_lambda"))
        regions = sorted(set(training["region_id"].astype(str)) | set(held["region_id"].astype(str)))
        raw_center = float(config["heatwave"]["ridge_raw_center_degc"])
        design = _ridge_features(training, regions, raw_center)
        held_design = _ridge_features(held, regions, raw_center)
        penalty = np.eye(design.shape[1]) * ridge_lambda
        penalty[0, 0] = 0.0
        beta = np.linalg.solve(design.T @ design + penalty, design.T @ residual)
        return held_design @ beta

    training = training.assign(_residual=residual)
    shrinkage = float(config["heatwave"]["region_lead_shrinkage_k"])
    for row in held.itertuples(index=False):
        lead_rows = training[training["lead_time_hours"] == row.lead_time_hours]
        lead_value = float(lead_rows["_residual"].median()) if len(lead_rows) else pooled
        region_rows = training[training["region_id"] == row.region_id]
        if method == "pooled_median_loco":
            value = pooled
        elif method == "lead_median_loco":
            value = lead_value
        elif method == "region_median_loco":
            value = (
                float(region_rows["_residual"].median()) if len(region_rows) >= 3 else pooled
            )
        elif method == "region_lead_shrinkage_loco":
            local = region_rows[region_rows["lead_time_hours"] == row.lead_time_hours]
            if len(local):
                weight = len(local) / (len(local) + shrinkage)
                value = weight * float(local["_residual"].median()) + (1 - weight) * lead_value
            else:
                value = lead_value
        else:
            raise ValueError(f"unknown heatwave method: {method}")
        corrections.append(value)
    return np.asarray(corrections, dtype=float)


def heatwave_candidate_rows(
    rows: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    limits = config["heatwave"]["correction_clip_degc"]
    output: list[pd.DataFrame] = []
    for method in config["heatwave"]["candidates"]:
        maximum_weight = 0.0
        fitted_method = method
        if method.startswith("blend") and method.endswith("_pooled_loco"):
            maximum_weight = (
                float(method.removeprefix("blend").split("_", maxsplit=1)[0]) / 100
            )
            fitted_method = "pooled_median_loco"
        elif method == "maximum_pooled_loco":
            maximum_weight = 1.0
            fitted_method = "pooled_median_loco"
        method_rows = rows.copy()
        method_rows["source_spatial_p95_degc"] = method_rows[
            "raw_forecast_tmax_degc"
        ]
        method_rows["base_aggregated_tmax_degc"] = method_rows[
            "raw_forecast_tmax_degc"
        ].astype(float) + maximum_weight * (
            method_rows["source_maximum_degc"].astype(float)
            - method_rows["raw_forecast_tmax_degc"].astype(float)
        )
        fitting_rows = method_rows.copy()
        fitting_rows["raw_forecast_tmax_degc"] = fitting_rows[
            "base_aggregated_tmax_degc"
        ]
        folds: list[pd.DataFrame] = []
        for held_case in sorted(fitting_rows["case_id"].unique()):
            training = fitting_rows[fitting_rows["case_id"] != held_case]
            held = fitting_rows[fitting_rows["case_id"] == held_case].sort_values(
                "lead_time_hours"
            ).copy()
            correction = _fold_correction(fitted_method, training, held, config)
            held["method"] = method
            held["maximum_weight"] = maximum_weight
            held["correction_degc"] = np.clip(
                correction, float(limits["minimum"]), float(limits["maximum"])
            )
            held["candidate_tmax_degc"] = (
                held["base_aggregated_tmax_degc"].astype(float)
                + held["correction_degc"]
            )
            held["raw_forecast_tmax_degc"] = held["source_spatial_p95_degc"]
            held["candidate_hot_day"] = (
                held["candidate_tmax_degc"] >= held["hot_day_threshold_degc"]
            )
            held["candidate_severe_hot_day"] = (
                held["candidate_tmax_degc"] >= held["severe_hot_day_threshold_degc"]
            )
            streak = 0
            streaks: list[int] = []
            positives: list[bool] = []
            for item in held.itertuples(index=False):
                streak = streak + 1 if bool(item.candidate_hot_day) else 0
                streaks.append(streak)
                positives.append(bool(item.candidate_severe_hot_day or streak >= 2))
            held["forecast_hot_day_streak"] = streaks
            held["candidate_positive"] = positives
            folds.append(held)
        output.append(pd.concat(folds, ignore_index=True))
    details = pd.concat(output, ignore_index=True)
    return details[HEAT_DETAIL_COLUMNS]


def _fraction(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else float("nan")


def assess_heatwave(details: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    gates = config["heatwave"]["gates"]
    complexity = {
        "raw_spatial_p95": 0,
        "pooled_median_loco": 1,
        "lead_median_loco": 2,
        "region_median_loco": 2,
        "region_lead_shrinkage_loco": 3,
        "ridge_state_loco_lambda1": 4,
        "ridge_state_loco_lambda10": 4,
        "ridge_state_loco_lambda100": 4,
        "blend025_pooled_loco": 3,
        "blend050_pooled_loco": 3,
        "blend075_pooled_loco": 3,
        "maximum_pooled_loco": 3,
    }
    for method, all_rows in details.groupby("method", sort=False):
        target = all_rows[all_rows["evaluation_scope"] == "target_window"]
        observed_hot = target[target["observed_hot_day"]]
        observed_nonhot = target[~target["observed_hot_day"]]
        event_cases = target[target["case_role"] == "event"].groupby("case_id")[
            "candidate_positive"
        ].any()
        control_cases = target[target["case_role"] == "control"].groupby("case_id")[
            "candidate_positive"
        ].any()
        recall = float(observed_hot["candidate_hot_day"].mean())
        specificity = float((~observed_nonhot["candidate_hot_day"]).mean())
        event_detection = float(event_cases.mean())
        control_rejection = float((~control_cases).mean())
        mae = float(
            np.mean(
                np.abs(
                    target["candidate_tmax_degc"].astype(float)
                    - target["observed_tmax_degc"].astype(float)
                )
            )
        )
        passed = (
            recall >= float(gates["minimum_observed_hot_day_recall"])
            and specificity >= float(gates["minimum_observed_nonhot_day_specificity"])
            and round(event_detection, 6)
            >= float(gates["minimum_event_case_detection_fraction"])
            and control_rejection
            >= float(gates["required_control_case_rejection_fraction"])
        )
        rows.append(
            {
                "method": method,
                "target_days": len(target),
                "observed_hot_days": len(observed_hot),
                "observed_hot_day_hits": int(observed_hot["candidate_hot_day"].sum()),
                "observed_hot_day_recall": recall,
                "observed_nonhot_days": len(observed_nonhot),
                "observed_nonhot_day_correct_negatives": int(
                    (~observed_nonhot["candidate_hot_day"]).sum()
                ),
                "observed_nonhot_day_specificity": specificity,
                "balanced_accuracy": (recall + specificity) / 2,
                "event_cases": len(event_cases),
                "event_case_detections": int(event_cases.sum()),
                "event_case_detection_fraction": event_detection,
                "control_cases": len(control_cases),
                "control_case_correct_rejections": int((~control_cases).sum()),
                "control_case_rejection_fraction": control_rejection,
                "mae_degc": mae,
                "complexity_rank": complexity[method],
                "passes_all_gates": passed,
            }
        )
    return pd.DataFrame(rows)


def select_heatwave(assessment: pd.DataFrame) -> str | None:
    passing = assessment[assessment["passes_all_gates"]].copy()
    if passing.empty:
        return None
    passing["minimum_class_skill"] = passing[
        ["observed_hot_day_recall", "observed_nonhot_day_specificity"]
    ].min(axis=1)
    passing = passing.sort_values(
        [
            "minimum_class_skill",
            "balanced_accuracy",
            "event_case_detection_fraction",
            "control_case_rejection_fraction",
            "mae_degc",
            "complexity_rank",
        ],
        ascending=[False, False, False, False, True, True],
    )
    return str(passing.iloc[0]["method"])


def _support_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'"support_count"\s*:\s*(\d+)', text)
    if match is None:
        raise ValueError(f"missing support_count in {path}")
    return int(match.group(1))


def load_rain_rows(
    root: Path, split: str, *, target_only: bool = True
) -> pd.DataFrame:
    if split == "development":
        v2_path = root / "handoff/risk_dry_runs/development_v2_rule_review.csv"
        risk_dir = root / "handoff/risk_results/development_heavy_rain"
    elif split == "independent_test":
        v2_path = root / "handoff/weather_verification/independent_heavy_rain_rule_review.csv"
        risk_dir = root / "handoff/risk_results/independent_heavy_rain"
    else:
        raise ValueError(f"unsupported rain split: {split}")
    v2 = pd.read_csv(v2_path)
    v2 = v2[v2["hazard"] == "heavy_rain"].copy()
    if target_only:
        v2 = v2[v2["evaluation_scope"] == "target_window"].copy()
    if split == "development":
        v1 = pd.read_csv(root / "handoff/risk_dry_runs/development_rule_review.csv")
        v1 = v1[v1["hazard"] == "heavy_rain"].copy()
        if target_only:
            v1 = v1[v1["evaluation_scope"] == "target_window"].copy()
        key = ["case_id", "prediction_case_id", "region_id", "lead_time_hours"]
        v1_positive = v1[key + ["risk_level"]].copy()
        v1_positive["v1_positive"] = v1_positive["risk_level"].isin(["medium", "high"])
        v2 = v2.merge(v1_positive[key + ["v1_positive"]], on=key, validate="one_to_one")
    else:
        v2["v1_positive"] = pd.NA
    support_counts: list[int] = []
    for row in v2.itertuples(index=False):
        path = risk_dir / (
            f"risk_{row.prediction_case_id}_{row.region_id}_heavy_rain.json"
        )
        support_counts.append(_support_count(path))
    v2["support_count"] = support_counts
    v2["v2_positive"] = v2["risk_level"].isin(["medium", "high"])
    v2["primary_ratio"] = v2["primary_value"].astype(float) / v2[
        "primary_threshold"
    ].astype(float)
    v2["dataset_split"] = split
    return v2


def rain_candidate_rows(rows: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    output: list[pd.DataFrame] = []
    if rows["v1_positive"].notna().all():
        v1 = rows.copy()
        v1["method"] = "v1_base"
        v1["candidate_positive"] = v1["v1_positive"].astype(bool)
        v1["knowledge_triggered"] = False
        output.append(v1)
    v2 = rows.copy()
    v2["method"] = "v2_base"
    v2["candidate_positive"] = v2["v2_positive"].astype(bool)
    v2["knowledge_triggered"] = False
    output.append(v2)

    for name, rule in config["heavy_rain"]["knowledge_candidates"].items():
        candidate = rows.copy()
        eligible = (
            ~candidate["v2_positive"].astype(bool)
            & (candidate["support_count"] >= int(rule["minimum_support_count"]))
            & (candidate["primary_ratio"] >= float(rule["minimum_primary_ratio"]))
        )
        if name == "persistence_ratio050_support2":
            case_stats = candidate.assign(_eligible=eligible).groupby("case_id").agg(
                eligible_windows=("_eligible", "sum"),
                maximum_primary_ratio=("primary_ratio", "max"),
            )
            passing_cases = set(
                case_stats[
                    (case_stats["eligible_windows"] >= int(rule["minimum_eligible_windows_per_case"]))
                    & (
                        case_stats["maximum_primary_ratio"]
                        >= float(rule["case_maximum_primary_ratio"])
                    )
                ].index.astype(str)
            )
            eligible &= candidate["case_id"].astype(str).isin(passing_cases)
        candidate["method"] = f"v2_kg_{name}"
        candidate["knowledge_triggered"] = eligible
        candidate["candidate_positive"] = candidate["v2_positive"].astype(bool) | eligible
        output.append(candidate)
    return pd.concat(output, ignore_index=True)


def assess_rain(details: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    gates = config["heavy_rain"]["gates"]
    for method, group in details.groupby("method", sort=False):
        events = group[group["case_role"] == "event"]
        controls = group[group["case_role"] == "control"]
        event_cases = events.groupby("case_id")["candidate_positive"].any()
        control_cases = controls.groupby("case_id")["candidate_positive"].any()
        recall = float(events["candidate_positive"].mean())
        specificity = float((~controls["candidate_positive"]).mean())
        event_detection = float(event_cases.mean())
        control_rejection = float((~control_cases).mean())
        passed = (
            recall >= float(gates["minimum_target_window_recall"])
            and specificity >= float(gates["minimum_target_window_specificity"])
            and round(event_detection, 6)
            >= float(gates["minimum_event_case_detection_fraction"])
            and control_rejection
            >= float(gates["required_control_case_rejection_fraction"])
        )
        corrected_events = group[
            group["knowledge_triggered"] & (group["case_role"] == "event")
        ]
        corrected_controls = group[
            group["knowledge_triggered"] & (group["case_role"] == "control")
        ]
        rows.append(
            {
                "method": method,
                "dataset_split": str(group["dataset_split"].iloc[0]),
                "event_target_windows": len(events),
                "hits": int(events["candidate_positive"].sum()),
                "misses": int((~events["candidate_positive"]).sum()),
                "target_window_recall": recall,
                "control_target_windows": len(controls),
                "false_alarms": int(controls["candidate_positive"].sum()),
                "correct_negatives": int((~controls["candidate_positive"]).sum()),
                "target_window_specificity": specificity,
                "event_cases": len(event_cases),
                "event_case_detections": int(event_cases.sum()),
                "event_case_detection_fraction": event_detection,
                "control_cases": len(control_cases),
                "control_case_correct_rejections": int((~control_cases).sum()),
                "control_case_rejection_fraction": control_rejection,
                "knowledge_trigger_count": int(group["knowledge_triggered"].sum()),
                "distinct_corrected_event_cases": int(corrected_events["case_id"].nunique()),
                "new_false_alarm_count": int(len(corrected_controls)),
                "passes_base_rule_gates": passed,
            }
        )
    return pd.DataFrame(rows)


def select_rain_shadow(assessment: pd.DataFrame, config: dict[str, Any]) -> str | None:
    guard = config["heavy_rain"]["activation_guard"]
    candidates = assessment[assessment["method"].str.startswith("v2_kg_")].copy()
    candidates = candidates[
        (candidates["new_false_alarm_count"] <= int(guard["allowed_new_false_alarms"]))
        & (candidates["hits"] > assessment.loc[assessment["method"] == "v2_base", "hits"].iloc[0])
    ]
    if candidates.empty:
        return None
    complexity = {
        "v2_kg_ratio_050_support2": 1,
        "v2_kg_persistence_ratio050_support2": 2,
    }
    candidates["shadow_complexity"] = candidates["method"].map(complexity).fillna(3)
    candidates = candidates.sort_values(
        [
            "distinct_corrected_event_cases",
            "shadow_complexity",
            "hits",
            "false_alarms",
            "knowledge_trigger_count",
        ],
        ascending=[False, True, False, True, True],
    )
    return str(candidates.iloc[0]["method"])


def run(root: Path, config_path: Path, output_dir: Path, manifest_path: Path) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("status") != "retrospective_development_benchmark_not_preregistered":
        raise ValueError("integrated benchmark must retain its retrospective label")
    if config["data_policy"].get("heatwave_independent_access") != "forbidden":
        raise ValueError("heatwave independent access must remain forbidden")

    heat_source = load_heatwave_development(root)
    heat_details = heatwave_candidate_rows(heat_source, config)
    heat_assessment = assess_heatwave(heat_details, config)
    heat_selected = select_heatwave(heat_assessment)
    heat_ranked = heat_assessment.sort_values(
        ["balanced_accuracy", "event_case_detection_fraction", "mae_degc"],
        ascending=[False, False, True],
    )
    heat_best_available = str(heat_ranked.iloc[0]["method"])
    heat_best_metrics = heat_ranked.iloc[0].to_dict()
    heat_best_details = heat_details[heat_details["method"] == heat_best_available]
    heat_group_rows: list[dict[str, Any]] = []
    for source_group, group in heat_best_details.groupby("source_group", sort=True):
        target = group[group["evaluation_scope"] == "target_window"]
        hot = target[target["observed_hot_day"]]
        nonhot = target[~target["observed_hot_day"]]
        heat_group_rows.append(
            {
                "method": heat_best_available,
                "source_group": source_group,
                "target_days": len(target),
                "observed_hot_days": len(hot),
                "observed_hot_day_recall": float(hot["candidate_hot_day"].mean()),
                "observed_nonhot_days": len(nonhot),
                "observed_nonhot_day_specificity": float(
                    (~nonhot["candidate_hot_day"]).mean()
                ),
                "mae_degc": float(
                    np.mean(
                        np.abs(
                            target["candidate_tmax_degc"].astype(float)
                            - target["observed_tmax_degc"].astype(float)
                        )
                    )
                ),
            }
        )
    heat_group_assessment = pd.DataFrame(heat_group_rows)

    rain_source = load_rain_rows(root, "development")
    rain_details = rain_candidate_rows(rain_source, config)
    rain_assessment = assess_rain(rain_details, config)
    rain_shadow = select_rain_shadow(rain_assessment, config)
    no_false_alarm_candidates = rain_assessment[
        rain_assessment["method"].str.startswith("v2_kg_")
        & (rain_assessment["new_false_alarm_count"] == 0)
    ].sort_values(["hits", "knowledge_trigger_count"], ascending=[False, True])
    best_observed_rain_kg = (
        str(no_false_alarm_candidates.iloc[0]["method"])
        if not no_false_alarm_candidates.empty
        else None
    )

    independent_stress: dict[str, Any] | None = None
    if rain_shadow:
        independent_source = load_rain_rows(root, "independent_test")
        independent_details = rain_candidate_rows(independent_source, config)
        selected_details = independent_details[independent_details["method"] == rain_shadow]
        selected_assessment = assess_rain(selected_details, config).iloc[0].to_dict()
        independent_stress = {
            **selected_assessment,
            "interpretation": "nonblind_reuse_stress_test_not_candidate_selection",
        }

    activation_guard = config["heavy_rain"]["activation_guard"]
    selected_shadow_row = (
        rain_assessment[rain_assessment["method"] == rain_shadow].iloc[0]
        if rain_shadow
        else None
    )
    kg_activation_eligible = bool(
        selected_shadow_row is not None
        and int(selected_shadow_row["distinct_corrected_event_cases"])
        >= int(activation_guard["minimum_distinct_corrected_event_cases"])
        and int(selected_shadow_row["new_false_alarm_count"])
        <= int(activation_guard["allowed_new_false_alarms"])
        and not bool(activation_guard["prospective_or_new_independent_validation_required"])
    )

    manifest = {
        "schema_version": "integrated_candidate_benchmark_v1",
        "scope": config["scope"],
        "candidate_selection_split": "development",
        "heatwave": {
            "opened_development_cases": int(heat_source["case_id"].nunique()),
            "opened_target_days": int(
                (heat_source["evaluation_scope"] == "target_window").sum()
            ),
            "selected_development_method": heat_selected,
            "best_available_development_method": heat_best_available,
            "best_available_metrics": heat_best_metrics,
            "candidate_can_freeze": False,
            "independent_heatwave_opened": False,
            "interpretation": (
                "development_candidate_requires_new_preregistered_validation"
                if heat_selected
                else "no_candidate_passed_all_development_gates"
            ),
        },
        "heavy_rain": {
            "selected_official_base_rule": "heavy_rain_graphcast_scale_v2",
            "official_base_status": "frozen_with_existing_one_time_independent_evaluation",
            "selected_shadow_knowledge_candidate": rain_shadow,
            "best_observed_development_knowledge_candidate": best_observed_rain_kg,
            "shadow_candidate_activation_eligible": kg_activation_eligible,
            "shadow_candidate_may_overwrite_frozen_risk": False,
            "independent_stress": independent_stress,
        },
        "knowledge_graph": {
            "recommended_role": "shadow_correction_candidate",
            "truth_access": False,
            "base_risk_mutation_enabled": False,
            "agent_may_report_shadow_candidate": bool(rain_shadow),
        },
        "limitations": [
            "This is a retrospective development benchmark, not a preregistered prospective comparison.",
            "The heavy-rain independent set was already opened for frozen v2; reuse here is explicitly nonblind and cannot validate a new knowledge candidate.",
            "The independent heatwave case remains sealed and was not read.",
        ],
        "artifacts": {
            "heatwave_details": "handoff/model_selection/heatwave_candidate_details.csv",
            "heatwave_assessment": "handoff/model_selection/heatwave_candidate_assessment.csv",
            "heatwave_group_stability": "handoff/model_selection/heatwave_best_by_source_group.csv",
            "heavy_rain_details": "handoff/model_selection/heavy_rain_candidate_details.csv",
            "heavy_rain_assessment": "handoff/model_selection/heavy_rain_candidate_assessment.csv",
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    heat_details.to_csv(output_dir / "heatwave_candidate_details.csv", index=False)
    heat_assessment.to_csv(output_dir / "heatwave_candidate_assessment.csv", index=False)
    heat_group_assessment.to_csv(
        output_dir / "heatwave_best_by_source_group.csv", index=False
    )
    rain_details.to_csv(output_dir / "heavy_rain_candidate_details.csv", index=False)
    rain_assessment.to_csv(output_dir / "heavy_rain_candidate_assessment.csv", index=False)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/integrated_candidate_benchmark_v1.yaml"),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("handoff/model_selection")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/integrated_candidate_benchmark_v1.json"),
    )
    args = parser.parse_args()
    result = run(args.root, args.config, args.output_dir, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
