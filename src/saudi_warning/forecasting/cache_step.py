"""Fetch and persist one cropped GraphCast forecast step.

Run this module as a separate process so a stalled remote request can be
terminated safely by the batch controller without corrupting completed caches.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from saudi_warning.forecasting.graphcast_loader import load_case_with_cache


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-time", required=True)
    parser.add_argument("--step-hours", type=int, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw/graphcast_2020"))
    args = parser.parse_args()
    if args.step_hours < 6 or args.step_hours > 240 or args.step_hours % 6:
        raise ValueError("step-hours must be a positive six-hour GraphCast lead")

    load_case_with_cache(args.initial_time, [args.step_hours], cache_dir=args.cache_dir)
    print(f"cached step={args.step_hours:03d}h")


if __name__ == "__main__":
    main()
