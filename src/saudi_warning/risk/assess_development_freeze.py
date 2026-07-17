"""Assess hazard-specific rule freeze gates from development-only artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


OUTPUT_COLUMNS = [
    "hazard",
    "rule_id",
    "rule_status",
    "event_cases",
    "control_cases",
    "event_target_windows",
    "candidate_hits",
    "target_window_recall",
    "control_target_windows",
    "candidate_correct_negatives",
    "target_window_specificity",
    "event_case_detection_fraction",
    "control_case_rejection_fraction",
    "observation_qc_statuses",
    "freeze_recommendation",
    "blocking_reasons",
]


def _rule(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _fraction(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _observation_statuses(pairs: pd.DataFrame, hazard: str) -> set[str]:
    variables = (
        {"daily_precip_total"} if hazard == "heavy_rain" else {"tmax_c", "tmin_c"}
    )
    return set(pairs.loc[pairs["variable"].isin(variables), "qc_status"].astype(str))


def assess_hazard(
    audit: pd.DataFrame, pairs: pd.DataFrame, rule: dict[str, Any]
) -> dict[str, Any]:
    hazard = str(rule["hazard"])
    rows = audit[
        (audit["hazard"] == hazard) & (audit["evaluation_scope"] == "target_window")
    ].copy()
    events = rows[rows["case_role"] == "event"]
    controls = rows[rows["case_role"] == "control"]
    event_cases = int(events["case_id"].nunique())
    control_cases = int(controls["case_id"].nunique())
    hits = int((events["candidate_outcome"] == "candidate_hit").sum())
    correct_negatives = int(
        (controls["candidate_outcome"] == "candidate_correct_negative").sum()
    )
    event_case_hits = int(
        events.groupby("case_id")["candidate_outcome"]
        .apply(lambda values: (values == "candidate_hit").any())
        .sum()
    )
    rejected_control_cases = int(
        controls.groupby("case_id")["candidate_outcome"]
        .apply(lambda values: (values == "candidate_correct_negative").all())
        .sum()
    )
    recall = _fraction(hits, len(events))
    specificity = _fraction(correct_negatives, len(controls))
    event_case_detection = _fraction(event_case_hits, event_cases)
    control_case_rejection = _fraction(rejected_control_cases, control_cases)
    statuses = _observation_statuses(pairs, hazard)
    gates = rule.get("freeze_gates", {})
    reasons: list[str] = []
    if event_cases < int(gates.get("minimum_event_cases", 0)):
        reasons.append("insufficient_event_cases")
    if control_cases < int(gates.get("minimum_control_cases", 0)):
        reasons.append("insufficient_control_cases")
    if recall < float(gates.get("minimum_target_window_recall", 0.0)):
        reasons.append("target_window_recall_below_gate")
    if specificity < float(gates.get("minimum_target_window_specificity", 0.0)):
        reasons.append("target_window_specificity_below_gate")
    if event_case_detection < float(
        gates.get("minimum_event_case_detection_fraction", 0.0)
    ):
        reasons.append("event_case_detection_below_gate")
    if control_case_rejection < float(
        gates.get("required_control_case_rejection_fraction", 0.0)
    ):
        reasons.append("control_case_rejection_below_gate")
    required_qc = gates.get("observation_qc_required")
    if required_qc is not None and statuses != {str(required_qc)}:
        reasons.append("observation_qc_not_accepted")
    return {
        "hazard": hazard,
        "rule_id": rule["rule_id"],
        "rule_status": rule["status"],
        "event_cases": event_cases,
        "control_cases": control_cases,
        "event_target_windows": len(events),
        "candidate_hits": hits,
        "target_window_recall": recall,
        "control_target_windows": len(controls),
        "candidate_correct_negatives": correct_negatives,
        "target_window_specificity": specificity,
        "event_case_detection_fraction": event_case_detection,
        "control_case_rejection_fraction": control_case_rejection,
        "observation_qc_statuses": ";".join(sorted(statuses)),
        "freeze_recommendation": "eligible_to_freeze" if not reasons else "blocked",
        "blocking_reasons": ";".join(reasons),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("handoff/risk_dry_runs/development_v2_rule_review.csv"),
    )
    parser.add_argument(
        "--pairs",
        type=Path,
        default=Path("handoff/weather_verification/development_pairs.csv"),
    )
    parser.add_argument(
        "--heavy-rule", type=Path, default=Path("configs/heavy_rain_rules_v2.yaml")
    )
    parser.add_argument(
        "--heat-rule", type=Path, default=Path("configs/heatwave_rules_v2.yaml")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("manifests/development_v2_freeze_assessment.csv"),
    )
    args = parser.parse_args()

    audit = pd.read_csv(args.audit)
    pairs = pd.read_csv(args.pairs)
    rows = [
        assess_hazard(audit, pairs, _rule(args.heavy_rule)),
        assess_hazard(audit, pairs, _rule(args.heat_rule)),
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=OUTPUT_COLUMNS).to_csv(
        args.output, index=False, float_format="%.6g"
    )
    print(args.output)
    for row in rows:
        print(
            f"{row['hazard']}={row['freeze_recommendation']} "
            f"recall={row['target_window_recall']:.3f} "
            f"specificity={row['target_window_specificity']:.3f}"
        )


if __name__ == "__main__":
    main()
