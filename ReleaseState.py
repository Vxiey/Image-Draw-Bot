"""Small release/first-run state helpers for Image Draw Bot.

This file intentionally stores only local UX state. It does not contain analytics,
tracking identifiers, source image information, or telemetry.
"""
from __future__ import annotations

import json
from pathlib import Path

from RuntimePaths import atomic_write_text, data_dir, read_json
from Version import APP_VERSION, BUILD_CHANNEL

STATE_FILE = data_dir() / "release-state.json"


def load_state() -> dict:
    state = {
        "welcome_seen": False,
        "last_seen_version": "",
    }
    try:
        raw = read_json(STATE_FILE, max_bytes=16384)
        if isinstance(raw, dict):
            if type(raw.get("welcome_seen")) is bool:
                state["welcome_seen"] = raw["welcome_seen"]
            if isinstance(raw.get("last_seen_version"), str):
                state["last_seen_version"] = raw["last_seen_version"][:80]
    except (OSError, ValueError, TypeError):
        pass
    return state


def should_show_welcome() -> bool:
    return not bool(load_state().get("welcome_seen"))


def mark_welcome_seen() -> None:
    atomic_write_text(
        STATE_FILE,
        json.dumps({"welcome_seen": True, "last_seen_version": APP_VERSION}, indent=2),
    )


def release_label() -> str:
    return f"Image Draw Bot {APP_VERSION}"


def build_channel_label() -> str:
    return BUILD_CHANNEL.capitalize()
