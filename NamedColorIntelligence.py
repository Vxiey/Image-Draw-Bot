"""Named-colour parsing and diagnostics for Image Draw Bot.

This module deliberately sits *above* the rendering palette. Named colours are
accepted as user/UI input and used for human-readable diagnostics, but they are
never injected into the calibrated game palette or quantizer candidate set.

The runtime database is static so packaged Windows builds do not depend on
Matplotlib, Tcl/Tk's host colour database, or network access.
"""
from __future__ import annotations

from functools import lru_cache
import re
from typing import Sequence

from NamedColorData import CSS4_COLORS, X11_TK_COLORS
from ColorFidelity import delta_e_oklab, oklab_metrics, rgb_to_oklab


def normalize_color_name(name: str) -> str:
    """Normalize a human colour name without changing its semantic digits.

    ``DarkSlateBlue``, ``dark slate blue``, ``dark_slate_blue`` and
    ``dark-slate-blue`` therefore resolve through the same lookup key.
    """
    if not isinstance(name, str):
        raise TypeError("Colour name must be text.")
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def _prefer_alias(candidates: Sequence[str], fallback: str) -> str:
    """Choose a stable readable display spelling from equivalent aliases."""
    if not candidates:
        return fallback[:1].upper() + fallback[1:]
    # Prefer Tk's CamelCase spellings: ``DarkSlateBlue`` is compact and matches
    # the vocabulary users see in many Python/Tk colour references.
    camel = [n for n in candidates if " " not in n and any(c.isupper() for c in n[1:])]
    if camel:
        return min(camel, key=lambda n: (len(n), n.casefold(), n))
    spaced = [n for n in candidates if " " in n]
    if spaced:
        return min(spaced, key=lambda n: (len(n), n.casefold())).title()
    return min(candidates, key=lambda n: (len(n), n.casefold()))[:1].upper() + min(candidates, key=lambda n: (len(n), n.casefold()))[1:]


# Raw aliases first, preserving all known Tk/X11 spellings and CSS4 names.
_alias_rows: list[tuple[str, tuple[int, int, int], str]] = []
for _name, _rgb in X11_TK_COLORS:
    _alias_rows.append((_name, tuple(_rgb), "tk-x11"))
for _name, _rgb in CSS4_COLORS:
    _alias_rows.append((_name, tuple(_rgb), "css4"))

_aliases_by_key: dict[str, list[tuple[str, tuple[int, int, int], str]]] = {}
_aliases_by_rgb: dict[tuple[int, int, int], list[str]] = {}
for _name, _rgb, _source in _alias_rows:
    _key = normalize_color_name(_name)
    _aliases_by_key.setdefault(_key, []).append((_name, _rgb, _source))
    _aliases_by_rgb.setdefault(_rgb, []).append(_name)

# Prefer CSS4 when a normalized key exists in both vocabularies. This avoids
# platform-dependent resolution and gives common web/Python names precedence.
_NAME_TO_RGB: dict[str, tuple[int, int, int]] = {}
for _key, _rows in _aliases_by_key.items():
    _css = [r for r in _rows if r[2] == "css4"]
    _NAME_TO_RGB[_key] = (_css[0] if _css else _rows[0])[1]

# Friendly compatibility aliases found in published Tk colour lists. They are
# accepted but never become canonical display names.
_COMPAT_ALIASES = {
    "agua": "aqua",
    "crymson": "crimson",
}
for _bad, _good in _COMPAT_ALIASES.items():
    if _good in _NAME_TO_RGB:
        _NAME_TO_RGB[_bad] = _NAME_TO_RGB[_good]

# CSS4 is the compact canonical vocabulary used for *nearest* human names.
_css_rgb_to_names: dict[tuple[int, int, int], list[str]] = {}
for _name, _rgb in CSS4_COLORS:
    _css_rgb_to_names.setdefault(tuple(_rgb), []).append(_name)

_CSS_CANONICAL: dict[tuple[int, int, int], str] = {}
for _rgb, _css_names in _css_rgb_to_names.items():
    # Prefer American gray spellings for duplicate CSS aliases, otherwise the
    # first alphabetical name is deterministic (aqua over cyan, etc.).
    _ordered = sorted(_css_names, key=lambda n: ("grey" in n, n))
    _base = _ordered[0]
    _matching_aliases = [n for n in _aliases_by_rgb.get(_rgb, ()) if normalize_color_name(n) == normalize_color_name(_base)]
    _CSS_CANONICAL[_rgb] = _prefer_alias(_matching_aliases, _base)

# Extended exact-name vocabulary. CSS canonical names win duplicate RGBs;
# otherwise pick a readable X11/Tk spelling.
_EXTENDED_CANONICAL: dict[tuple[int, int, int], str] = dict(_CSS_CANONICAL)
for _rgb, _names in _aliases_by_rgb.items():
    if _rgb not in _EXTENDED_CANONICAL:
        _EXTENDED_CANONICAL[_rgb] = _prefer_alias(_names, _names[0])

# Deduplicated tuples make nearest-colour scans much smaller than the raw alias
# table. CSS4 contains 139 unique RGB values; the full Tk/X11 compatibility set
# remains available for exact parsing and optional extended nearest matching.
_CSS_NEAREST_ROWS = tuple(sorted(_CSS_CANONICAL.items(), key=lambda item: item[1].casefold()))
_EXTENDED_NEAREST_ROWS = tuple(sorted(_EXTENDED_CANONICAL.items(), key=lambda item: item[1].casefold()))


def vocabulary_stats() -> dict:
    """Return stable counts useful for diagnostics/tests/about screens."""
    return {
        "css4_aliases": len(CSS4_COLORS),
        "css4_unique_rgb": len(_CSS_CANONICAL),
        "tk_x11_aliases": len(X11_TK_COLORS),
        "all_lookup_keys": len(_NAME_TO_RGB),
        "extended_unique_rgb": len(_EXTENDED_CANONICAL),
        "compatibility_aliases": len(_COMPAT_ALIASES),
    }


def resolve_named_color(name: str) -> tuple[int, int, int]:
    """Resolve a CSS4/Tk/X11 name to canonical sRGB."""
    key = normalize_color_name(name)
    if not key or key not in _NAME_TO_RGB:
        raise ValueError(f"Unknown named color: {name!r}.")
    return _NAME_TO_RGB[key]


def aliases_for_rgb(rgb: Sequence[int]) -> tuple[str, ...]:
    key = _rgb3(rgb)
    aliases = _aliases_by_rgb.get(key, ())
    # Normalized-key dedup while preserving the most readable first spelling.
    found: dict[str, str] = {}
    for name in aliases:
        nk = normalize_color_name(name)
        current = found.get(nk)
        if current is None or _prefer_alias((name,), name) == name:
            found[nk] = name
    return tuple(sorted(found.values(), key=lambda n: n.casefold()))


def _rgb3(value: Sequence[int]) -> tuple[int, int, int]:
    try:
        values = tuple(value)
    except TypeError:
        raise ValueError("RGB must contain three channels.") from None
    if len(values) < 3:
        raise ValueError("RGB must contain three channels.")
    out = []
    for channel in values[:3]:
        if isinstance(channel, bool):
            raise ValueError("RGB channels must be integers from 0 to 255.")
        try:
            number = int(channel)
        except (TypeError, ValueError):
            raise ValueError("RGB channels must be integers from 0 to 255.") from None
        if number != channel or not 0 <= number <= 255:
            raise ValueError("RGB channels must be integers from 0 to 255.")
        out.append(number)
    return tuple(out)


def color_family(rgb: Sequence[int]) -> str:
    """Classify colour family from OKLab hue/chroma, never from its name."""
    rgb3 = _rgb3(rgb)
    lightness, chroma, hue = oklab_metrics(rgb3)
    if chroma < 3.0:
        if lightness < 18.0:
            return "black"
        if lightness > 92.0:
            return "white"
        return "gray"
    # Circular hue sectors tuned for broad, user-facing labels rather than
    # quantization. Rendering continues to use numeric OKLab directly.
    if hue < 35.0 or hue >= 355.0:
        return "red"
    if hue < 70.0:
        return "orange"
    if hue < 115.0:
        return "yellow"
    if hue < 175.0:
        return "green"
    if hue < 225.0:
        return "cyan"
    if hue < 285.0:
        return "blue"
    if hue < 325.0:
        return "purple"
    return "pink"


@lru_cache(maxsize=65536)
def _nearest_cached(rgb: tuple[int, int, int], extended: bool) -> tuple[str, tuple[int, int, int], float]:
    # Exact extended aliases should retain their exact human name even when the
    # default nearest scan otherwise uses only the compact CSS4 vocabulary.
    if rgb in _EXTENDED_CANONICAL:
        return _EXTENDED_CANONICAL[rgb], rgb, 0.0
    import numpy as np
    from math import sqrt
    rows,labs=_nearest_reference(extended)
    delta=labs-np.asarray(rgb_to_oklab(rgb),dtype=np.float64)
    squared=np.sum(delta*delta,axis=1)
    index=int(np.argmin(squared))
    best_rgb,best_name=rows[index]
    return best_name,best_rgb,sqrt(float(squared[index]))*100.0


@lru_cache(maxsize=2)
def _nearest_reference(extended):
    """Immutable numeric vocabulary shared by every previously unseen color."""
    import numpy as np
    rows=_EXTENDED_NEAREST_ROWS if extended else _CSS_NEAREST_ROWS
    labs=np.asarray([rgb_to_oklab(rgb) for rgb,_name in rows],dtype=np.float64)
    labs.setflags(write=False)
    return rows,labs


def nearest_named_color(rgb: Sequence[int], *, extended: bool = False) -> dict:
    """Return nearest readable named colour using Image Draw Bot's OKLab metric."""
    rgb3 = _rgb3(rgb)
    name, named_rgb, delta = _nearest_cached(rgb3, bool(extended))
    return {
        "name": name,
        "rgb": named_rgb,
        "delta_e_oklab": round(delta, 4),
        "family": color_family(rgb3),
        "exact": delta <= 1e-12,
        "aliases": aliases_for_rgb(named_rgb) if delta <= 1e-12 else (),
        "vocabulary": "extended-tk-x11" if extended else "css4",
    }


def canonical_color_name(rgb: Sequence[int], *, extended: bool = False) -> str:
    return str(nearest_named_color(rgb, extended=extended)["name"])


def _alpha255(value) -> int:
    if isinstance(value, str):
        value = value.strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("Alpha must be 0..1 or 0..255.") from None
    if 0.0 <= number <= 1.0:
        number *= 255.0
    if not 0.0 <= number <= 255.0:
        raise ValueError("Alpha must be 0..1 or 0..255.")
    return int(round(number))


def composite_rgba(r: int, g: int, b: int, a, background=(255, 255, 255)) -> tuple[int, int, int]:
    rgb = _rgb3((int(r), int(g), int(b)))
    bg = _rgb3(background)
    alpha = _alpha255(a)
    if alpha == 255:
        return rgb
    if alpha == 0:
        return bg
    return tuple(round((channel * alpha + base * (255 - alpha)) / 255) for channel, base in zip(rgb, bg))


def parse_named_color_text(text: str, *, background=(255, 255, 255)) -> tuple[int, int, int]:
    """Parse named/CSS-like text not covered by Image Draw Bot's legacy hex path.

    Supported forms: named colours, ``#RGB``, ``#RGBA``, ``rgb(r,g,b)``,
    ``rgba(r,g,b,a)`` and ``argb(a,r,g,b)``. Eight-digit legacy Image Draw Bot hex
    remains ``AARRGGBB`` and is intentionally handled by ``Colors.normalize_rgb``.
    """
    if not isinstance(text, str):
        raise ValueError("Color input must be text.")
    raw = text.strip()
    if not raw:
        raise ValueError("Color input is empty.")

    m = re.fullmatch(r"(?i)(rgb|rgba|argb)\s*\((.*?)\)\s*", raw)
    if m:
        mode = m.group(1).lower()
        parts = [p.strip() for p in m.group(2).split(",")]
        if mode == "rgb" and len(parts) == 3:
            try:
                return _rgb3(tuple(int(p) for p in parts))
            except ValueError:
                raise ValueError("rgb() requires integer channels from 0 to 255.") from None
        if mode == "rgba" and len(parts) == 4:
            try:
                r, g, b = (int(p) for p in parts[:3])
                return composite_rgba(r, g, b, parts[3], background)
            except ValueError:
                raise ValueError("rgba() requires RGB 0..255 and alpha 0..1 or 0..255.") from None
        if mode == "argb" and len(parts) == 4:
            try:
                a = parts[0]
                r, g, b = (int(p) for p in parts[1:])
                return composite_rgba(r, g, b, a, background)
            except ValueError:
                raise ValueError("argb() requires alpha 0..1 or 0..255 and RGB 0..255.") from None
        raise ValueError(f"Invalid {mode}() color.")

    if raw.startswith("#"):
        body = raw[1:]
        if len(body) in (3, 4) and all(ch in "0123456789abcdefABCDEF" for ch in body):
            channels = [int(ch * 2, 16) for ch in body]
            if len(channels) == 3:
                return tuple(channels)
            return composite_rgba(channels[0], channels[1], channels[2], channels[3], background)
        raise ValueError('Short hex colors must use #RGB or #RGBA hexadecimal digits.')

    return resolve_named_color(raw)


def describe_color_mapping(source: Sequence[int], mapped: Sequence[int]) -> dict:
    """Human-readable mapping diagnostics for preview/debug metadata."""
    src = _rgb3(source)
    dst = _rgb3(mapped)
    src_named = nearest_named_color(src)
    dst_named = nearest_named_color(dst)
    _sL, sC, sH = oklab_metrics(src)
    _dL, dC, dH = oklab_metrics(dst)
    if min(sC, dC) < 2.5:
        hue_drift = 0.0
    else:
        hue_drift = abs(sH - dH) % 360.0
        hue_drift = min(hue_drift, 360.0 - hue_drift)
    delta = float(delta_e_oklab(src, dst))
    if delta <= 1.0:
        note = f"{src_named['name']}-like color preserved"
    elif src_named["family"] != dst_named["family"]:
        note = f"{src_named['name']}-like region mapped toward {dst_named['name']}"
    else:
        note = f"{src_named['name']}-like region mapped within {dst_named['family']} family"
    return {
        "source_rgb": src,
        "source_name": src_named["name"],
        "source_family": src_named["family"],
        "mapped_rgb": dst,
        "mapped_name": dst_named["name"],
        "mapped_family": dst_named["family"],
        "delta_e_oklab": round(delta, 4),
        "hue_drift_degrees": round(hue_drift, 2),
        "note": note,
    }
