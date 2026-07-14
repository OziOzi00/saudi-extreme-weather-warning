"""Cache GraphCast steps with one-process-per-step timeout and retry control."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from saudi_warning.forecasting.graphcast_loader import _cache_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-time", default="2020-08-20T00:00:00Z")
    parser.add_argument("--steps", nargs="+", type=int, default=[54, 60, 66, 72])
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw/graphcast_2020"))
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    for step in args.steps:
        cache_file = _cache_path(args.cache_dir, args.initial_time, step)
        if cache_file.exists() and cache_file.stat().st_size > 0:
            print(f"skip cached step={step:03d}h path={cache_file}", flush=True)
            continue
        command = [
            sys.executable,
            "-m",
            "saudi_warning.forecasting.cache_step",
            "--initial-time",
            args.initial_time,
            "--step-hours",
            str(step),
            "--cache-dir",
            str(args.cache_dir),
        ]
        for attempt in range(1, args.retries + 1):
            print(f"start step={step:03d}h attempt={attempt}/{args.retries}", flush=True)
            try:
                completed = subprocess.run(command, check=False, timeout=args.timeout_seconds)
            except subprocess.TimeoutExpired:
                print(f"timeout step={step:03d}h attempt={attempt}", flush=True)
                continue
            if completed.returncode == 0 and cache_file.exists() and cache_file.stat().st_size > 0:
                print(f"complete step={step:03d}h path={cache_file}", flush=True)
                break
            print(f"retry step={step:03d}h exit_code={completed.returncode}", flush=True)
        else:
            raise RuntimeError(f"failed to cache step {step:03d}h after {args.retries} attempts")


if __name__ == "__main__":
    main()
