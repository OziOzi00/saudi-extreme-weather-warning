"""Validate one MAZU-like NetCDF or every matching file in a directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from saudi_warning.forecasting.validation import (
    validate_mazu_like_file,
    validate_mazu_like_sequence,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    paths = (
        sorted(args.target.glob("mazu_like_*_lead*.nc"))
        if args.target.is_dir()
        else [args.target]
    )
    if not paths:
        raise SystemExit(f"no MAZU-like NetCDF files found at {args.target}")
    reports = [validate_mazu_like_file(path) for path in paths]
    sequence_errors: list[str] = []
    if args.target.is_dir():
        groups: dict[str, list[Path]] = {}
        for path, report in zip(paths, reports, strict=True):
            initial_time = str(report.metadata.get("initial_time") or path.name[:22])
            groups.setdefault(initial_time, []).append(path)
        for initial_time, group_paths in groups.items():
            for error in validate_mazu_like_sequence(group_paths):
                sequence_errors.append(f"{initial_time}: {error}")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "valid": not any(not report.valid for report in reports)
                    and not sequence_errors,
                    "files": [report.to_dict() for report in reports],
                    "sequence_errors": sequence_errors,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(args.report)
    failures = [report for report in reports if not report.valid]
    for report in reports:
        print(f"{report.path}: {'PASS' if report.valid else 'FAIL'}")
        for warning in report.warnings:
            print(f"  warning: {warning}")
        for error in report.errors:
            print(f"  error: {error}")
    if args.target.is_dir():
        for error in sequence_errors:
            print(f"  sequence error: {error}")
    if failures or sequence_errors:
        raise SystemExit(
            f"validation failed: files={len(failures)}/{len(reports)} "
            f"sequence_errors={len(sequence_errors)}"
        )
    print(f"validated {len(reports)} MAZU-like NetCDF files")


if __name__ == "__main__":
    main()
