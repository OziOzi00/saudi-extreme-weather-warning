"""Run the MAZU-like conversion for every GraphCast case in a CSV catalog."""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from saudi_warning.forecasting.graphcast_loader import _cache_path, load_case_with_cache
from saudi_warning.forecasting.indicator_converter import convert_window


LEADS = (24, 48, 72)
REQUIRED_STEPS = tuple(range(6, 73, 6))


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
    for row_number, row in enumerate(rows, start=2):
        case_id = (row.get("case_id") or "").strip()
        initial_time = (row.get("initial_time") or "").strip()
        if not case_id or not initial_time:
            raise ValueError(f"row {row_number} needs case_id and initial_time")
        if case_id in seen_case_ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        try:
            datetime.fromisoformat(initial_time.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"invalid initial_time at row {row_number}: {initial_time}") from error
        seen_case_ids.add(case_id)
        records.append(
            CaseRecord(
                case_id=case_id,
                initial_time=initial_time,
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
        if not _cache_path(cache_dir, case.initial_time, step).exists()
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
    if all(path.exists() and path.stat().st_size > 0 for path in paths.values()):
        return "skipped", paths, "all lead outputs already exist"

    cache_missing_steps(case, cache_dir, retries, timeout_seconds)
    full_case = load_case_with_cache(case.initial_time, REQUIRED_STEPS, cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for lead, path in paths.items():
        convert_window(full_case, case.initial_time, lead).to_netcdf(path, engine="scipy")
    return "completed", paths, ""


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
                "lead024_file": str(paths[24]),
                "lead048_file": str(paths[48]),
                "lead072_file": str(paths[72]),
                "message": message,
                "updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
        write_manifest(args.manifest, manifest_rows)
        print(f"case_id={case.case_id} status={status}", flush=True)


if __name__ == "__main__":
    main()
