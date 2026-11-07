"""Golden-image regression suite for Image Draw Bot Step 17.

The suite keeps a tiny deterministic set of local synthetic problem images that
exercise the bugs fixed in Steps 1-16: banana yellow drifting to pink/orange,
dominant hue loss, texture over-fragmentation, small-detail loss, timing budget
misses and unsafe correction regressions.

It is intentionally local-only and planning/metrics-only. It never moves the
mouse, never reads the screen, never contacts the network and never stores user
images. The PNGs are generated from code so the same tests can be rebuilt on a
clean checkout without bundling personal data.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from copy import deepcopy
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Iterable
import json
import math
import time

from PIL import Image, ImageDraw, ImageFilter

from RuntimePaths import data_dir, resource_path, atomic_write_text

VERSION = 1
DEFAULT_TARGET_AREA = (240, 160)
DEFAULT_OUTPUT_DIR = data_dir() / "golden-regression"


@dataclass(frozen=True)
class GoldenCase:
    name: str
    description: str
    factory: Callable[[], Image.Image]
    time_budget_seconds: int
    min_visual_accuracy_percent: float
    min_perceptual_color_accuracy_percent: float
    min_hue_accuracy_percent: float | None = None
    min_coverage_percent: float | None = None
    max_estimated_draw_seconds_ratio: float = 1.12
    max_p95_delta_e_oklab: float | None = None
    requires_correction_safe: bool = False
    expected_keywords: tuple[str, ...] = ()

    def manifest_row(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("factory", None)
        return data


def _banana_yellow() -> Image.Image:
    im = Image.new("RGBA", (360, 240), (250, 250, 246, 255))
    d = ImageDraw.Draw(im)
    # Two thick curves build a stable anti-aliased yellow banana shape without
    # needing external assets.
    d.line((58, 132, 104, 176, 190, 184, 292, 114), fill=(94, 60, 26, 255), width=46, joint="curve")
    d.line((66, 118, 118, 154, 190, 158, 284, 92), fill=(248, 211, 45, 255), width=39, joint="curve")
    d.line((87, 118, 132, 138, 202, 136, 260, 97), fill=(255, 232, 83, 255), width=8, joint="curve")
    d.line((50, 132, 68, 121), fill=(62, 42, 26, 255), width=11)
    d.line((286, 91, 306, 78), fill=(69, 49, 30, 255), width=12)
    d.ellipse((146, 150, 158, 162), fill=(181, 117, 34, 255))
    d.ellipse((202, 130, 212, 140), fill=(183, 123, 35, 255))
    return im.filter(ImageFilter.GaussianBlur(0.15))


def _red_bananas_texture() -> Image.Image:
    im = Image.new("RGBA", (360, 240), (244, 235, 213, 255))
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            band = (x // 17 + y // 9) % 4
            px[x, y] = (156 + x // 10 - band * 7, 104 + y // 13 + band * 8, 64 + band * 5, 255)
    d = ImageDraw.Draw(im)
    d.polygon([(8, 50), (92, 24), (136, 76), (52, 99)], fill=(45, 145, 82, 255))
    d.polygon([(236, 24), (352, 58), (298, 108)], fill=(52, 151, 86, 255))
    for offset, fill, hi in ((0, (173, 46, 45, 255), (221, 83, 71, 255)), (35, (132, 36, 48, 255), (194, 73, 79, 255)), (-32, (197, 64, 45, 255), (238, 105, 69, 255))):
        d.line((60, 150 + offset // 3, 120, 112 + offset // 5, 206, 112 - offset // 8, 298, 146 + offset // 6), fill=(65, 36, 25, 255), width=37, joint="curve")
        d.line((66, 144 + offset // 3, 124, 111 + offset // 5, 203, 113 - offset // 8, 291, 139 + offset // 6), fill=fill, width=28, joint="curve")
        d.line((96, 135 + offset // 3, 157, 121 + offset // 5, 231, 124 - offset // 8), fill=hi, width=5, joint="curve")
    return im.filter(ImageFilter.GaussianBlur(0.18))


def _dominant_hues() -> Image.Image:
    im = Image.new("RGBA", (360, 240), (249, 249, 246, 255))
    d = ImageDraw.Draw(im)
    colors = ((221, 43, 54, 255), (247, 209, 38, 255), (42, 165, 86, 255), (48, 100, 220, 255))
    for i, color in enumerate(colors):
        x0 = 19 + i * 84
        d.rounded_rectangle((x0, 28, x0 + 70, 212), radius=18, fill=color, outline=(33, 33, 33, 255), width=3)
        d.ellipse((x0 + 22, 76, x0 + 48, 102), fill=(255, 255, 250, 255))
        d.rectangle((x0 + 18, 146, x0 + 52, 172), fill=(20, 20, 20, 255))
    return im


def _small_details() -> Image.Image:
    im = Image.new("RGBA", (360, 240), (252, 252, 249, 255))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((44, 36, 316, 204), radius=22, fill=(236, 236, 229, 255), outline=(23, 26, 28, 255), width=4)
    for y in range(58, 188, 14):
        d.line((62, y, 298, y), fill=(99, 104, 108, 255), width=1)
    d.ellipse((131, 72, 229, 170), fill=(239, 91, 72, 255), outline=(22, 23, 24, 255), width=3)
    d.ellipse((158, 105, 170, 117), fill=(5, 5, 5, 255))
    d.ellipse((191, 105, 203, 117), fill=(5, 5, 5, 255))
    d.arc((158, 126, 204, 151), 0, 180, fill=(5, 5, 5, 255), width=2)
    d.rectangle((69, 50, 83, 64), fill=(248, 211, 45, 255))
    return im


GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        "yellow-banana-hue-guard",
        "Bright yellow banana that must not regress to pink/orange after OKLab and hue preservation fixes.",
        _banana_yellow,
        80,
        72.0,
        69.0,
        min_hue_accuracy_percent=78.0,
        min_coverage_percent=86.0,
        max_p95_delta_e_oklab=0.25,
        expected_keywords=("yellow", "banana", "hue"),
    ),
    GoldenCase(
        "red-bananas-texture",
        "Red bananas on noisy warm background; checks texture merging without destroying red/green tone anchors.",
        _red_bananas_texture,
        150,
        66.0,
        62.0,
        min_hue_accuracy_percent=70.0,
        min_coverage_percent=80.0,
        max_p95_delta_e_oklab=0.39,
        expected_keywords=("red", "texture", "region"),
    ),
    GoldenCase(
        "dominant-hue-four-color",
        "Large red/yellow/green/blue blocks; catches loss of a dominant hue under tight color ceilings.",
        _dominant_hues,
        75,
        76.0,
        73.0,
        min_hue_accuracy_percent=82.0,
        min_coverage_percent=88.0,
        max_p95_delta_e_oklab=0.24,
        expected_keywords=("dominant", "hue", "palette"),
    ),
    GoldenCase(
        "small-detail-preservation",
        "Small face/line details; catches over-aggressive simplification and correction regressions.",
        _small_details,
        80,
        70.0,
        66.0,
        min_hue_accuracy_percent=74.0,
        min_coverage_percent=83.0,
        max_p95_delta_e_oklab=0.30,
        requires_correction_safe=True,
        expected_keywords=("detail", "edge", "correction"),
    ),
)


def _case_filename(case: GoldenCase) -> str:
    return f"{case.name}.png"


def ensure_local_golden_images(directory: str | Path | None = None, *, overwrite: bool = False,
                               cases: Iterable[GoldenCase] = GOLDEN_CASES, cancelled=lambda:False) -> dict[str, Any]:
    """Create/refresh the local golden PNGs and manifest.

    The images are generated synthetic fixtures, not user uploads. Existing PNGs
    are left untouched by default to make local diffs explicit.
    """
    if cancelled():raise InterruptedError('Golden image regression cancelled.')
    root = Path(directory) if directory is not None else DEFAULT_OUTPUT_DIR
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in cases:
        if cancelled():raise InterruptedError('Golden image regression cancelled.')
        path = root / _case_filename(case)
        with closing(case.factory()) as image:
            if cancelled():raise InterruptedError('Golden image regression cancelled.')
            if overwrite or not path.is_file():
                with closing(image.convert('RGBA')) as rgba:
                    rgba.save(path, 'PNG', optimize=True)
            size=image.size
        row = case.manifest_row()
        row.update({"file": path.name, "width": size[0], "height": size[1]})
        rows.append(row)
    manifest = {
        "version": VERSION,
        "local_only": True,
        "mouse_input": False,
        "screen_capture": False,
        "network": False,
        "user_image_data": False,
        "description": "Synthetic Image Draw Bot golden-image regression fixtures.",
        "cases": rows,
    }
    if cancelled():raise InterruptedError('Golden image regression cancelled.')
    atomic_write_text(root / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"directory": str(root), "manifest": str(root / "manifest.json"), "case_count": len(rows), "cases": rows}


def load_golden_image(case: GoldenCase, directory: str | Path | None = None) -> Image.Image:
    root = Path(directory) if directory is not None else DEFAULT_OUTPUT_DIR
    path = root / _case_filename(case)
    if path.is_file():
        with closing(Image.open(path)) as image:return image.convert('RGBA')
    packaged = resource_path("golden-regression") / _case_filename(case)
    if packaged.is_file():
        with closing(Image.open(packaged)) as image:return image.convert('RGBA')
    with closing(case.factory()) as image:return image.convert('RGBA')


def _num(value: Any, default: float | None = None) -> float | None:
    if isinstance(value,bool):return default
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _accuracy_meta(plan: dict[str, Any]) -> dict[str, Any]:
    options = plan.get("options") if isinstance(plan, dict) else {}
    if not isinstance(options, dict):
        return {}
    return options.get("adaptive_accuracy_meta") if isinstance(options.get("adaptive_accuracy_meta"), dict) else {}


def _delta_e_meta(plan: dict[str, Any]) -> dict[str, Any]:
    options = plan.get("options") if isinstance(plan, dict) else {}
    if not isinstance(options, dict):
        return {}
    delta = options.get("preview_delta_e_meta")
    if isinstance(delta, dict):
        return delta
    acc = _accuracy_meta(plan).get("delta_e_oklab")
    return acc if isinstance(acc, dict) else {}


def _draw_seconds(plan: dict[str, Any]) -> float | None:
    timing = plan.get("draw_time_estimate") if isinstance(plan, dict) else {}
    if isinstance(timing, dict):
        value = _num(timing.get("projected_seconds"), None)
        if value is not None and value>=0:
            return value
    value=_num(plan.get('estimate') if isinstance(plan,dict) else None)
    return value if value is not None and value>=0 else None


def _pass_fail(row: dict[str, Any], case: GoldenCase) -> tuple[bool, list[str]]:
    failures: list[str] = []
    visual = _num(row.get("visual_accuracy_percent"), None)
    color = _num(row.get("perceptual_color_accuracy_percent"), None)
    hue = _num(row.get("hue_accuracy_percent"), None)
    coverage = _num(row.get("coverage_percent"), None)
    p95 = _num(row.get("p95_delta_e_oklab"), None)
    estimated = _num(row.get("estimated_draw_seconds"))
    usable = _num(row.get("usable_seconds"))
    if visual is None or not case.min_visual_accuracy_percent<=visual<=100:
        failures.append(f"visual {visual if visual is not None else 'n/a'} < {case.min_visual_accuracy_percent}")
    if color is None or not case.min_perceptual_color_accuracy_percent<=color<=100:
        failures.append(f"perceptual {color if color is not None else 'n/a'} < {case.min_perceptual_color_accuracy_percent}")
    if case.min_hue_accuracy_percent is not None and (hue is None or not case.min_hue_accuracy_percent<=hue<=100):
        failures.append(f"hue {hue if hue is not None else 'n/a'} < {case.min_hue_accuracy_percent}")
    if case.min_coverage_percent is not None and (coverage is None or not case.min_coverage_percent<=coverage<=100):
        failures.append(f"coverage {coverage if coverage is not None else 'n/a'} < {case.min_coverage_percent}")
    if case.max_p95_delta_e_oklab is not None and (p95 is None or not 0<=p95<=case.max_p95_delta_e_oklab):
        failures.append(f"p95 ΔE {p95 if p95 is not None else 'n/a'} outside required range 0..{case.max_p95_delta_e_oklab:.3f}")
    if estimated is None or estimated<0 or usable is None or usable<=0:
        failures.append('finite estimated draw time and positive usable budget are required')
    elif estimated > usable * case.max_estimated_draw_seconds_ratio:
        failures.append(f"time {estimated:.1f}s > {usable * case.max_estimated_draw_seconds_ratio:.1f}s")
    if case.requires_correction_safe and row.get("correction_safe") is not True:
        failures.append("correction safety was not verified")
    return not failures, failures


def run(make_plan: Callable[..., dict], base_options: dict[str, Any] | None = None, *,
        cases: Iterable[GoldenCase] = GOLDEN_CASES,
        directory: str | Path | None = None,
        target_area: tuple[int, int] = DEFAULT_TARGET_AREA,
        cancelled: Callable[[], bool] = lambda: False,
        ensure_assets: bool = True) -> dict[str, Any]:
    """Run the golden-image regression suite through the supplied planner."""
    if cancelled():raise InterruptedError('Golden image regression cancelled.')
    cases=tuple(cases)
    if ensure_assets:
        ensure_local_golden_images(directory,cases=cases,cancelled=cancelled)
    rows = []
    started_all = time.monotonic()
    for case in cases:
        if cancelled():
            raise InterruptedError("Golden image regression cancelled.")
        options = deepcopy(base_options or {})
        options.update({
            "_preview_plan": True,
            "_preview_mode": "Golden image regression",
            "time_budget_active": True,
            "time_budget_seconds": int(case.time_budget_seconds),
            "max_seconds": int(case.time_budget_seconds),
            "manual_max_seconds": int(case.time_budget_seconds),
            "time_budget_mode": f"Golden {case.time_budget_seconds}s",
            "exact_color_count": options.get("exact_color_count", "Auto"),
            "draw_quality": options.get("draw_quality", "Pixel Accurate"),
            "color_fidelity": options.get("color_fidelity", "Faithful"),
        })
        with closing(load_golden_image(case, directory)) as image:
            plan=None
            try:
                started = time.monotonic()
                plan = make_plan(image, tuple(target_area), options, cancelled)
                elapsed = time.monotonic() - started
                if cancelled():raise InterruptedError('Golden image regression cancelled.')
                acc = _accuracy_meta(plan)
                de = _delta_e_meta(plan)
                plan_options = plan.get("options") if isinstance(plan, dict) and isinstance(plan.get("options"), dict) else {}
                usable = _num(plan_options.get("deadline_render_budget_seconds",case.time_budget_seconds))
                estimate=_draw_seconds(plan)
                correction = plan_options.get("post_draw_correction_meta") if isinstance(plan_options.get("post_draw_correction_meta"), dict) else {}
                row = {
                    "case": case.name,
                    "description": case.description,
                    "target_seconds": int(case.time_budget_seconds),
                    "usable_seconds": None if usable is None else round(usable, 3),
                    "planning_seconds": round(elapsed, 4),
                    "planned_paths": int(plan.get("count", 0) or 0) if isinstance(plan, dict) else 0,
                    "estimated_draw_seconds": None if estimate is None else round(estimate, 3),
                    "visual_accuracy_percent": acc.get("visual_accuracy_percent"),
                    "source_pixel_accuracy_percent": acc.get("source_pixel_accuracy_percent"),
                    "perceptual_color_accuracy_percent": acc.get("perceptual_color_accuracy_percent"),
                    "luminance_accuracy_percent": acc.get("luminance_accuracy_percent"),
                    "hue_accuracy_percent": acc.get("hue_accuracy_percent"),
                    "edge_accuracy_percent": acc.get("edge_accuracy_percent"),
                    "coverage_percent": acc.get("coverage_percent"),
                    "plan_execution_accuracy_percent": acc.get("plan_execution_accuracy_percent"),
                    "mean_delta_e_oklab": de.get("mean_delta_e_oklab"),
                    "p95_delta_e_oklab": de.get("p95_delta_e_oklab"),
                    "correction_safe": correction.get('safe') if type(correction.get('safe')) is bool else None,
                    "privacy": "synthetic fixture only; no user image stored",
                }
                passed, failures = _pass_fail(row, case)
                row["passed"] = bool(passed)
                row["failures"] = failures
                rows.append(row)
            finally:
                from AutoSketchBudget import _release_trial
                _release_trial(plan,image,options)
    passed_count = sum(1 for row in rows if row.get("passed"))
    return {
        "version": VERSION,
        "local_only": True,
        "mouse_input": False,
        "screen_capture": False,
        "network": False,
        "user_image_data": False,
        "case_count": len(rows),
        "passed_count": passed_count,
        "failed_count": len(rows) - passed_count,
        "passed": bool(rows) and passed_count == len(rows),
        "total_seconds": round(time.monotonic() - started_all, 4),
        "rows": rows,
    }


def format_result(result: dict[str, Any]) -> str:
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    header = f"Golden image regression: {int(result.get('passed_count', 0) or 0)}/{int(result.get('case_count', len(rows)) or len(rows))} passed"
    parts = [header]
    for row in rows:
        status = "PASS" if row.get("passed") else "FAIL"
        visual = row.get("visual_accuracy_percent")
        color = row.get("perceptual_color_accuracy_percent")
        hue = row.get("hue_accuracy_percent")
        estimate = _num(row.get("estimated_draw_seconds"))
        usable = _num(row.get("usable_seconds"))
        metrics = []
        if visual is not None:
            metrics.append(f"visual {float(visual):.1f}%")
        if color is not None:
            metrics.append(f"color {float(color):.1f}%")
        if hue is not None:
            metrics.append(f"hue {float(hue):.1f}%")
        estimate_label='n/a' if estimate is None else f'{estimate:.1f}s'
        usable_label='n/a' if usable is None else f'{usable:.0f}s'
        metrics.append(f"time {estimate_label}/{usable_label}")
        line = f"{row.get('case')} {status} · " + " · ".join(metrics)
        if row.get("failures"):
            line += " · " + "; ".join(map(str, row.get("failures") or []))
        parts.append(line)
    parts.append("Local-only synthetic fixtures; no mouse input, screen capture, network, telemetry or user images.")
    return "\n".join(parts)


if __name__ == "__main__":
    print(json.dumps(ensure_local_golden_images(overwrite=True), indent=2))
