"""Compute weather-layer metrics from standardized forecast-observation pairs."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from saudi_warning.verification.metrics import compute_heatwave_sequences, compute_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairs", type=Path)
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=Path("outputs/weather_verification/weather_metrics.csv"),
    )
    parser.add_argument(
        "--heatwave-output",
        type=Path,
        default=Path("outputs/weather_verification/heatwave_sequences.csv"),
    )
    parser.add_argument("--minimum-heatwave-duration", type=int, default=2)
    args = parser.parse_args()
    pairs = pd.read_csv(args.pairs)
    metrics = compute_metrics(pairs)
    heatwave = compute_heatwave_sequences(pairs, args.minimum_heatwave_duration)
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.heatwave_output.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.metrics_output, index=False)
    heatwave.to_csv(args.heatwave_output, index=False)
    print(args.metrics_output)
    print(args.heatwave_output)


if __name__ == "__main__":
    main()
