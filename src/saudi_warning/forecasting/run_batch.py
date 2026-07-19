"""Run the MAZU-like conversion for every GraphCast case in a CSV catalog."""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from saudi_warning.forecasting.graphcast_loader import (
    _cache_path,
    cache_file_is_valid,
    load_case_with_cache,
)
from saudi_warning.forecasting.indicator_converter import convert_window
from saudi_warning.forecasting.validation import (
    validate_mazu_like_file,
    validate_mazu_like_sequence,
)


LEADS = (24, 48, 72)
REQUIRED_STEPS = tuple(range(6, 73, 6))
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SUPPORTED_REPLAY_YEARS = {2018, 2020}


@dataclass(frozen=True)
class CaseRecord:
    """One forecast initialization selected for member A batch conversion."""

    case_id: str
    initial_time: str
    event_type: str = ""
    notes: str = ""


def load_catalog(path: Path) -> list[CaseRecord]:
    """Read and validate a unique case catalog without accessing remote data."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("case catalog is empty")
    required_columns = {"case_id", "initial_time"}
    if not rows[0].keys() >= required_columns:
        raise ValueError("catalog must contain case_id and initial_time columns")

    records: list[CaseRecord] = []
    seen_case_ids: set[str] = set()
    seen_initial_times: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        case_id = (row.get("case_id") or "").strip()
        initial_time = (row.get("initial_time") or "").strip()
        if not case_id or not initial_time:
            raise ValueError(f"row {row_number} needs case_id and initial_time")
        if case_id in seen_case_ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise ValueError(f"invalid case_id at row {row_number}: {case_id}")
        if not initial_time.endswith("Z"):
            raise ValueError(f"initial_time must be explicit UTC ending in Z at row {row_number}")
        try:
            initial = datetime.fromisoformat(initial_time.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"invalid initial_time at row {row_number}: {initial_time}") from error
        initial = initial.astimezone(timezone.utc)
        if initial.year not in SUPPORTED_REPLAY_YEARS:
            supported = ", ".join(str(year) for year in sorted(SUPPORTED_REPLAY_YEARS))
            raise ValueError(
                f"initial_time must use a supported GraphCast replay year "
                f"({supported}): {initial_time}"
            )
        clock = (initial.minute, initial.second, initial.microsecond)
        if initial.hour not in {0, 12} or any(clock):
            raise ValueError(f"initial_time must be a 00 or 12 UTC cycle: {initial_time}")
        normalized_initial = initial.isoformat().replace("+00:00", "Z")
        if normalized_initial in seen_initial_times:
            raise ValueError(
                f"duplicate initial_time would overwrite outputs: {normalized_initial}"
            )
        seen_case_ids.add(case_id)
        seen_initial_times.add(normalized_initial)
        records.append(
            CaseRecord(
                case_id=case_id,
                initial_time=normalized_initial,
                event_type=(row.get("event_type") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            )
        )
    return records


def output_paths(output_dir: Path, initial_time: str) -> dict[int, Path]:
    """Return the contract-compliant output names for all v1 lead windows."""
    stamp = datetime.fromisoformat(initial_time.replace("Z", "+00:00")).strftime("%Y%m%d_%H")
    return {lead: output_dir / f"mazu_like_{stamp}_lead{lead:03d}.nc" for lead in LEADS}


def cache_missing_steps(
    case: CaseRecord,
    cache_dir: Path,
    retries: int,
    timeout_seconds: int,
) -> None:
    """Use isolated child processes to cache only missing six-hour steps."""
    missing_steps = [
        step
        for step in REQUIRED_STEPS
        if not cache_file_is_valid(_cache_path(cache_dir, case.initial_time, step))
    ]
    if not missing_steps:
        return
    root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    source_root = str(root / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    command = [
        sys.executable,
        "-m",
        "saudi_warning.forecasting.cache_pending_steps",
        "--initial-time",
        case.initial_time,
        "--steps",
        *map(str, missing_steps),
        "--cache-dir",
        str(cache_dir),
        "--retries",
        str(retries),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    completed = subprocess.run(command, check=False, env=environment)
    if completed.returncode != 0:
        raise RuntimeError(f"cache worker exited with code {completed.returncode}")


def process_case(
    case: CaseRecord,
    cache_dir: Path,
    output_dir: Path,
    retries: int,
    timeout_seconds: int,
) -> tuple[str, dict[int, Path], str]:
    """Create all v1 outputs for one case and return status plus an optional error."""
    paths = output_paths(output_dir, case.initial_time)
    valid_leads = {
        lead
        for lead, path in paths.items()
        if path.exists()
        and validate_mazu_like_file(path, case.initial_time, lead).valid
    }
    if valid_leads == set(LEADS):
        sequence_errors = validate_mazu_like_sequence(list(paths.values()))
        if not sequence_errors:
            return "skipped", paths, "all lead outputs already exist and passed validation"
        valid_leads = set()

    cache_missing_steps(case, cache_dir, retries, timeout_seconds)
    full_case = load_case_with_cache(case.initial_time, REQUIRED_STEPS, cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for lead, path in paths.items():
        if lead in valid_leads:
            continue
        temporary = path.with_suffix(path.suffix + ".partial")
        convert_window(full_case, case.initial_time, lead).to_netcdf(temporary, engine="scipy")
        report = validate_mazu_like_file(
            temporary,
            expected_initial_time=case.initial_time,
            expected_lead=lead,
            check_filename=False,
        )
        if not report.valid:
            raise RuntimeError(
                f"generated lead{lead:03d} failed validation: {' | '.join(report.errors)}"
            )
        temporary.replace(path)
    sequence_errors = validate_mazu_like_sequence(list(paths.values()))
    if sequence_errors:
        raise RuntimeError(f"generated sequence failed validation: {' | '.join(sequence_errors)}")
    generated = ",".join(f"lead{lead:03d}" for lead in LEADS if lead not in valid_leads)
    return "completed", paths, f"generated and validated {generated}"


def write_manifest(path: Path, records: list[dict[str, str]]) -> None:
    """Atomically replace the local processing manifest after each case."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    fieldnames = [
        "case_id",
        "initial_time",
        "event_type",
        "status",
        "lead024_file",
        "lead048_file",
        "lead072_file",
        "message",
        "updated_at_utc",
    ]
    with temp_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    temp_path.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw/graphcast_2020"))
    parser.add_argument("--output-dir", type=Path, default=Path("handoff/mazu_like"))
    parser.add_argument("--manifest", type=Path, default=Path("manifests/processing_manifest.csv"))
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    manifest_rows: list[dict[str, str]] = []
    for case in load_catalog(args.catalog):
        paths = output_paths(args.output_dir, case.initial_time)
        try:
            status, paths, message = process_case(
                case, args.cache_dir, args.output_dir, args.retries, args.timeout_seconds
            )
        except Exception as error:  # Preserve other catalog cases after a single failure.
            status, message = "failed", f"{type(error).__name__}: {error}"
        manifest_rows.append(
            {
                "case_id": case.case_id,
                "initial_time": case.initial_time,
                "event_type": case.event_type,
                "status": status,
                "lead024_file": paths[24].as_posix(),
                "lead048_file": paths[48].as_posix(),
                "lead072_file": paths[72].as_posix(),
                "message": message,
                "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
        write_manifest(args.manifest, manifest_rows)
        print(f"case_id={case.case_id} status={status}", flush=True)


if __name__ == "__main__":
    main()
