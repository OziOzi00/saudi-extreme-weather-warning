"""Diagnose blocked heatwave development results without opening independent data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


KEYS = ["case_id", "case_role", "lead_time_hours", "region_id"]


def _attribution(row: pd.Series) -> str:
    if row["evaluation_scope"] != "target_window":
        return "context_only"
    if row["case_role"] == "control":
        return "correct_control" if not bool(row["candidate_positive"]) else "control_false_alarm"
    if row["candidate_positive"]:
        return "event_window_hit"
    if not row["observed_hot_day"]:
        return "event_label_not_observed_hot_day"
    if row["corrected_hot_day"] and not row["regional_p95_hot_day"]:
        return "aggregation_proxy_gap"
    if row["regional_p95_hot_day"] and row["forecast_duration_days"] < 2:
        return "duration_gate"
    return "forecast_or_correction_shortfall"


def _aggregation_sensitivity(rows: pd.DataFrame) -> list[dict[str, Any]]:
    results = []
    for maximum_weight in (0.0, 0.25, 0.5, 0.6, 0.75, 1.0):
        candidate = rows.copy()
        candidate["candidate_tmax_degc"] = (
            candidate["source_spatial_p95_degc"]
            + maximum_weight
            * (candidate["source_maximum_degc"] - candidate["source_spatial_p95_degc"])
            + candidate["fold_correction_degc"]
        )
        candidate["candidate_hot"] = candidate["candidate_tmax_degc"] >= candidate["primary_threshold"]
        candidate["candidate_severe"] = candidate["candidate_tmax_degc"] >= candidate["severe_threshold"]
        candidate["sensitivity_positive"] = False
        for _, group in candidate.groupby("case_id", sort=False):
            duration = 0
            for index in group.sort_values("lead_time_hours").index:
                duration = duration + 1 if candidate.at[index, "candidate_hot"] else 0
                candidate.at[index, "sensitivity_positive"] = bool(
                    duration >= 2 or candidate.at[index, "candidate_severe"]
                )
        event_target = candidate[
            (candidate["case_role"] == "event")
            & (candidate["evaluation_scope"] == "target_window")
        ]
        control_target = candidate[
            (candidate["case_role"] == "control")
            & (candidate["evaluation_scope"] == "target_window")
        ]
        observed_hot = event_target[event_target["observed_hot_day"]]
        results.append(
            {
                "maximum_weight": maximum_weight,
                "event_target_hits": int(event_target["sensitivity_positive"].sum()),
                "event_target_windows": len(event_target),
                "control_correct_negatives": int((~control_target["sensitivity_positive"]).sum()),
                "control_target_windows": len(control_target),
                "observed_hot_event_hits": int(observed_hot["sensitivity_positive"].sum()),
                "observed_hot_event_windows": len(observed_hot),
                "exploratory_only": True,
            }
        )
    return results


def diagnose(
    pairs_path: Path, review_path: Path, summaries_path: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    pairs = pd.read_csv(pairs_path)
    review = pd.read_csv(review_path)
    merged = pairs.merge(review, on=KEYS, how="inner", validate="one_to_one")
    if len(merged) != len(pairs) or len(merged) != len(review):
        raise ValueError("heatwave pair and rule-review rows are not one-to-one")

    merged["raw_error_degc"] = merged["raw_forecast_tmax_degc"] - merged["observed_tmax_degc"]
    merged["corrected_error_degc"] = (
        merged["corrected_forecast_tmax_degc"] - merged["observed_tmax_degc"]
    )
    merged["regional_p95_margin_degc"] = merged["primary_value"] - merged["primary_threshold"]
    merged["regional_p95_hot_day"] = merged["regional_p95_margin_degc"] >= 0
    merged["candidate_positive"] = merged["risk_level"].isin(["medium", "high"])
    merged["forecast_duration_days"] = pd.to_numeric(
        merged["primary_stage_or_duration"], errors="raise"
    ).astype(int)
    merged["diagnostic_attribution"] = merged.apply(_attribution, axis=1)

    summaries = pd.read_csv(summaries_path)
    summaries = summaries[
        (summaries["indicator"] == "tmax_c")
        & (summaries["region_id"].isin(merged["region_id"]))
    ].copy()
    summaries["case_id"] = (
        summaries["initial_time"].str.slice(0, 10).str.replace("-", "", regex=False) + "_00"
    )
    summaries = summaries.rename(
        columns={
            "spatial_p95": "source_spatial_p95_degc",
            "maximum": "source_maximum_degc",
        }
    )[["case_id", "region_id", "lead_time_hours", "source_spatial_p95_degc", "source_maximum_degc"]]
    merged = merged.merge(
        summaries,
        on=["case_id", "region_id", "lead_time_hours"],
        how="left",
        validate="one_to_one",
    )
    if merged[["source_spatial_p95_degc", "source_maximum_degc"]].isna().any().any():
        raise ValueError("missing source regional tmax summaries")
    reconstructed = merged["source_spatial_p95_degc"] + merged["fold_correction_degc"]
    if (reconstructed - merged["primary_value"]).abs().max() > 1e-6:
        raise ValueError("rule review primary values do not match corrected regional P95")

    event_target = merged[
        (merged["case_role"] == "event") & (merged["evaluation_scope"] == "target_window")
    ]
    control_target = merged[
        (merged["case_role"] == "control") & (merged["evaluation_scope"] == "target_window")
    ]
    observed_positive = event_target[event_target["observed_hot_day"]]
    observed_negative = event_target[~event_target["observed_hot_day"]]
    misses = event_target[~event_target["candidate_positive"]]

    lead_diagnostics = []
    for lead, group in merged.groupby("lead_time_hours", sort=True):
        lead_diagnostics.append(
            {
                "lead_time_hours": int(lead),
                "pair_count": len(group),
                "raw_bias_degc": float(group["raw_error_degc"].mean()),
                "corrected_bias_degc": float(group["corrected_error_degc"].mean()),
                "raw_mae_degc": float(group["raw_error_degc"].abs().mean()),
                "corrected_mae_degc": float(group["corrected_error_degc"].abs().mean()),
            }
        )

    summary: dict[str, Any] = {
        "schema_version": "heatwave_development_diagnostic_v1",
        "scope": "development_only",
        "independent_heatwave_opened": False,
        "pair_count": len(merged),
        "case_count": int(merged["case_id"].nunique()),
        "event_target_windows": len(event_target),
        "candidate_event_window_hits": int(event_target["candidate_positive"].sum()),
        "candidate_event_window_misses": len(misses),
        "control_target_windows": len(control_target),
        "candidate_control_correct_negatives": int((~control_target["candidate_positive"]).sum()),
        "observed_hot_event_target_windows": int(event_target["observed_hot_day"].sum()),
        "observed_nonhot_event_target_windows": int((~event_target["observed_hot_day"]).sum()),
        "candidate_hits_among_observed_hot_event_windows": int(
            observed_positive["candidate_positive"].sum()
        ),
        "candidate_positives_among_observed_nonhot_event_windows": int(
            observed_negative["candidate_positive"].sum()
        ),
        "miss_attribution_counts": {
            str(key): int(value)
            for key, value in misses["diagnostic_attribution"].value_counts().items()
        },
        "raw_bias_degc": float(merged["raw_error_degc"].mean()),
        "corrected_bias_degc": float(merged["corrected_error_degc"].mean()),
        "raw_mae_degc": float(merged["raw_error_degc"].abs().mean()),
        "corrected_mae_degc": float(merged["corrected_error_degc"].abs().mean()),
        "lead_diagnostics": lead_diagnostics,
        "aggregation_sensitivity": _aggregation_sensitivity(merged),
        "diagnostic_conclusion": "blocked_metric_mixes_forecast_rule_and_label_effects",
        "recommended_next_action": "preregister_development_only_candidate_comparison",
        "prohibited_action": "do_not_open_or_tune_on_independent_heatwave",
    }

    output_fields = [
        *KEYS,
        "evaluation_scope",
        "candidate_outcome",
        "risk_level",
        "raw_forecast_tmax_degc",
        "corrected_forecast_tmax_degc",
        "observed_tmax_degc",
        "event_threshold_degc",
        "raw_error_degc",
        "corrected_error_degc",
        "corrected_hot_day",
        "observed_hot_day",
        "primary_value",
        "primary_threshold",
        "regional_p95_margin_degc",
        "regional_p95_hot_day",
        "source_spatial_p95_degc",
        "source_maximum_degc",
        "forecast_duration_days",
        "candidate_positive",
        "diagnostic_attribution",
    ]
    return merged[output_fields].sort_values(KEYS).reset_index(drop=True), summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs",
        type=Path,
        default=Path("handoff/weather_verification/heatwave_bias_cv_v2_pairs.csv"),
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=Path("handoff/risk_dry_runs/heatwave_bias_cv_v2_rule_review.csv"),
    )
    parser.add_argument(
        "--summaries",
        type=Path,
        default=Path("handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv"),
    )
    parser.add_argument(
        "--row-output",
        type=Path,
        default=Path("handoff/weather_verification/heatwave_development_diagnostics.csv"),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("manifests/heatwave_development_diagnostic_summary.json"),
    )
    args = parser.parse_args()
    rows, summary = diagnose(args.pairs, args.review, args.summaries)
    args.row_output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(args.row_output, index=False)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(rows)} diagnostic rows and summary; independent heatwave unopened.")


if __name__ == "__main__":
    main()
