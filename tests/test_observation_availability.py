import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_observation_source_manifest_is_well_formed() -> None:
    rows = read_csv(ROOT / "manifests" / "observation_source_availability.csv")
    assert len(rows) == 4
    assert all(None not in row for row in rows)
    ghcn = next(row for row in rows if row["observation_id"] == "GHCN_DAILY_2020")
    assert ghcn["access_status"] == "downloaded_local_not_versioned"
    assert len(ghcn["sha256"]) == 64
    imerg = next(row for row in rows if row["observation_id"] == "IMERG_FINAL_V07B_2020")
    assert imerg["access_status"] == "downloaded_local_not_versioned"
    assert imerg["version"] == "V07B"
    imerg_files = read_csv(ROOT / "manifests" / "imerg_v07b_daily_files.csv")
    assert len(imerg_files) == 32
    assert all(len(row["sha256"]) == 64 for row in imerg_files)
    ssod = next(row for row in rows if row["observation_id"] == "SSOD_V2_SAUDI_2020")
    assert ssod["access_status"] == "downloaded_local_not_versioned"
    assert len(ssod["sha256"]) == 64
    ssod_files = read_csv(ROOT / "manifests" / "ssod_v2_saudi_2020_files.csv")
    assert len(ssod_files) == 31
    assert all(len(row["sha256"]) == 64 for row in ssod_files)


def test_late_july_heat_is_present_in_downloaded_ghcn_screening() -> None:
    rows = read_csv(ROOT / "manifests" / "ghcn_2020_candidate_coverage.csv")
    heat = {
        row["region_id"]: row
        for row in rows
        if row["case_id"] == "20200729_00" and row["hazard"] == "heatwave"
    }
    assert float(heat["SA-08"]["tmax_max"]) == 50.0
    assert float(heat["SA-04"]["tmax_max"]) == 50.6
    assert int(heat["SA-08"]["tmax_stations"]) >= 1
    assert int(heat["SA-04"]["tmax_stations"]) >= 1
