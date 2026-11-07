"""Step 28 target capability registry.

This module is deliberately data-only. It classifies built-in targets without
containing coordinates, input authorization, palette pixels or native handles.
Those remain owned by the existing calibration/safety layers.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class TargetCapability:
    key: str
    name: str
    kind: str                 # desktop-app, browser-game, browser-app, generic
    setup_mode: str           # paint-auto, browser-auto, manual
    palette_mode: str         # verified-auto, manual
    timed: bool
    layout_fingerprint: bool
    timing_cache: bool
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


_TARGETS = {
    "microsoft-paint": TargetCapability(
        "microsoft-paint", "Microsoft Paint", "desktop-app", "paint-auto",
        "verified-auto", False, True, True,
        "Paint uses the dedicated visual detector and strict safety chain."),
    "generic": TargetCapability(
        "generic", "Other drawing app", "generic", "manual", "manual", False,
        True, True, "Generic fallback with explicit manual calibration."),
    "gartic-phone": TargetCapability(
        "gartic-phone", "Gartic Phone", "browser-game", "browser-auto",
        "verified-auto", True, True, True,
        "Verified browser auto-setup is available."),
    "skribbl": TargetCapability(
        "skribbl", "Skribbl.io", "browser-game", "browser-auto",
        "verified-auto", True, True, True,
        "Verified browser auto-setup is available."),
    "skribbl-fast": TargetCapability(
        "skribbl-fast", "Skribbl.io Fast", "browser-game", "browser-auto",
        "verified-auto", True, True, True,
        "Fast Skribbl renderer with the same isolated calibration namespace."),
    "sketchheads": TargetCapability(
        "sketchheads", "SketchHeads", "browser-game", "browser-auto",
        "verified-auto", True, True, True,
        "Verified browser canvas/palette detector is available."),
    "sketchful": TargetCapability(
        "sketchful", "Sketchful.io", "browser-game", "browser-auto",
        "verified-auto", True, True, True,
        "Verified browser setup is available."),
    "drawize": TargetCapability(
        "drawize", "Drawize", "browser-game", "manual", "manual", True,
        True, True,
        "Dedicated profile, but palette/layout auto-detection remains disabled until verified."),
    "gartic-io": TargetCapability(
        "gartic-io", "Gartic.io", "browser-game", "manual", "manual", True,
        True, True,
        "Dedicated profile with manual palette/canvas calibration until a detector is verified."),
    "kleki": TargetCapability(
        "kleki", "Kleki", "browser-app", "manual", "manual", False,
        True, True,
        "Browser painting app; use explicit canvas/tool/color calibration."),
    "magma": TargetCapability(
        "magma", "Magma", "browser-app", "manual", "manual", False,
        True, True,
        "Collaborative browser painting app; use explicit per-profile calibration."),
}

_ALL = tuple(_TARGETS.values())
_BUILTIN_KEYS = frozenset(_TARGETS)
_AUTO_BROWSER_KEYS = frozenset(k for k, v in _TARGETS.items() if v.setup_mode == 'browser-auto')
_MANUAL_BROWSER_KEYS = frozenset(k for k, v in _TARGETS.items() if v.kind.startswith('browser-') and v.setup_mode == 'manual')
_BROWSER_KEYS = frozenset(k for k, v in _TARGETS.items() if v.kind.startswith('browser-'))


def capability_for_key(profile_key: str) -> TargetCapability:
    key = str(profile_key or "").strip().lower()
    known = _TARGETS.get(key)
    if known is not None:
        return known
    return TargetCapability(
        key or "custom", "Custom target", "generic", "manual", "manual", False,
        True, True, "Custom profile with explicit calibration.")


def all_capabilities() -> tuple[TargetCapability, ...]:
    return _ALL


def builtin_profile_keys() -> frozenset[str]:
    return _BUILTIN_KEYS


def auto_browser_profile_keys() -> frozenset[str]:
    return _AUTO_BROWSER_KEYS


def manual_browser_profile_keys() -> frozenset[str]:
    return _MANUAL_BROWSER_KEYS


def browser_profile_keys() -> frozenset[str]:
    return _BROWSER_KEYS


def is_browser_target(profile_key: str) -> bool:
    return capability_for_key(profile_key).kind.startswith("browser-")


def supports_one_click_setup(profile_key: str) -> bool:
    return capability_for_key(profile_key).setup_mode in {"paint-auto", "browser-auto"}


def requires_manual_setup(profile_key: str) -> bool:
    return capability_for_key(profile_key).setup_mode == "manual"
