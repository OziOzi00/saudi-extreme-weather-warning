"""Command-line runner for a single GraphCast-to-MAZU-like v1 case."""

from __future__ import annotations

import argparse
from pathlib import Path

from saudi_warning.forecasting.graphcast_loader import load_case_subset
from saudi_warning.forecasting.indicator_converter import convert_window, ensure_supported_lead


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-time", default="2020-08-20T00:00:00Z")
    parser.add_argument("--lead-hours", type=int, default=24)
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/mazu_like"))
    args = parser.parse_args()
    ensure_supported_lead(args.lead_hours)

    case = load_case_subset(args.initial_time, max_lead_hours=args.lead_hours)
    indicators = convert_window(case, args.initial_time, args.lead_hours)
    stamp = args.initial_time.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
    output_path = args.output_dir / f"mazu_like_{stamp}_lead{args.lead_hours:03d}.nc"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    indicators.to_netcdf(output_path, engine="scipy")
    print(output_path)
    print(indicators)


if __name__ == "__main__":
    main()
