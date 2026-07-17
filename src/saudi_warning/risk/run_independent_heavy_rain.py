"""Run the one-time independent heavy-rain evaluation under a frozen rule."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from saudi_warning.risk.engine import (
    _season,
    evaluate_all,
    load_rule,
    load_statistics,
    load_summaries,
    write_results,
)
from saudi_warning.risk.run_development_review import (
    build_review,
    select_development_summaries,
    write_audit,
)
from saudi_warning.risk.validation import validate_paths
from saudi_warning.verification.build_development_pairs import (
    COVERAGE_FIELDS,
    PAIR_FIELDS,
    build_imerg_pairs,
    read_csv,
    write_csv,
)
from saudi_warning.verification.metrics import compute_metrics, validate_pairs


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def independent_heavy_cases(path: Path) -> list[dict[str, str]]:
    cases = [
        row
        for row in read_csv(path)
        if row["selection_status"] == "approved"
        and row["dataset_split"] == "independent_test"
        and row["hazard"] == "heavy_rain"
    ]
    if len(cases) != 4:
        raise ValueError(f"expected 4 independent heavy-rain cases, found {len(cases)}")
    return cases


def _create_or_validate_lock(
    path: Path,
    rule_path: Path,
    files_path: Path,
    summary_path: Path,
    cases: list[dict[str, str]],
) -> dict[str, Any]:
    expected = {
        "schema_version": "independent_evaluation_lock_v1",
        "hazard": "heavy_rain",
        "dataset_split": "independent_test",
        "rule_file": rule_path.as_posix(),
        "rule_sha256": _sha256(rule_path),
        "observation_file_manifest": files_path.as_posix(),
        "observation_file_manifest_sha256": _sha256(files_path),
        "observation_summary": summary_path.as_posix(),
        "observation_summary_sha256": _sha256(summary_path),
        "case_ids": sorted(case["case_id"] for case in cases),
        "no_retuning_declaration": (
            "Frozen heavy-rain v2 must not be changed in response to this evaluation."
        ),
    }
    if path.exists():
        lock = json.loads(path.read_text(encoding="utf-8"))
        for key, value in expected.items():
            if lock.get(key) != value:
                raise ValueError(f"independent evaluation lock mismatch: {key}")
        return lock
    lock = {
        **expected,
        "opened_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return lock


def _apply_frozen_thresholds(
    pairs: pd.DataFrame,
    statistics: dict[tuple[str, str, str], dict[str, Any]],
    rule: dict[str, Any],
) -> pd.DataFrame:
    output = pairs.copy()
    config = rule["thresholds"]["precipitation"]["medium"]
    thresholds: list[float | str] = []
    for row in output.to_dict(orient="records"):
        if row["aggregation"] != "spatial_p95":
            thresholds.append("")
            continue
        period = _season(row["valid_start_time"], row["valid_end_time"])
        reference = statistics[(period, row["region_id"], "daily_precip_total")][
            config["reference_column"]
        ]
        thresholds.append(max(float(config["absolute_floor"]), float(reference)))
    output["event_threshold"] = thresholds
    return output


def _write_metric_output(
    path: Path, pairs: pd.DataFrame, rule: dict[str, Any]
) -> pd.DataFrame:
    metrics = compute_metrics(pairs)
    metrics.insert(0, "dataset_split", "independent_test")
    metrics.insert(1, "evaluation_status", "one_time_locked")
    metrics.insert(2, "rule_id", rule["rule_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(path, index=False, float_format="%.8g")
    return metrics


def _write_result_manifest(path: Path, results: list[dict[str, Any]], output_dir: Path) -> None:
    fields = [
        "file",
        "sha256",
        "case_id",
        "region_id",
        "lead_time_hours",
        "risk_level",
        "rule_id",
        "dataset_split",
        "validation_status",
    ]
    rows = []
    for result in results:
        result_path = output_dir / (
            f"risk_{result['case_id']}_{result['region_id']}_{result['hazard']}.json"
        )
        rows.append(
            {
                "file": result_path.as_posix(),
                "sha256": _sha256(result_path),
                "case_id": result["case_id"],
                "region_id": result["region_id"],
                "lead_time_hours": result["lead_time_hours"],
                "risk_level": result["risk_level"],
                "rule_id": result["rule_id"],
                "dataset_split": "independent_test",
                "validation_status": "passed",
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path("configs/case_catalog_candidates.csv")
    )
    parser.add_argument(
        "--forecast-summary",
        type=Path,
        default=Path("handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv"),
    )
    parser.add_argument(
        "--imerg-summary",
        type=Path,
        default=Path("manifests/imerg_2020_saudi_daily_summary.csv"),
    )
    parser.add_argument(
        "--imerg-files", type=Path, default=Path("manifests/imerg_v07b_daily_files.csv")
    )
    parser.add_argument(
        "--statistics",
        type=Path,
        default=Path("handoff/mazu_statistics/mazu_2025_adm1_descriptive_stats.csv"),
    )
    parser.add_argument(
        "--heavy-rule", type=Path, default=Path("configs/heavy_rain_rules_v2.yaml")
    )
    parser.add_argument(
        "--heat-rule", type=Path, default=Path("configs/heatwave_rules_v2.yaml")
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path("manifests/independent_heavy_rain_evaluation_lock.json"),
    )
    parser.add_argument(
        "--pairs",
        type=Path,
        default=Path("handoff/weather_verification/independent_heavy_rain_pairs.csv"),
    )
    parser.add_argument(
        "--coverage",
        type=Path,
        default=Path("manifests/independent_heavy_rain_pairing_coverage.csv"),
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=Path("handoff/weather_verification/independent_heavy_rain_metrics.csv"),
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=Path("handoff/weather_verification/independent_heavy_rain_rule_review.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("handoff/risk_results/independent_heavy_rain"),
    )
    parser.add_argument(
        "--result-manifest",
        type=Path,
        default=Path("manifests/independent_heavy_rain_risk_manifest.csv"),
    )
    parser.add_argument(
        "--schema", type=Path, default=Path("schemas/risk_result.schema.json")
    )
    parser.add_argument(
        "--regions", type=Path, default=Path("configs/region_registry.csv")
    )
    args = parser.parse_args()

    rule = load_rule(args.heavy_rule, "heavy_rain")
    heat_rule = load_rule(args.heat_rule, "heatwave")
    if rule["status"] != "frozen":
        raise ValueError("independent evaluation requires frozen heavy-rain rule")
    cases = independent_heavy_cases(args.catalog)
    lock = _create_or_validate_lock(
        args.lock, args.heavy_rule, args.imerg_files, args.imerg_summary, cases
    )
    forecast_rows = read_csv(args.forecast_summary)
    pair_rows, audit = build_imerg_pairs(cases, forecast_rows, read_csv(args.imerg_summary))
    if len(pair_rows) != 54 or len(audit) != 54:
        raise ValueError(f"expected 54 independent pairs, found {len(pair_rows)}/{len(audit)}")
    if {row["pair_status"] for row in audit} != {"paired_accepted"}:
        raise ValueError("independent IMERG pairing is incomplete")
    pairs = _apply_frozen_thresholds(
        pd.DataFrame(pair_rows), load_statistics(args.statistics), rule
    )
    errors = validate_pairs(pairs)
    if errors:
        raise ValueError("; ".join(errors))
    write_csv(args.pairs, pairs.to_dict(orient="records"), PAIR_FIELDS)
    write_csv(args.coverage, audit, COVERAGE_FIELDS)
    _write_metric_output(args.metrics, pairs, rule)

    summaries = select_development_summaries(load_summaries(args.forecast_summary), cases)
    all_results = evaluate_all(
        summaries,
        load_statistics(args.statistics),
        rule,
        heat_rule,
        lock["opened_at"],
    )
    results, review = build_review(cases, all_results)
    results = [result for result in results if result["hazard"] == "heavy_rain"]
    if len(results) != 18:
        raise ValueError(f"expected 18 independent risk results, found {len(results)}")
    for result in results:
        result["verification"] = {
            "status": "independent_test_one_time_locked",
            "dataset_split": "independent_test",
            "observation_source": "IMERG Final Run V07B",
            "pair_qc_status": "accepted",
            "metrics_file": args.metrics.as_posix(),
            "evaluation_lock": args.lock.as_posix(),
            "no_retuning": True,
        }
    write_results(results, args.output_dir, filename_prefix="risk")
    write_audit(args.review, review)
    paths = sorted(args.output_dir.glob("*.json"))
    report = validate_paths(paths, args.schema, args.regions, require_frozen=True)
    failures = {path: errors for path, errors in report.items() if errors}
    if failures:
        raise ValueError(f"independent risk validation failed: {failures}")
    _write_result_manifest(args.result_manifest, results, args.output_dir)
    print("independent heavy-rain evaluation completed and locked")
    print(f"pairs={len(pairs)} metrics=12 risk_results={len(results)}")
    print(args.metrics)
    print(args.review)


if __name__ == "__main__":
    main()
