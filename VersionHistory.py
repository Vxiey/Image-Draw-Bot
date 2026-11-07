"""Local version-history helpers for Image Draw Bot.

The functions are deterministic and local-only. They read bundled markdown files
from the source tree or a PyInstaller onedir bundle; they never use the network.
"""
from __future__ import annotations

from pathlib import Path
import sys

from Version import APP_VERSION


CANDIDATE_FILES = ("VERSION-HISTORY.md", "docs/VERSION-HISTORY.md")


def candidate_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parent)
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root)
        if key not in seen:
            unique.append(root)
            seen.add(key)
    return tuple(unique)


def _history_files():
    for root in candidate_roots():
        for rel in CANDIDATE_FILES:
            path = root / rel
            try:
                if path.is_file():
                    yield path
            except OSError:
                continue


def find_version_history_file() -> Path | None:
    return next(_history_files(), None)


def read_version_history(max_chars: int = 70000) -> str:
    if type(max_chars) is not int or not 1 <= max_chars <= 1_000_000:
        raise ValueError('Version history limit must be an integer from 1 to 1,000,000 characters.')
    last_error = None
    for path in _history_files():
        try:
            with path.open('r', encoding='utf-8', errors='replace') as stream:
                text = stream.read(max_chars + 1)
        except OSError as error:
            last_error = error
            continue
        if len(text) > max_chars:
            return text[:max_chars].strip() + "\n\n[Version history truncated in the viewer.]"
        return text.strip() + "\n"
    if last_error is not None:
        return f"Image Draw Bot {APP_VERSION}\n\nCould not read version history: {last_error}"
    return f"Image Draw Bot {APP_VERSION}\n\nVersion history file was not found in this build."


def has_version_history() -> bool:
    return find_version_history_file() is not None
