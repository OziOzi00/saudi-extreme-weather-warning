"""Select complete weather-rule plus knowledge-correction pipelines on development."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from saudi_warning.risk.benchmark_integrated_candidates import (
    assess_rain,
    heatwave_candidate_rows,
    load_heatwave_development,
    load_rain_rows,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bool_series(values: pd.Series) -> pd.Series:
    if values.dtype == bool:
        return values
    return values.astype(str).str.lower().eq("true")


def _candidate_id(prefix: str, **parameters: Any) -> str:
    suffix = "_".join(f"{key}{str(value).replace('.', 'p')}" for key, value in parameters.items())
    return f"{prefix}_{suffix}" if suffix else prefix


def heavy_rain_joint_candidates(
    rows: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    """Create whole-pipeline rain candidates using only forecast-time fields."""
    output: list[pd.DataFrame] = []
    for base_method in config["heavy_rain"]["base_methods"]:
        base_column = "v1_positive" if base_method == "v1_base" else "v2_positive"
        if rows[base_column].isna().any():
            continue
        base_positive = _bool_series(rows[base_column])
        baseline = rows.copy()
        baseline["method"] = f"joint_rain_{base_method}_kg_none"
        baseline["base_method"] = base_method
        baseline["knowledge_mode"] = "none"
        baseline["primary_ratio_threshold"] = np.nan
        baseline["support_count_threshold"] = np.nan
        baseline["minimum_eligible_windows"] = np.nan
        baseline["knowledge_triggered"] = False
        baseline["candidate_positive"] = base_positive
        baseline["complexity_rank"] = 0
        output.append(baseline)

        single = config["heavy_rain"]["single_window"]
        for ratio in single["primary_ratio_thresholds"]:
            for support in single["support_count_thresholds"]:
                candidate = rows.copy()
                eligible = (
                    ~base_positive
                    & (candidate["primary_ratio"].astype(float) >= float(ratio))
                    & (candidate["support_count"].astype(int) >= int(support))
                )
                candidate["method"] = _candidate_id(
                    f"joint_rain_{base_method}_kg_single",
                    ratio=ratio,
                    support=support,
                )
                candidate["base_method"] = base_method
                candidate["knowledge_mode"] = "single_window"
                candidate["primary_ratio_threshold"] = float(ratio)
                candidate["support_count_threshold"] = int(support)
                candidate["minimum_eligible_windows"] = 1
                candidate["knowledge_triggered"] = eligible
                candidate["candidate_positive"] = base_positive | eligible
                candidate["complexity_rank"] = 1
                output.append(candidate)

        persistence = config["heavy_rain"]["persistence"]
        for ratio in persistence["primary_ratio_thresholds"]:
            for support in persistence["support_count_thresholds"]:
                for minimum_windows in persistence["minimum_eligible_windows"]:
                    candidate = rows.copy()
                    window_eligible = (
                        ~base_positive
                        & (candidate["primary_ratio"].astype(float) >= float(ratio))
                        & (candidate["support_count"].astype(int) >= int(support))
                    )
                    eligible_count = (
                        candidate.assign(_eligible=window_eligible)
                        .groupby(["case_id", "region_id"])["_eligible"]
                        .transform("sum")
                    )
                    eligible = window_eligible & (eligible_count >= int(minimum_windows))
                    candidate["method"] = _candidate_id(
                        f"joint_rain_{base_method}_kg_persistence",
                        ratio=ratio,
                        support=support,
                        windows=minimum_windows,
                    )
                    candidate["base_method"] = base_method
                    candidate["knowledge_mode"] = "cross_window_persistence"
                    candidate["primary_ratio_threshold"] = float(ratio)
                    candidate["support_count_threshold"] = int(support)
                    candidate["minimum_eligible_windows"] = int(minimum_windows)
                    candidate["knowledge_triggered"] = eligible
                    candidate["candidate_positive"] = base_positive | eligible
                    candidate["complexity_rank"] = 2
                    output.append(candidate)
    return pd.concat(output, ignore_index=True)


def apply_locked_heavy_rain_candidate(
    rows: pd.DataFrame, selected: dict[str, Any]
) -> pd.DataFrame:
    """Apply one locked joint rain rule without using evaluation labels."""
    base_method = str(selected["base_method"])
    base_column = "v1_positive" if base_method == "v1_base" else "v2_positive"
    base_positive = _bool_series(rows[base_column])
    candidate = rows.copy()
    mode = str(selected["knowledge_mode"])
    if mode == "none":
        eligible = pd.Series(False, index=candidate.index)
    else:
        window_eligible = (
            ~base_positive
            & (
                candidate["primary_ratio"].astype(float)
                >= float(selected["primary_ratio_threshold"])
            )
            & (
                candidate["support_count"].astype(int)
                >= int(float(selected["support_count_threshold"]))
            )
        )
        if mode == "single_window":
            eligible = window_eligible
        elif mode == "cross_window_persistence":
            count = (
                candidate.assign(_eligible=window_eligible)
                .groupby(["case_id", "region_id"])["_eligible"]
                .transform("sum")
            )
            eligible = window_eligible & (
                count >= int(float(selected["minimum_eligible_windows"]))
            )
        else:
            raise ValueError(f"unknown locked rain knowledge mode: {mode}")
    candidate["method"] = str(selected["method"])
    candidate["base_method"] = base_method
    candidate["knowledge_mode"] = mode
    candidate["primary_ratio_threshold"] = selected.get(
        "primary_ratio_threshold", np.nan
    )
    candidate["support_count_threshold"] = selected.get(
        "support_count_threshold", np.nan
    )
    candidate["minimum_eligible_windows"] = selected.get(
        "minimum_eligible_windows", np.nan
    )
    candidate["complexity_rank"] = int(selected.get("complexity_rank", 0))
    candidate["knowledge_triggered"] = eligible
    candidate["candidate_positive"] = base_positive | eligible
    return candidate


def _recompute_heatwave_sequence(group: pd.DataFrame) -> pd.DataFrame:
    ordered = group.sort_values("lead_time_hours").copy()
    streak = 0
    streaks: list[int] = []
    positive: list[bool] = []
    for row in ordered.itertuples(index=False):
        streak = streak + 1 if bool(row.integrated_hot_day) else 0
        streaks.append(streak)
        positive.append(bool(row.candidate_severe_hot_day or streak >= 2))
    ordered["integrated_hot_day_streak"] = streaks
    ordered["candidate_positive"] = positive
    return ordered


def heatwave_joint_candidates(
    base_details: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    """Combine cross-fitted heat rules with truth-free graph consistency rules."""
    output: list[pd.DataFrame] = []
    heat = config["heatwave"]
    for base_method, base in base_details.groupby("method", sort=False):
        base = base.copy()
        base["base_method"] = base_method
        base["base_candidate_positive"] = _bool_series(base["candidate_positive"])
        baseline = base.copy()
        baseline["method"] = f"joint_heat_{base_method}_kg_none"
        baseline["knowledge_mode"] = "none"
        baseline["near_threshold_margin_degc"] = np.nan
        baseline["temporal_minimum_near_windows"] = np.nan
        baseline["spatial_maximum_margin_degc"] = np.nan
        baseline["knowledge_triggered"] = False
        baseline["integrated_hot_day"] = _bool_series(baseline["candidate_hot_day"])
        baseline["complexity_rank"] = 0
        baseline = (
            baseline.groupby(["case_id", "region_id"], group_keys=False)
            .apply(_recompute_heatwave_sequence, include_groups=False)
            .reset_index(drop=True)
        )
        ordered_base = base.sort_values(["case_id", "region_id", "lead_time_hours"])
        baseline["case_id"] = ordered_base["case_id"].to_numpy()
        baseline["region_id"] = ordered_base["region_id"].to_numpy()
        output.append(baseline)

        for mode in heat["knowledge_modes"]:
            if mode == "none":
                continue
            for margin in heat["near_threshold_margins_degc"]:
                for minimum_windows in heat["temporal_minimum_near_windows"]:
                    for maximum_margin in heat["spatial_maximum_margins_degc"]:
                        candidate = base.copy()
                        near = candidate["candidate_tmax_degc"].astype(float) >= (
                            candidate["hot_day_threshold_degc"].astype(float)
                            - float(margin)
                        )
                        near_count = (
                            candidate.assign(_near=near)
                            .groupby(["case_id", "region_id"])["_near"]
                            .transform("sum")
                        )
                        temporal = near & (near_count >= int(minimum_windows))
                        spatial = near & (
                            candidate["source_maximum_degc"].astype(float)
                            >= candidate["hot_day_threshold_degc"].astype(float)
                            - float(maximum_margin)
                        )
                        if mode == "temporal_near_threshold":
                            eligible = temporal
                        elif mode == "spatial_hotspot":
                            eligible = spatial
                        elif mode == "temporal_or_spatial":
                            eligible = temporal | spatial
                        elif mode == "temporal_and_spatial":
                            eligible = temporal & spatial
                        else:
                            raise ValueError(f"unknown heatwave knowledge mode: {mode}")
                        eligible &= ~_bool_series(candidate["candidate_hot_day"])
                        candidate["method"] = _candidate_id(
                            f"joint_heat_{base_method}_kg_{mode}",
                            margin=margin,
                            windows=minimum_windows,
                            maxmargin=maximum_margin,
                        )
                        candidate["base_method"] = base_method
                        candidate["knowledge_mode"] = mode
                        candidate["near_threshold_margin_degc"] = float(margin)
                        candidate["temporal_minimum_near_windows"] = int(
                            minimum_windows
                        )
                        candidate["spatial_maximum_margin_degc"] = float(
                            maximum_margin
                        )
                        candidate["knowledge_triggered"] = eligible
                        candidate["integrated_hot_day"] = (
                            _bool_series(candidate["candidate_hot_day"]) | eligible
                        )
                        candidate["complexity_rank"] = {
                            "temporal_near_threshold": 1,
                            "spatial_hotspot": 1,
                            "temporal_and_spatial": 2,
                            "temporal_or_spatial": 3,
                        }[mode]
                        candidate = (
                            candidate.groupby(
                                ["case_id", "region_id"], group_keys=False
                            )
                            .apply(_recompute_heatwave_sequence, include_groups=False)
                            .reset_index(drop=True)
                        )
                        candidate["case_id"] = base.sort_values(
                            ["case_id", "region_id", "lead_time_hours"]
                        )["case_id"].to_numpy()
                        candidate["region_id"] = base.sort_values(
                            ["case_id", "region_id", "lead_time_hours"]
                        )["region_id"].to_numpy()
                        output.append(candidate)
    return pd.concat(output, ignore_index=True)


def apply_locked_heatwave_candidate(
    base: pd.DataFrame, selected: dict[str, Any]
) -> pd.DataFrame:
    """Apply one locked heatwave graph rule without reading observation columns."""
    candidate = base.copy()
    candidate["base_candidate_positive"] = _bool_series(
        candidate["candidate_positive"]
    )
    mode = str(selected["knowledge_mode"])
    if mode == "none":
        eligible = pd.Series(False, index=candidate.index)
    else:
        margin = float(selected["near_threshold_margin_degc"])
        minimum_windows = int(float(selected["temporal_minimum_near_windows"]))
        maximum_margin = float(selected["spatial_maximum_margin_degc"])
        near = candidate["candidate_tmax_degc"].astype(float) >= (
            candidate["hot_day_threshold_degc"].astype(float) - margin
        )
        near_count = (
            candidate.assign(_near=near)
            .groupby(["case_id", "region_id"])["_near"]
            .transform("sum")
        )
        temporal = near & (near_count >= minimum_windows)
        spatial = near & (
            candidate["source_maximum_degc"].astype(float)
            >= candidate["hot_day_threshold_degc"].astype(float) - maximum_margin
        )
        if mode == "temporal_near_threshold":
            eligible = temporal
        elif mode == "spatial_hotspot":
            eligible = spatial
        elif mode == "temporal_or_spatial":
            eligible = temporal | spatial
        elif mode == "temporal_and_spatial":
            eligible = temporal & spatial
        else:
            raise ValueError(f"unknown locked heatwave knowledge mode: {mode}")
        eligible &= ~_bool_series(candidate["candidate_hot_day"])
    candidate["method"] = str(selected["method"])
    candidate["base_method"] = str(selected["base_method"])
    candidate["knowledge_mode"] = mode
    candidate["near_threshold_margin_degc"] = selected.get(
        "near_threshold_margin_degc", np.nan
    )
    candidate["temporal_minimum_near_windows"] = selected.get(
        "temporal_minimum_near_windows", np.nan
    )
    candidate["spatial_maximum_margin_degc"] = selected.get(
        "spatial_maximum_margin_degc", np.nan
    )
    candidate["complexity_rank"] = int(selected.get("complexity_rank", 0))
    candidate["knowledge_triggered"] = eligible
    candidate["integrated_hot_day"] = (
        _bool_series(candidate["candidate_hot_day"]) | eligible
    )
    candidate = (
        candidate.groupby(["case_id", "region_id"], group_keys=False)
        .apply(_recompute_heatwave_sequence, include_groups=False)
        .reset_index(drop=True)
    )
    ordered = base.sort_values(["case_id", "region_id", "lead_time_hours"])
    candidate["case_id"] = ordered["case_id"].to_numpy()
    candidate["region_id"] = ordered["region_id"].to_numpy()
    return candidate


def assess_joint_heatwave(
    details: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    gates = config["heatwave"]["gates"]
    for method, group in details.groupby("method", sort=False):
        target = group[group["evaluation_scope"] == "target_window"]
        observed_hot = target[_bool_series(target["observed_hot_day"])]
        observed_nonhot = target[~_bool_series(target["observed_hot_day"])]
        event_cases = target[target["case_role"] == "event"].groupby(
            ["case_id", "region_id"]
        )["candidate_positive"].any()
        control_cases = target[target["case_role"] == "control"].groupby(
            ["case_id", "region_id"]
        )["candidate_positive"].any()
        recall = float(observed_hot["integrated_hot_day"].mean())
        specificity = float((~observed_nonhot["integrated_hot_day"]).mean())
        event_detection = float(event_cases.mean())
        control_rejection = float((~control_cases).mean())
        passes = (
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
                "base_method": str(group["base_method"].iloc[0]),
                "knowledge_mode": str(group["knowledge_mode"].iloc[0]),
                "near_threshold_margin_degc": group[
                    "near_threshold_margin_degc"
                ].iloc[0],
                "temporal_minimum_near_windows": group[
                    "temporal_minimum_near_windows"
                ].iloc[0],
                "spatial_maximum_margin_degc": group[
                    "spatial_maximum_margin_degc"
                ].iloc[0],
                "target_days": len(target),
                "observed_hot_days": len(observed_hot),
                "observed_hot_day_hits": int(observed_hot["integrated_hot_day"].sum()),
                "observed_hot_day_recall": recall,
                "observed_nonhot_days": len(observed_nonhot),
                "observed_nonhot_day_correct_negatives": int(
                    (~observed_nonhot["integrated_hot_day"]).sum()
                ),
                "observed_nonhot_day_specificity": specificity,
                "balanced_accuracy": (recall + specificity) / 2,
                "event_cases": len(event_cases),
                "event_case_detections": int(event_cases.sum()),
                "event_case_detection_fraction": event_detection,
                "control_cases": len(control_cases),
                "control_case_correct_rejections": int((~control_cases).sum()),
                "control_case_rejection_fraction": control_rejection,
                "knowledge_upgrade_count": int(group["knowledge_triggered"].sum()),
                "complexity_rank": int(group["complexity_rank"].iloc[0]),
                "passes_all_gates": passes,
            }
        )
    return pd.DataFrame(rows)


def _rank_candidates(assessment: pd.DataFrame) -> pd.DataFrame:
    ranked = assessment.copy()
    recall_column = next(column for column in ranked if column.endswith("recall"))
    specificity_column = next(
        column for column in ranked if column.endswith("specificity")
    )
    ranked["minimum_operational_skill"] = ranked[
        [
            recall_column,
            specificity_column,
            "event_case_detection_fraction",
            "control_case_rejection_fraction",
        ]
    ].min(axis=1)
    return ranked.sort_values(
        [
            "passes_all_gates",
            "minimum_operational_skill",
            "balanced_accuracy",
            "event_case_detection_fraction",
            "control_case_rejection_fraction",
            "knowledge_upgrade_count",
            "complexity_rank",
            "method",
        ],
        ascending=[False, False, False, False, False, True, True, True],
    )


def _heat_operating_points(ranked: pd.DataFrame) -> pd.DataFrame:
    """Expose balanced, conservative and recall-first trade-offs explicitly."""
    balanced = ranked.iloc[0]
    conservative_pool = ranked[
        ranked["observed_nonhot_day_specificity"].ge(0.8)
        & ranked["control_case_rejection_fraction"].eq(1.0)
    ].sort_values(
        [
            "minimum_operational_skill",
            "balanced_accuracy",
            "observed_hot_day_recall",
            "complexity_rank",
            "method",
        ],
        ascending=[False, False, False, True, True],
    )
    recall_pool = ranked.sort_values(
        [
            "observed_hot_day_recall",
            "event_case_detection_fraction",
            "observed_nonhot_day_specificity",
            "control_case_rejection_fraction",
            "complexity_rank",
            "method",
        ],
        ascending=[False, False, False, False, True, True],
    )
    points = pd.DataFrame([balanced, conservative_pool.iloc[0], recall_pool.iloc[0]])
    points.insert(0, "operating_profile", ["balanced", "conservative", "recall_first"])
    return points.reset_index(drop=True)


def _rain_assessment(
    details: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    adapted = {
        "heavy_rain": {"gates": config["heavy_rain"]["gates"]}
    }
    scored = details[details["evaluation_scope"] == "target_window"].copy()
    scored["case_id"] = (
        scored["case_id"].astype(str) + "|" + scored["region_id"].astype(str)
    )
    assessment = assess_rain(scored, adapted)
    metadata = details.groupby("method", as_index=False).agg(
        base_method=("base_method", "first"),
        knowledge_mode=("knowledge_mode", "first"),
        primary_ratio_threshold=("primary_ratio_threshold", "first"),
        support_count_threshold=("support_count_threshold", "first"),
        minimum_eligible_windows=("minimum_eligible_windows", "first"),
        complexity_rank=("complexity_rank", "first"),
    )
    assessment = assessment.merge(metadata, on="method", validate="one_to_one")
    assessment = assessment.rename(
        columns={"passes_base_rule_gates": "passes_all_gates"}
    )
    assessment["balanced_accuracy"] = (
        assessment["target_window_recall"]
        + assessment["target_window_specificity"]
    ) / 2
    assessment["knowledge_upgrade_count"] = assessment["knowledge_trigger_count"]
    return assessment


def run(
    root: Path,
    config_path: Path,
    output_dir: Path,
    lock_path: Path,
) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("status") != "retrospective_development_joint_search":
        raise ValueError("joint search must retain retrospective development label")
    if config["truth_policy"].get("candidate_may_read_independent_truth") is not False:
        raise ValueError("candidate selection must forbid independent truth")

    rain_source = load_rain_rows(root, "development", target_only=False)
    rain_details = heavy_rain_joint_candidates(rain_source, config)
    rain_assessment = _rain_assessment(rain_details, config)
    rain_ranked = _rank_candidates(rain_assessment)

    base_config_path = root / config["heatwave"]["base_config"]
    base_config = yaml.safe_load(base_config_path.read_text(encoding="utf-8"))
    heat_source = load_heatwave_development(root)
    heat_base = heatwave_candidate_rows(heat_source, base_config)
    heat_details = heatwave_joint_candidates(heat_base, config)
    heat_assessment = assess_joint_heatwave(heat_details, config)
    heat_ranked = _rank_candidates(heat_assessment)

    selected_rain = rain_ranked.iloc[0].to_dict()
    selected_heat = heat_ranked.iloc[0].to_dict()
    heat_operating_points = _heat_operating_points(heat_ranked)
    output_dir.mkdir(parents=True, exist_ok=True)
    rain_ranked.to_csv(
        output_dir / "joint_heavy_rain_candidate_assessment.csv",
        index=False,
        lineterminator="\n",
    )
    heat_ranked.to_csv(
        output_dir / "joint_heatwave_candidate_assessment.csv",
        index=False,
        lineterminator="\n",
    )
    heat_operating_points.to_csv(
        output_dir / "joint_heatwave_operating_points.csv",
        index=False,
        lineterminator="\n",
    )
    selected_rain_details = rain_details[
        rain_details["method"] == selected_rain["method"]
    ].copy()
    selected_heat_details = heat_details[
        heat_details["method"] == selected_heat["method"]
    ].copy()
    selected_rain_details.to_csv(
        output_dir / "selected_joint_heavy_rain_development_details.csv",
        index=False,
        lineterminator="\n",
    )
    selected_heat_details.to_csv(
        output_dir / "selected_joint_heatwave_development_details.csv",
        index=False,
        lineterminator="\n",
    )
    selected_rain_details["base_risk_level"] = selected_rain_details["risk_level"]
    selected_rain_details["joint_final_risk_level"] = np.where(
        selected_rain_details["knowledge_triggered"]
        & selected_rain_details["risk_level"].eq("low"),
        "medium",
        selected_rain_details["risk_level"],
    )
    rain_prediction_path = (
        output_dir / "locked_development_joint_heavy_rain_predictions.csv"
    )
    selected_rain_details[
        [
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
    ].to_csv(rain_prediction_path, index=False, lineterminator="\n")
    selected_heat_details["base_risk_level"] = np.select(
        [
            selected_heat_details["base_candidate_positive"].astype(bool),
            selected_heat_details["candidate_hot_day"].astype(bool),
        ],
        ["high", "medium"],
        default="low",
    )
    selected_heat_details["joint_final_risk_level"] = np.select(
        [
            selected_heat_details["candidate_positive"].astype(bool),
            selected_heat_details["integrated_hot_day"].astype(bool),
        ],
        ["high", "medium"],
        default="low",
    )
    heat_prediction_path = (
        output_dir / "locked_development_joint_heatwave_predictions.csv"
    )
    selected_heat_details[
        [
            "case_id",
            "region_id",
            "lead_time_hours",
            "base_method",
            "knowledge_mode",
            "base_risk_level",
            "base_candidate_positive",
            "candidate_tmax_degc",
            "hot_day_threshold_degc",
            "knowledge_triggered",
            "joint_final_risk_level",
        ]
    ].to_csv(heat_prediction_path, index=False, lineterminator="\n")

    inputs = [
        config_path,
        base_config_path,
        root / "src/saudi_warning/risk/select_joint_pipeline.py",
        root / "src/saudi_warning/risk/benchmark_integrated_candidates.py",
        root / "handoff/risk_dry_runs/development_v2_rule_review.csv",
        root / "handoff/risk_dry_runs/development_rule_review.csv",
        root / "handoff/weather_verification/heatwave_development_diagnostics.csv",
        root / "handoff/weather_verification/heatwave_v3_prospective_details.csv",
        root / "handoff/weather_verification/heatwave_v5_prospective_details.csv",
    ]
    lock = {
        "schema_version": "joint_pipeline_selection_lock_v2",
        "status": "development_selected_before_independent_evaluator_execution",
        "selection_split": "development",
        "independent_truth_used_by_selection_code": False,
        "heavy_rain": {
            "candidate_count": int(rain_assessment["method"].nunique()),
            "selected": selected_rain,
        },
        "heatwave": {
            "candidate_count": int(heat_assessment["method"].nunique()),
            "selected": selected_heat,
            "operating_points": heat_operating_points.to_dict(orient="records"),
        },
        "truth_free_development_prediction_locks": {
            "heavy_rain_path": str(rain_prediction_path.relative_to(root)).replace(
                "\\", "/"
            ),
            "heavy_rain_sha256": _sha256(rain_prediction_path),
            "heatwave_path": str(heat_prediction_path.relative_to(root)).replace(
                "\\", "/"
            ),
            "heatwave_sha256": _sha256(heat_prediction_path),
            "truth_fields_present": False,
        },
        "input_sha256": {
            str(path.relative_to(root)).replace("\\", "/"): _sha256(path)
            for path in inputs
        },
        "limitations": [
            "Candidate search is retrospective on all opened development batches.",
            "The heavy-rain independent split was previously opened and can only support a nonblind full-chain replay.",
            "Independent heatwave truth is not read by this selection module.",
        ],
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return lock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--config", type=Path, default=Path("configs/joint_pipeline_candidate_search_v2.yaml")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("handoff/model_selection/joint_v2")
    )
    parser.add_argument(
        "--lock", type=Path, default=Path("manifests/joint_pipeline_selection_lock_v2.json")
    )
    args = parser.parse_args()
    result = run(args.root, args.config, args.output_dir, args.lock)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
