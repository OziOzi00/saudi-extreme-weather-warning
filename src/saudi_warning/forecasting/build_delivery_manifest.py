"""Validate and hash all MAZU-like files expected by one case catalog."""

from __future__ import annotations

import argparse
from pathlib import Path

from saudi_warning.forecasting.delivery import build_delivery_rows, write_delivery_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, default=Path("handoff/mazu_like"))
    parser.add_argument(
        "--output", type=Path, default=Path("manifests/delivery_manifest.csv")
    )
    parser.add_argument("--validated-at", help="fixed UTC timestamp for reproducible runs")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    rows = build_delivery_rows(args.catalog, args.input_dir, root, args.validated_at)
    write_delivery_manifest(args.output, rows)
    failures = [row for row in rows if row["validation_status"] != "passed"]
    print(args.output)
    print(f"delivery_files={len(rows)} passed={len(rows) - len(failures)}")
    if failures:
        raise SystemExit(f"delivery validation failed for {len(failures)} files")


if __name__ == "__main__":
    main()
