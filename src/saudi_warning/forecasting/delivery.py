"""Build a traceable manifest for validated MAZU-like delivery files."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from saudi_warning.forecasting.run_batch import load_catalog, output_paths
from saudi_warning.forecasting.validation import validate_mazu_like_file


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def implementation_sha256(root: Path) -> str:
    """Fingerprint the actual A-side source/config bytes, including uncommitted changes."""
    paths = sorted((root / "src" / "saudi_warning" / "forecasting").glob("*.py"))
    paths.extend(
        [
            root / "scripts" / "summarize_mazu_like_adm1.py",
            root / "configs" / "indicator_mapping.yaml",
            root / "pyproject.toml",
        ]
    )
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def repository_revision(root: Path) -> str:
    """Read the current Git revision without invoking Git or changing global config."""
    git_dir = root / ".git"
    head_path = git_dir / "HEAD"
    if not head_path.exists():
        return "unknown"
    head = head_path.read_text(encoding="ascii").strip()
    if not head.startswith("ref: "):
        return head
    reference = head.removeprefix("ref: ")
    loose_ref = git_dir / reference
    if loose_ref.exists():
        return loose_ref.read_text(encoding="ascii").strip()
    packed_refs = git_dir / "packed-refs"
    if packed_refs.exists():
        for line in packed_refs.read_text(encoding="ascii").splitlines():
            if line and not line.startswith(("#", "^")):
                revision, name = line.split(" ", maxsplit=1)
                if name == reference:
                    return revision
    return "unknown"


def build_delivery_rows(
    catalog_path: Path,
    input_dir: Path,
    repository_root: Path,
    validated_at_utc: str | None = None,
) -> list[dict[str, str]]:
    """Hash and validate every expected catalog output."""
    validated_at = validated_at_utc or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    cases = load_catalog(catalog_path)
    mapping_path = repository_root / "configs" / "indicator_mapping.yaml"
    mapping_hash = sha256_file(mapping_path)
    revision = repository_revision(repository_root)
    implementation_hash = implementation_sha256(repository_root)
    rows: list[dict[str, str]] = []
    for case in cases:
        for lead, path in output_paths(input_dir, case.initial_time).items():
            report = validate_mazu_like_file(path, case.initial_time, lead)
            relative_path = path.resolve().relative_to(repository_root.resolve()).as_posix()
            modified_at = (
                datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                if path.exists()
                else ""
            )
            rows.append(
                {
                    "case_id": case.case_id,
                    "source_file": relative_path,
                    "file_size_bytes": str(path.stat().st_size) if path.exists() else "0",
                    "sha256": sha256_file(path) if path.exists() else "",
                    "file_modified_at_utc": modified_at,
                    "validated_at_utc": validated_at,
                    "validation_status": "passed" if report.valid else "failed",
                    "validation_errors": " | ".join(report.errors),
                    "validation_warnings": " | ".join(report.warnings),
                    "initial_time": str(
                        report.metadata.get("initial_time") or case.initial_time
                    ),
                    "lead_time_hours": str(report.metadata.get("lead_time_hours") or lead),
                    "valid_start_time": str(report.metadata.get("valid_start_time") or ""),
                    "valid_end_time": str(report.metadata.get("valid_end_time") or ""),
                    "forecast_model": str(report.metadata.get("forecast_model") or ""),
                    "source_resolution": str(
                        report.metadata.get("source_resolution") or ""
                    ),
                    "indicator_version": str(
                        report.metadata.get("indicator_version") or ""
                    ),
                    "indicator_mapping_sha256": mapping_hash,
                    "implementation_sha256": implementation_hash,
                    "repository_revision": revision,
                }
            )
    return rows


def write_delivery_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("delivery manifest cannot be empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)
