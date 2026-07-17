"""CLI for missed positive-impact attribution."""

from pathlib import Path

from .impact_attribution import run


def main() -> None:
    run(
        Path("handoff/impact_verification/positive_impact_units.csv"),
        Path("handoff/weather_verification/development_pairs.csv"),
        Path("handoff/risk_dry_runs/development_v2_rule_review.csv"),
        Path("handoff/impact_verification/missed_impact_attribution.csv"),
        Path("manifests/impact_miss_attribution.json"),
    )
    print("handoff/impact_verification/missed_impact_attribution.csv")
    print("manifests/impact_miss_attribution.json")


if __name__ == "__main__":
    main()
