"""Command-line runner for a single GraphCast-to-MAZU-like v1 case."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from saudi_warning.forecasting.graphcast_loader import load_case_with_cache
from saudi_warning.forecasting.indicator_converter import convert_window, ensure_supported_lead


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-time", default="2020-08-20T00:00:00Z")
    parser.add_argument("--lead-hours", type=int, default=24)
    parser.add_argument(
        "--all-leads",
        action="store_true",
        help="Create the v1 24, 48, and 72 hour windows from one cached case.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/mazu_like"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw/graphcast_2020"))
    args = parser.parse_args()
    ensure_supported_lead(args.lead_hours)

    output_leads = (24, 48, 72) if args.all_leads else (args.lead_hours,)
    lead_steps = list(range(6, max(output_leads) + 1, 6))
    case = load_case_with_cache(args.initial_time, lead_steps, cache_dir=args.cache_dir)
    stamp = datetime.fromisoformat(args.initial_time.replace("Z", "+00:00")).strftime("%Y%m%d_%H")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for lead_hours in output_leads:
        indicators = convert_window(case, args.initial_time, lead_hours)
        output_path = args.output_dir / f"mazu_like_{stamp}_lead{lead_hours:03d}.nc"
        indicators.to_netcdf(output_path, engine="scipy")
        print(output_path)
        print(indicators)


if __name__ == "__main__":
    main()
