from pathlib import Path

from scripts.refresh_portable_hash_locks import run


ROOT = Path(__file__).resolve().parents[1]


def test_repository_hash_locks_are_portable_and_current() -> None:
    """A clean checkout must not require any hash-lock repair."""

    assert run(ROOT) == []
