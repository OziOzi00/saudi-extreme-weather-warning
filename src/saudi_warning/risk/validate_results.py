"""Validate one Risk JSON file or every JSON file below a directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from saudi_warning.risk.validation import validate_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument(
        "--schema", type=Path, default=Path("schemas/risk_result.schema.json")
    )
    parser.add_argument(
        "--registry", type=Path, default=Path("configs/region_registry.csv")
    )
    parser.add_argument("--require-frozen", action="store_true")
    args = parser.parse_args()
    paths = sorted(args.target.rglob("*.json")) if args.target.is_dir() else [args.target]
    if not paths:
        raise SystemExit(f"no JSON files found at {args.target}")
    report = validate_paths(paths, args.schema, args.registry, args.require_frozen)
    failures = {path: errors for path, errors in report.items() if errors}
    if failures:
        for path, errors in failures.items():
            print(path)
            for error in errors:
                print(f"  - {error}")
        raise SystemExit(f"validation failed for {len(failures)}/{len(paths)} files")
    print(f"validated {len(paths)} Risk JSON files")


if __name__ == "__main__":
    main()
