"""Replay locked joint weather-plus-knowledge pipelines on independent splits."""

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
    _fold_correction,
    _regional_thresholds,
    load_heatwave_development,
    load_rain_rows,
)
from saudi_warning.risk.select_joint_pipeline import (
    _rain_assessment,
    apply_locked_heatwave_candidate,
    apply_locked_heavy_rain_candidate,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _selected_base_details(
    development: pd.DataFrame,
    independent: pd.DataFrame,
    base_method: str,
    base_config: dict[str, Any],
) -> pd.DataFrame:
    maximum_weight = 0.0
    fitted_method = base_method
    if base_method.startswith("blend") and base_method.endswith("_pooled_loco"):
        maximum_weight = (
            float(base_method.removeprefix("blend").split("_", maxsplit=1)[0])
            / 100
        )
        fitted_method = "pooled_median_loco"
    elif base_method == "maximum_pooled_loco":
        maximum_weight = 1.0
        fitted_method = "pooled_median_loco"

    training = development.copy()
    held = independent.copy()
    for frame in (training, held):
        frame["source_spatial_p95_degc"] = frame["raw_forecast_tmax_degc"]
        frame["base_aggregated_tmax_degc"] = frame[
            "raw_forecast_tmax_degc"
        ].astype(float) + maximum_weight * (
            frame["source_maximum_degc"].astype(float)
            - frame["raw_forecast_tmax_degc"].astype(float)
        )
        frame["raw_forecast_tmax_degc"] = frame[
            "base_aggregated_tmax_degc"
        ]
    correction = _fold_correction(fitted_method, training, held, base_config)
    limits = base_config["heatwave"]["correction_clip_degc"]
    held["method"] = base_method
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
        held["candidate_tmax_degc"]
        >= held["severe_hot_day_threshold_degc"]
    )
    ordered = held.sort_values(["case_id", "region_id", "lead_time_hours"]).copy()
    streaks: list[int] = []
    positives: list[bool] = []
    for _, group in ordered.groupby(["case_id", "region_id"], sort=False):
        streak = 0
        for row in group.itertuples(index=False):
            streak = streak + 1 if bool(row.candidate_hot_day) else 0
            streaks.append(streak)
            positives.append(bool(row.candidate_severe_hot_day or streak >= 2))
    ordered["forecast_hot_day_streak"] = streaks
    ordered["candidate_positive"] = positives
    return ordered


def load_heatwave_independent(root: Path) -> pd.DataFrame:
    """Open the approved 20200729 independent case only in this evaluator."""
    catalog = pd.read_csv(root / "configs/case_catalog_candidates.csv")
    selected = catalog[
        (catalog["case_id"] == "20200729_00")
        & (catalog["dataset_split"] == "independent_test")
        & (catalog["hazard"] == "heatwave")
        & (catalog["selection_status"] == "approved")
    ]
    if len(selected) != 1:
        raise ValueError("expected one approved independent heatwave case")
    regions = str(selected.iloc[0]["target_region_ids"]).split(";")
    summaries = pd.read_csv(
        root / "handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv"
    )
    summaries = summaries[
        summaries["source_file"].astype(str).str.contains("20200729_00")
        & (summaries["indicator"] == "tmax_c")
        & summaries["region_id"].isin(regions)
    ].copy()
    if len(summaries) != 6:
        raise ValueError("expected 2 regions x 3 independent forecast windows")

    observations = pd.read_csv(
        root / "manifests/ssod_v2_saudi_2020_daily_summary.csv"
    )
    observations = observations[
        observations["region_id"].isin(regions)
        & (observations["variable"] == "tmax_c")
        & (observations["aggregation"] == "station_max")
        & observations["date"].isin(
            ["2020-07-29", "2020-07-30", "2020-07-31"]
        )
    ][["region_id", "date", "observed_value", "station_count"]].copy()
    if len(observations) != 6:
        raise ValueError("expected complete SSOD independent observations")

    stats = pd.read_csv(
        root / "handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv"
    )
    rows: list[dict[str, Any]] = []
    for item in summaries.itertuples(index=False):
        lead = int(item.lead_time_hours)
        valid_date = (
            pd.Timestamp("2020-07-29") + pd.Timedelta(days=lead // 24 - 1)
        ).strftime("%Y-%m-%d")
        observation = observations[
            (observations["region_id"] == item.region_id)
            & (observations["date"] == valid_date)
        ].iloc[0]
        hot_threshold, severe_threshold = _regional_thresholds(
            stats, str(item.region_id), "JJA"
        )
        observed = float(observation["observed_value"])
        rows.append(
            {
                "source_group": "2020_independent_existing_split",
                "case_id": "20200729_00",
                "case_role": "event",
                "region_id": str(item.region_id),
                "lead_time_hours": lead,
                "evaluation_scope": (
                    "context_only" if lead == 24 else "target_window"
                ),
                "raw_forecast_tmax_degc": float(item.spatial_p95),
                "source_maximum_degc": float(item.maximum),
                "observed_tmax_degc": observed,
                "hot_day_threshold_degc": hot_threshold,
                "severe_hot_day_threshold_degc": severe_threshold,
                "observed_hot_day": observed >= hot_threshold,
                "observation_station_count": int(observation["station_count"]),
                "valid_date": valid_date,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["case_id", "region_id", "lead_time_hours"]
    )


def _heatwave_independent_assessment(details: pd.DataFrame) -> dict[str, Any]:
    target = details[details["evaluation_scope"] == "target_window"].copy()
    hot = target[target["observed_hot_day"].astype(bool)]
    nonhot = target[~target["observed_hot_day"].astype(bool)]
    units = target.groupby(["case_id", "region_id"])["candidate_positive"].any()
    return {
        "dataset_split": "independent_test",
        "evaluation_character": "existing_split_full_chain_replay",
        "target_days": len(target),
        "observed_hot_days": len(hot),
        "observed_hot_day_hits": int(hot["integrated_hot_day"].sum()),
        "observed_hot_day_recall": (
            float(hot["integrated_hot_day"].mean()) if len(hot) else None
        ),
        "observed_nonhot_days": len(nonhot),
        "observed_nonhot_day_specificity": (
            float((~nonhot["integrated_hot_day"]).mean()) if len(nonhot) else None
        ),
        "event_region_units": len(units),
        "event_region_unit_detections": int(units.sum()),
        "event_region_unit_detection_fraction": float(units.mean()),
        "knowledge_upgrade_count": int(details["knowledge_triggered"].sum()),
        "limitation": "No independent heatwave control case is available, so false-alarm skill cannot be estimated.",
    }


def run(
    root: Path,
    config_path: Path,
    lock_path: Path,
    output_dir: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for relative_path, expected_hash in lock["input_sha256"].items():
        source = root / relative_path
        if not source.exists() or _sha256(source) != expected_hash:
            raise ValueError(f"selection input changed after lock: {relative_path}")
    if lock.get("independent_truth_used_by_selection_code") is not False:
        raise ValueError("selection lock does not prove independent isolation")

    rain_source = load_rain_rows(root, "independent_test", target_only=False)
    rain_method = lock["heavy_rain"]["selected"]["method"]
    rain_selected = apply_locked_heavy_rain_candidate(
        rain_source, lock["heavy_rain"]["selected"]
    )
    rain_assessment = _rain_assessment(rain_selected, config).iloc[0].to_dict()
    rain_assessment["evaluation_character"] = "nonblind_existing_split_full_chain_replay"

    base_config = yaml.safe_load(
        (root / config["heatwave"]["base_config"]).read_text(encoding="utf-8")
    )
    heat_development = load_heatwave_development(root)
    heat_independent = load_heatwave_independent(root)
    truth_columns = [
        "case_id",
        "region_id",
        "lead_time_hours",
        "observed_tmax_degc",
        "observed_hot_day",
        "observation_station_count",
    ]
    heat_truth = heat_independent[truth_columns].copy()
    heat_forecast_features = heat_independent.drop(
        columns=[
            "observed_tmax_degc",
            "observed_hot_day",
            "observation_station_count",
        ]
    )
    heat_base_method = lock["heatwave"]["selected"]["base_method"]
    heat_base = _selected_base_details(
        heat_development, heat_forecast_features, heat_base_method, base_config
    )
    heat_method = lock["heatwave"]["selected"]["method"]
    heat_selected = apply_locked_heatwave_candidate(
        heat_base, lock["heatwave"]["selected"]
    )
    heat_selected = heat_selected.merge(
        heat_truth,
        on=["case_id", "region_id", "lead_time_hours"],
        how="left",
        validate="one_to_one",
    )
    heat_assessment = _heatwave_independent_assessment(heat_selected)

    output_dir.mkdir(parents=True, exist_ok=True)
    rain_selected["base_risk_level"] = rain_selected["risk_level"]
    rain_selected["joint_final_risk_level"] = np.where(
        rain_selected["knowledge_triggered"] & rain_selected["risk_level"].eq("low"),
        "medium",
        rain_selected["risk_level"],
    )
    rain_prediction_columns = [
        "case_id",
        "prediction_case_id",
        "region_id",
        "lead_time_hours",
        "base_method",
        "knowledge_mode",
        "base_risk_level",
        "v2_positive",
        "knowledge_triggered",
        "candidate_positive",
        "joint_final_risk_level",
        "primary_ratio",
        "support_count",
    ]
    rain_prediction_path = output_dir / "locked_joint_heavy_rain_predictions.csv"
    rain_selected[rain_prediction_columns].to_csv(
        rain_prediction_path, index=False, lineterminator="\n"
    )
    heat_selected["base_risk_level"] = np.select(
        [
            heat_selected["base_candidate_positive"].astype(bool),
            heat_selected["candidate_hot_day"].astype(bool),
        ],
        ["high", "medium"],
        default="low",
    )
    heat_selected["joint_final_risk_level"] = np.select(
        [
            heat_selected["candidate_positive"].astype(bool),
            heat_selected["integrated_hot_day"].astype(bool),
        ],
        ["high", "medium"],
        default="low",
    )
    heat_prediction_columns = [
        "case_id",
        "region_id",
        "lead_time_hours",
        "valid_date",
        "base_method",
        "knowledge_mode",
        "base_risk_level",
        "base_candidate_positive",
        "candidate_tmax_degc",
        "hot_day_threshold_degc",
        "candidate_hot_day",
        "knowledge_triggered",
        "integrated_hot_day",
        "candidate_positive",
        "joint_final_risk_level",
    ]
    heat_prediction_path = output_dir / "locked_joint_heatwave_predictions.csv"
    heat_selected[heat_prediction_columns].to_csv(
        heat_prediction_path, index=False, lineterminator="\n"
    )
    rain_selected.to_csv(
        output_dir / "independent_joint_heavy_rain_details.csv",
        index=False,
        lineterminator="\n",
    )
    heat_selected.to_csv(
        output_dir / "independent_joint_heatwave_details.csv",
        index=False,
        lineterminator="\n",
    )
    manifest = {
        "schema_version": "joint_pipeline_full_chain_evaluation_v2",
        "selection_lock_sha256": _sha256(lock_path),
        "prediction_locks": {
            "heavy_rain_path": str(rain_prediction_path).replace("\\", "/"),
            "heavy_rain_sha256": _sha256(rain_prediction_path),
            "heatwave_path": str(heat_prediction_path).replace("\\", "/"),
            "heatwave_sha256": _sha256(heat_prediction_path),
            "truth_fields_present_in_prediction_locks": False,
        },
        "heavy_rain": {
            "selected_method": rain_method,
            "development": lock["heavy_rain"]["selected"],
            "independent_replay": rain_assessment,
        },
        "heatwave": {
            "selected_method": heat_method,
            "development": lock["heatwave"]["selected"],
            "independent_replay": heat_assessment,
        },
        "interpretation": {
            "heavy_rain": "joint pipeline may be compared on the existing split, but the split was previously opened",
            "heatwave": "event recall can be replayed, but no independent control exists and the repository already contains descriptive truth",
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--config", type=Path, default=Path("configs/joint_pipeline_candidate_search_v2.yaml")
    )
    parser.add_argument(
        "--lock", type=Path, default=Path("manifests/joint_pipeline_selection_lock_v2.json")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("handoff/model_selection/joint_v2")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/joint_pipeline_full_chain_evaluation_v2.json"),
    )
    args = parser.parse_args()
    result = run(args.root, args.config, args.lock, args.output_dir, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
