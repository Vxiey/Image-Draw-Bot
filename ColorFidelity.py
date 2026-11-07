"""sRGB-aware palette fidelity helpers for Image Draw Bot.

v1.0.120 keeps palette mapping deterministic while preventing a common game-
palette failure mode: several mathematically-close swatches can all be darker
and less saturated than the source, making the simulated preview look gloomy.
The scorer therefore combines a base colour distance with explicit lightness,
saturation and hue preservation. Exact mode disables those extra preferences.
"""
from __future__ import annotations

import colorsys
from functools import lru_cache
from math import atan2, degrees, sqrt, exp, sin, cos, radians, pi
from typing import Sequence

COLOR_FIDELITY_MODES = ("Fast", "Balanced", "Faithful", "Exact")


def validate_color_fidelity(mode: str) -> str:
    if mode not in COLOR_FIDELITY_MODES:
        raise ValueError("Color fidelity must be Fast, Balanced, Faithful or Exact.")
    return mode


def _clamp8(v) -> int:
    return max(0, min(255, int(round(float(v)))))


def _linear_channel(v: int) -> float:
    c = _clamp8(v) / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


@lru_cache(maxsize=131072)
def rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """Convert display sRGB to CIE Lab (D65)."""
    r, g, b = (_linear_channel(v) for v in rgb)
    # sRGB D65 -> XYZ
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    # D65 reference white
    x /= 0.95047
    y /= 1.00000
    z /= 1.08883

    def f(t: float) -> float:
        d = 6.0 / 29.0
        return t ** (1.0 / 3.0) if t > d ** 3 else t / (3.0 * d * d) + 4.0 / 29.0

    fx, fy, fz = f(x), f(y), f(z)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


@lru_cache(maxsize=131072)
def rgb_to_oklab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """Convert display sRGB to OKLab.

    The returned components follow Björn Ottosson's OKLab definition: L is
    roughly 0..1 and a/b are opponent chroma axes.  This is the canonical
    perceptual space for Image Draw Bot palette matching from Step 2 onward.
    """
    r, g, b = (_linear_channel(v) for v in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    ss = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b

    # Python's ** (1/3) becomes complex for a negative value.  The matrices
    # can produce tiny negatives near gamut edges, so use a signed cube root.
    def cbrt(v: float) -> float:
        return -((-v) ** (1.0 / 3.0)) if v < 0.0 else v ** (1.0 / 3.0)

    ll, mm, s3 = cbrt(l), cbrt(m), cbrt(ss)
    return (
        0.2104542553 * ll + 0.7936177850 * mm - 0.0040720468 * s3,
        1.9779984951 * ll - 2.4285922050 * mm + 0.4505937099 * s3,
        0.0259040371 * ll + 0.7827717662 * mm - 0.8086757660 * s3,
    )


@lru_cache(maxsize=131072)
def oklab_metrics(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """Return OKLab lightness (0..100), chroma (0..100-ish) and hue degrees."""
    L, a, b = rgb_to_oklab(rgb)
    chroma = sqrt(a * a + b * b)
    hue = degrees(atan2(b, a))
    if hue < 0.0:
        hue += 360.0
    return L * 100.0, chroma * 100.0, hue


def delta_e_oklab(a: Sequence[int], b: Sequence[int]) -> float:
    """Euclidean OKLab difference on a convenient ~0..100 scale."""
    aa = tuple(_clamp8(v) for v in a[:3])
    bb = tuple(_clamp8(v) for v in b[:3])
    la = rgb_to_oklab(aa); lb = rgb_to_oklab(bb)
    return sqrt(sum((la[i] - lb[i]) ** 2 for i in range(3))) * 100.0


def _oklab_hue_error(h1: float, h2: float, c1: float, c2: float) -> float:
    # Hue is unstable for near-neutral colours.  Chroma is scaled by 100 here.
    if min(c1, c2) < 2.5:
        return 0.0
    d = abs(h1 - h2) % 360.0
    return min(d, 360.0 - d)


def _hue_family_penalty(source: tuple[int, int, int], candidate: tuple[int, int, int], fidelity: str) -> float:
    """Discourage catastrophic saturated hue-family swaps.

    This is deliberately not dominant-hue extraction (that is a later step).
    It only protects an individual chromatic source colour during candidate
    matching, e.g. yellow must not become pink when a reasonable yellow/orange
    swatch is available.
    """
    if fidelity in ("Fast", "Exact"):
        return 0.0
    _sL, sC, sH = oklab_metrics(source)
    _dL, dC, dH = oklab_metrics(candidate)
    if sC < 5.0:
        return 0.0
    hue = _oklab_hue_error(sH, dH, sC, dC)
    penalty = 0.0
    # Mapping a vivid source into a nearly neutral candidate is visibly wrong.
    if dC < max(2.5, sC * 0.28):
        penalty += (sC - dC) * (0.18 if fidelity == "Balanced" else 0.32)
    # Gentle up to 45°, then increasingly expensive across hue families.
    if hue > 45.0:
        excess = hue - 45.0
        penalty += excess * (0.035 if fidelity == "Balanced" else 0.080)
        if hue > 85.0:
            penalty += (hue - 85.0) * (0.060 if fidelity == "Balanced" else 0.120)
    return penalty


@lru_cache(maxsize=131072)
def color_metrics(rgb: tuple[int, int, int]) -> tuple[float, float, float, float]:
    """Return Lab lightness, HSV saturation, hue degrees and linear luminance."""
    L, a, b = rgb_to_lab(rgb)
    r, g, bl = (_clamp8(v) / 255.0 for v in rgb)
    h, s, _v = colorsys.rgb_to_hsv(r, g, bl)
    lr, lg, lb = (_linear_channel(v) for v in rgb)
    luminance = 0.2126 * lr + 0.7152 * lg + 0.0722 * lb
    return L, s * 100.0, h * 360.0, luminance


def delta_e76(a: Sequence[int], b: Sequence[int]) -> float:
    aa = tuple(_clamp8(v) for v in a[:3])
    bb = tuple(_clamp8(v) for v in b[:3])
    la = rgb_to_lab(aa); lb = rgb_to_lab(bb)
    return sqrt(sum((la[i] - lb[i]) ** 2 for i in range(3)))




def delta_e2000(a: Sequence[int], b: Sequence[int]) -> float:
    """CIEDE2000 perceptual color difference for display sRGB inputs."""
    aa = tuple(_clamp8(v) for v in a[:3]); bb = tuple(_clamp8(v) for v in b[:3])
    L1,a1,b1 = rgb_to_lab(aa); L2,a2,b2 = rgb_to_lab(bb)
    C1=sqrt(a1*a1+b1*b1); C2=sqrt(a2*a2+b2*b2); Cbar=(C1+C2)/2.0
    G=0.5*(1.0-sqrt((Cbar**7)/(Cbar**7+25.0**7))) if Cbar>0 else 0.0
    a1p=(1.0+G)*a1; a2p=(1.0+G)*a2
    C1p=sqrt(a1p*a1p+b1*b1); C2p=sqrt(a2p*a2p+b2*b2)
    def hp(x,y):
        if x==0 and y==0:return 0.0
        h=degrees(atan2(y,x))
        return h+360.0 if h<0 else h
    h1p=hp(a1p,b1); h2p=hp(a2p,b2)
    dLp=L2-L1; dCp=C2p-C1p
    dh=h2p-h1p
    if C1p*C2p==0:dhp=0.0
    elif abs(dh)<=180.0:dhp=dh
    elif dh>180.0:dhp=dh-360.0
    else:dhp=dh+360.0
    dHp=2.0*sqrt(C1p*C2p)*sin(radians(dhp)/2.0)
    Lbar=(L1+L2)/2.0; Cbarp=(C1p+C2p)/2.0
    if C1p*C2p==0:hbar=h1p+h2p
    elif abs(h1p-h2p)<=180.0:hbar=(h1p+h2p)/2.0
    elif h1p+h2p<360.0:hbar=(h1p+h2p+360.0)/2.0
    else:hbar=(h1p+h2p-360.0)/2.0
    T=(1.0-0.17*cos(radians(hbar-30.0))+0.24*cos(radians(2*hbar))
       +0.32*cos(radians(3*hbar+6.0))-0.20*cos(radians(4*hbar-63.0)))
    dtheta=30.0*exp(-((hbar-275.0)/25.0)**2)
    Rc=2.0*sqrt((Cbarp**7)/(Cbarp**7+25.0**7)) if Cbarp>0 else 0.0
    Sl=1.0+(0.015*(Lbar-50.0)**2)/sqrt(20.0+(Lbar-50.0)**2)
    Sc=1.0+0.045*Cbarp; Sh=1.0+0.015*Cbarp*T
    Rt=-sin(radians(2.0*dtheta))*Rc
    x=dLp/Sl; y=dCp/Sc; z=dHp/Sh
    return sqrt(max(0.0,x*x+y*y+z*z+Rt*y*z))

def _rgb_distance_scaled(a: Sequence[int], b: Sequence[int]) -> float:
    # 0..100-ish scale so the fidelity penalties have stable meaning.
    return sqrt(sum((_clamp8(a[i]) - _clamp8(b[i])) ** 2 for i in range(3)) / 3.0) / 255.0 * 100.0


def _hue_error(h1: float, h2: float, s1: float, s2: float) -> float:
    if min(s1, s2) < 7.0:
        return 0.0
    d = abs(h1 - h2) % 360.0
    return min(d, 360.0 - d)


def palette_match_cost(source: Sequence[int], candidate: Sequence[int], *,
                       color_rendering: str = "Perceptual match",
                       fidelity: str = "Balanced") -> float:
    """Return a lower-is-better palette match cost.

    Step 2 uses OKLab as the canonical perceptual matching space. RGB-nearest
    remains byte-for-byte compatible with the legacy fast mode. Balanced and
    Faithful additionally preserve OKLab lightness/chroma/hue and penalize
    catastrophic saturated hue-family swaps such as yellow -> pink.
    """
    validate_color_fidelity(fidelity)
    src = tuple(_clamp8(v) for v in source[:3])
    dst = tuple(_clamp8(v) for v in candidate[:3])
    base = _rgb_distance_scaled(src, dst) if color_rendering == "RGB nearest" else delta_e_oklab(src, dst)
    if color_rendering == "RGB nearest" or fidelity in ("Fast", "Exact"):
        return base

    sL, sC, sH = oklab_metrics(src)
    dL, dC, dH = oklab_metrics(dst)
    light_error = abs(sL - dL)
    dark_loss = max(0.0, sL - dL)
    chroma_error = abs(sC - dC)
    hue_error = _oklab_hue_error(sH, dH, sC, dC)
    bright_boost = 1.0 + max(0.0, sL - 52.0) / 80.0
    family_penalty = _hue_family_penalty(src, dst, fidelity)

    if fidelity == "Balanced":
        return base + light_error * 0.10 + dark_loss * 0.24 * bright_boost + chroma_error * 0.055 + hue_error * 0.010 + family_penalty
    return base + light_error * 0.22 + dark_loss * 0.55 * bright_boost + chroma_error * 0.115 + hue_error * 0.026 + family_penalty

def mapping_pair_metrics(source: Sequence[int], mapped: Sequence[int]) -> dict:
    src = tuple(_clamp8(v) for v in source[:3]); dst = tuple(_clamp8(v) for v in mapped[:3])
    sL, sS, _sH_hsv, sY = color_metrics(src)
    dL, dS, _dH_hsv, dY = color_metrics(dst)
    soL, sC, sH = oklab_metrics(src)
    doL, dC, dH = oklab_metrics(dst)
    return {
        "source_lightness": sL,
        "mapped_lightness": dL,
        "source_saturation": sS,
        "mapped_saturation": dS,
        "source_luminance": sY,
        "mapped_luminance": dY,
        "source_oklab_lightness": soL,
        "mapped_oklab_lightness": doL,
        "source_oklab_chroma": sC,
        "mapped_oklab_chroma": dC,
        "delta_e76": delta_e76(src, dst),
        "delta_e2000": delta_e2000(src, dst),
        "delta_e_oklab": delta_e_oklab(src, dst),
        "hue_error": _oklab_hue_error(sH, dH, sC, dC),
    }

def finalize_mapping_stats(stats: dict) -> dict:
    count = max(0, int(stats.get("mapped_pixels", 0) or 0))
    if count <= 0:
        return {
            "mapped_pixels": 0, "average_source_lightness": 0.0,
            "average_mapped_lightness": 0.0, "lightness_drift": 0.0,
            "luminance_drift_percent": 0.0, "saturation_drift": 0.0,
            "average_delta_e76": 0.0, "max_delta_e76": 0.0, "average_delta_e2000": 0.0, "max_delta_e2000": 0.0,
            "average_delta_e_oklab": 0.0, "max_delta_e_oklab": 0.0, "hue_drift": 0.0, "color_fidelity_rating": "Unavailable",
            "evaluated": False,
            "dark_bias_detected": False,
        }
    srcL = float(stats.get("source_lightness_sum", 0.0)) / count
    dstL = float(stats.get("mapped_lightness_sum", 0.0)) / count
    srcY = float(stats.get("source_luminance_sum", 0.0)) / count
    dstY = float(stats.get("mapped_luminance_sum", 0.0)) / count
    srcS = float(stats.get("source_saturation_sum", 0.0)) / count
    dstS = float(stats.get("mapped_saturation_sum", 0.0)) / count
    drift_pct = (dstY - srcY) / max(0.02, srcY) * 100.0
    light_drift = dstL - srcL
    avg_de2000=round(float(stats.get("delta_e2000_sum", 0.0)) / count, 2)
    max_de2000=round(float(stats.get("delta_e2000_max", 0.0)), 2)
    avg_oklab=round(float(stats.get("delta_e_oklab_sum", 0.0)) / count, 2)
    max_oklab=round(float(stats.get("delta_e_oklab_max", 0.0)), 2)
    hue_drift=round(float(stats.get("hue_error_sum", 0.0)) / count, 2)
    try:
        from ColorPreviewDiagnostics import fidelity_rating
        rating=fidelity_rating(average_delta_e2000=avg_de2000,luminance_drift_percent=drift_pct,max_delta_e2000=max_de2000)
    except Exception:
        rating="Good"
    return {
        "mapped_pixels": count,
        "evaluated": True,
        "average_source_lightness": round(srcL, 2),
        "average_mapped_lightness": round(dstL, 2),
        "lightness_drift": round(light_drift, 2),
        "luminance_drift_percent": round(drift_pct, 2),
        "saturation_drift": round(dstS - srcS, 2),
        "hue_drift": hue_drift,
        "average_delta_e76": round(float(stats.get("delta_e_sum", 0.0)) / count, 2),
        "max_delta_e76": round(float(stats.get("delta_e_max", 0.0)), 2),
        "average_delta_e2000": avg_de2000,
        "max_delta_e2000": max_de2000,
        "average_delta_e_oklab": avg_oklab,
        "max_delta_e_oklab": max_oklab,
        "color_fidelity_rating": rating,
        "dark_bias_detected": bool(light_drift < -4.0 or drift_pct < -10.0),
    }
