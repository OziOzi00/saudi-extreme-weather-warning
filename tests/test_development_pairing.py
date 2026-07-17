import csv
from pathlib import Path

import pandas as pd

from saudi_warning.verification.build_development_pairs import development_cases
from saudi_warning.verification.metrics import validate_pairs


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "configs" / "case_catalog_candidates.csv"
PAIRS = ROOT / "handoff" / "weather_verification" / "development_pairs.csv"
COVERAGE = ROOT / "manifests" / "development_pairing_coverage.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_development_pairs_never_expose_independent_test() -> None:
    cases = development_cases(CATALOG)
    expected_case_ids = {row["case_id"] for row in cases}
    pairs = read_csv(PAIRS)
    audit = read_csv(COVERAGE)

    assert len(cases) == 11
    assert {row["case_id"] for row in pairs} == expected_case_ids
    assert {row["case_id"] for row in audit} == expected_case_ids
    assert {row["dataset_split"] for row in audit} == {"development"}
    assert not any("independent" in row["dataset_split"] for row in audit)


def test_pair_contract_and_qc_boundaries_are_explicit() -> None:
    frame = pd.read_csv(PAIRS)
    audit = read_csv(COVERAGE)

    assert validate_pairs(frame) == []
    assert len(frame) == 153
    assert len(audit) == 153
    assert (frame["observation_source"] == "IMERG").sum() == 45
    assert (frame["observation_source"] == "NOAA_SSOD_V2").sum() == 108
    assert set(frame.loc[frame["observation_source"] == "IMERG", "qc_status"]) == {
        "accepted"
    }
    assert set(
        frame.loc[frame["observation_source"] == "NOAA_SSOD_V2", "qc_status"]
    ) == {"accepted"}
    assert {row["pair_status"] for row in audit} == {"paired_accepted"}
    assert sum(row["pair_status"] == "missing" for row in audit) == 0
    assert frame.loc[frame["observation_source"] == "IMERG", "event_threshold"].isna().all()
    assert frame.loc[frame["observation_source"] == "NOAA_SSOD_V2", "event_threshold"].notna().all()


def test_every_development_rain_lead_has_all_three_imerg_aggregations() -> None:
    audit = read_csv(COVERAGE)
    rainfall = [row for row in audit if row["observation_source"] == "IMERG"]

    identities = {
        (row["case_id"], int(row["lead_time_hours"]), row["aggregation"])
        for row in rainfall
    }
    assert len(rainfall) == len(identities) == 5 * 3 * 3
    assert {row["pair_status"] for row in rainfall} == {"paired_accepted"}
    assert {float(row["coverage_fraction"]) for row in rainfall} == {1.0}
