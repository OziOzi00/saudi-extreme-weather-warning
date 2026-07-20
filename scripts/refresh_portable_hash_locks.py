"""Refresh repository hash locks against the bytes committed by Git.

The repository enforces LF for text artifacts through ``.gitattributes``.  This
utility repairs manifests that were previously produced from CRLF working-tree
bytes on Windows.  It only changes hashes (and recorded byte sizes) that have an
explicit path relationship; scientific values and prediction decisions are not
recomputed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml


DOCUMENT_SUFFIXES = {".json", ".yaml", ".yml"}
SELECTION_LOCK = Path("manifests/joint_pipeline_selection_lock_v2.json")
ADVISORY_LOCK = Path(
    "handoff/reports/dual_prediction_batch_v1/llm_advisory_prediction_lock.csv"
)
INTENTIONALLY_STALE_LOCKS = {
    Path("configs/heatwave_bias_correction_cv_v1.yaml"),
    Path("configs/heatwave_bias_correction_cv_v2.yaml"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_documents(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths = result.stdout.decode("utf-8").split("\0")
    return sorted(
        root / path
        for path in paths
        if path
        and Path(path).suffix.lower() in DOCUMENT_SUFFIXES
        and Path(path) not in INTENTIONALLY_STALE_LOCKS
    )


def load_document(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def write_lf(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def path_for_key(record: dict[str, Any], key: str) -> str | None:
    if key == "sha256":
        value = record.get("path")
        return value if isinstance(value, str) else None
    if not key.endswith("_sha256"):
        return None
    stem = key[: -len("_sha256")]
    for candidate in (f"{stem}_path", stem):
        value = record.get(candidate)
        if isinstance(value, str):
            return value
    return None


def repository_file(root: Path, value: str) -> Path | None:
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
    else:
        candidate = root / candidate
    return candidate if candidate.is_file() else None


def collect_replacements(
    root: Path,
    document_path: Path,
    value: Any,
    replacements: dict[str, str],
) -> None:
    if isinstance(value, list):
        for item in value:
            collect_replacements(root, document_path, item, replacements)
        return
    if not isinstance(value, dict):
        return

    for key, current in value.items():
        if isinstance(current, str) and len(current) == 64:
            relative = path_for_key(value, key)
            target = repository_file(root, relative) if relative else None
            if target is not None:
                replacements[current] = sha256(target)

        if key == "input_sha256" and isinstance(current, dict):
            for relative, old_hash in current.items():
                if not isinstance(relative, str) or not isinstance(old_hash, str):
                    continue
                target = repository_file(root, relative)
                if target is not None:
                    replacements[old_hash] = sha256(target)

    relative_document = document_path.relative_to(root).as_posix()
    selection_hash = value.get("selection_lock_sha256")
    selection_path = root / SELECTION_LOCK
    if isinstance(selection_hash, str) and selection_path.is_file():
        replacements[selection_hash] = sha256(selection_path)

    prediction_hash = value.get("prediction_lock_sha256")
    if (
        isinstance(prediction_hash, str)
        and relative_document.startswith("handoff/reports/dual_prediction_batch_v1/")
    ):
        replacements[prediction_hash] = sha256(root / ADVISORY_LOCK)

    for item in value.values():
        collect_replacements(root, document_path, item, replacements)


def refresh_recorded_sizes(root: Path, value: Any) -> bool:
    changed = False
    if isinstance(value, list):
        for item in value:
            changed = refresh_recorded_sizes(root, item) or changed
        return changed
    if not isinstance(value, dict):
        return False
    relative = value.get("path")
    recorded = value.get("size_bytes")
    if isinstance(relative, str) and isinstance(recorded, int):
        target = repository_file(root, relative)
        if target is not None and target.stat().st_size != recorded:
            value["size_bytes"] = target.stat().st_size
            changed = True
    for item in value.values():
        changed = refresh_recorded_sizes(root, item) or changed
    return changed


def refresh_document(root: Path, path: Path) -> bool:
    try:
        document = load_document(path)
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError):
        return False
    replacements: dict[str, str] = {}
    collect_replacements(root, path, document, replacements)
    text = path.read_text(encoding="utf-8-sig")
    updated = text
    for old_hash, new_hash in replacements.items():
        if old_hash != new_hash:
            updated = updated.replace(old_hash, new_hash)

    size_changed = refresh_recorded_sizes(root, document)
    if updated == text and not size_changed:
        return False
    if size_changed and path.suffix.lower() == ".json":
        # Repository JSON artifacts consistently use two-space indentation.
        updated = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        for old_hash, new_hash in replacements.items():
            if old_hash != new_hash:
                updated = updated.replace(old_hash, new_hash)
    write_lf(path, updated)
    return True


def run(root: Path, max_passes: int = 8) -> list[str]:
    changed: set[str] = set()
    documents = tracked_documents(root)
    for _ in range(max_passes):
        pass_changed = False
        for path in documents:
            if refresh_document(root, path):
                changed.add(path.relative_to(root).as_posix())
                pass_changed = True
        if not pass_changed:
            break
    else:
        raise RuntimeError("hash-lock refresh did not converge")
    return sorted(changed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    changed = run(args.root.resolve())
    print(f"refreshed {len(changed)} hash-lock documents")
    for path in changed:
        print(path)


if __name__ == "__main__":
    main()
