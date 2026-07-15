"""Preflight a v1 case catalog without downloading GraphCast data."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from saudi_warning.forecasting.graphcast_loader import _cache_path, cache_file_is_valid
from saudi_warning.forecasting.run_batch import REQUIRED_STEPS, load_catalog, output_paths
from saudi_warning.forecasting.validation import validate_mazu_like_file


def preflight_rows(catalog: Path, output_dir: Path, cache_dir: Path) -> list[dict[str, str]]:
    """Build a deterministic preflight report for every catalog case."""
    rows: list[dict[str, str]] = []
    for case in load_catalog(catalog):
        paths = output_paths(output_dir, case.initial_time)
        output_states = []
        issues = []
        for lead, path in paths.items():
            if not path.exists():
                output_states.append(f"lead{lead:03d}:missing")
                continue
            report = validate_mazu_like_file(path, case.initial_time, lead)
            if report.valid:
                output_states.append(f"lead{lead:03d}:valid")
            else:
                output_states.append(f"lead{lead:03d}:invalid")
                issues.extend(f"lead{lead:03d}:{error}" for error in report.errors)
        missing_steps = [
            step
            for step in REQUIRED_STEPS
            if not cache_file_is_valid(_cache_path(cache_dir, case.initial_time, step))
        ]
        valid_outputs = sum(state.endswith(":valid") for state in output_states)
        rows.append(
            {
                "case_id": case.case_id,
                "initial_time": case.initial_time,
                "event_type": case.event_type,
                "output_state": ";".join(output_states),
                "valid_output_count": str(valid_outputs),
                "missing_cache_steps": ";".join(map(str, missing_steps)),
                "ready_for_b": "yes" if valid_outputs == 3 and not issues else "no",
                "issues": " | ".join(issues),
            }
        )
    return rows


def write_report(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id",
        "initial_time",
        "event_type",
        "output_state",
        "valid_output_count",
        "missing_cache_steps",
        "ready_for_b",
        "issues",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("handoff/mazu_like"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw/graphcast_2020"))
    parser.add_argument(
        "--report", type=Path, default=Path("outputs/case_catalog_preflight.csv")
    )
    parser.add_argument(
        "--fail-on-invalid-existing",
        action="store_true",
        help="exit non-zero when an existing output fails validation",
    )
    args = parser.parse_args()
    rows = preflight_rows(args.catalog, args.output_dir, args.cache_dir)
    write_report(args.report, rows)
    print(args.report)
    invalid = [row for row in rows if row["issues"]]
    for row in rows:
        print(
            f"case_id={row['case_id']} ready_for_b={row['ready_for_b']} "
            f"outputs={row['output_state']}"
        )
    if invalid and args.fail_on_invalid_existing:
        raise SystemExit(f"{len(invalid)} cases contain invalid existing outputs")


if __name__ == "__main__":
    main()
