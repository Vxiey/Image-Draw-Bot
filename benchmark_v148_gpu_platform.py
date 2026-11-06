"""Reproducible CPU comparisons for batch03 GPU-platform preparation work.

Only reads the existing Git baseline. Never discovers GPUs, runs pip, downloads
files, captures the desktop or sends input. Tracemalloc is not RSS/VRAM.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import tracemalloc
import types

import numpy as np
from PIL import Image, __version__ as pillow_version

import GpuAcceleration as acceleration
import PortraitPlanner as portrait
import UniversalGpuAcceleration as universal


ROOT = Path(__file__).resolve().parent
BASELINE = "2fb7abf470a4ef498df9c53f42cddda62d8b652b"


def baseline_module(name, revision):
    source = subprocess.check_output(["git", "show", f"{revision}:{name}.py"], cwd=ROOT)
    module = types.ModuleType("_platform_before_" + name)
    module.__file__ = str(ROOT / (name + ".py"))
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def fingerprint(value):
    if isinstance(value, Image.Image):
        return {"mode": value.mode, "size": value.size,
                "sha256": hashlib.sha256(value.tobytes()).hexdigest()}
    if isinstance(value, np.ndarray):
        return {"shape": value.shape, "dtype": str(value.dtype),
                "sha256": hashlib.sha256(value.tobytes()).hexdigest()}
    if isinstance(value, (list, tuple)):
        return [fingerprint(item) for item in value]
    return value


def output(function):
    value = function()
    try:
        return fingerprint(value)
    finally:
        if isinstance(value, Image.Image):
            value.close()


def timed(function):
    started = time.perf_counter()
    value = function()
    elapsed = (time.perf_counter() - started) * 1000
    if isinstance(value, Image.Image):
        value.close()
    return elapsed


def measure_pair(before, after, repeats):
    expected, actual = output(before), output(after)
    if expected != actual:
        raise AssertionError("Before/after outputs differ")
    samples = [[], []]
    for _ in range(repeats):
        for index, function in enumerate((before, after)):
            samples[index].append(timed(function))
    peaks = []
    for function in (before, after):
        gc.collect()
        tracemalloc.start()
        try:
            timed(function)
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
    return {"before_samples_ms": samples[0], "after_samples_ms": samples[1],
            "before_median_ms": statistics.median(samples[0]),
            "after_median_ms": statistics.median(samples[1]),
            "before_peak_traced_bytes": peaks[0], "after_peak_traced_bytes": peaks[1],
            "exact_output_parity": True,
            "output_sha256": hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()}


def former_rgba_formula(raw):
    # Literal expression from baseline palette_indices_rgba, measured in isolation
    # to avoid unrelated palette-distance work obscuring compositing allocations.
    alpha = raw[:, :, 3].astype(np.float32)
    visible = alpha > 0
    rgb = np.where(alpha[:, :, None] >= 255, raw[:, :, :3].astype(np.float32),
                   (raw[:, :, :3].astype(np.float32) * alpha[:, :, None]
                    + 255 * (255 - alpha[:, :, None])) / 255)
    return rgb, visible


def former_stimulus(size):
    # Literal image construction from baseline GpuAcceleration.benchmark.
    image = Image.new("L", (size, size))
    image.putdata([(x * 17 + y * 31 + (x ^ y)) % 256 for y in range(size) for x in range(size)])
    return image


def measure(revision=BASELINE, repeats=5):
    if type(repeats) is not int or repeats < 1:
        raise ValueError("Repeats must be a positive integer")
    old_universal = baseline_module("UniversalGpuAcceleration", revision)
    old_portrait = baseline_module("PortraitPlanner", revision)
    current = {"UniversalGpuAcceleration": universal, "PortraitPlanner": portrait,
               "GpuAcceleration": acceleration}
    result = {"baseline": revision, "python": sys.version.split()[0], "platform": sys.platform,
              "numpy": np.__version__, "pillow": pillow_version, "repeats": repeats,
              "method": "One exact parity/warm call; alternating before/after elapsed samples; separate traced peak after GC.",
              "scope": "Synthetic CPU work only. Traced bytes exclude some native Pillow buffers and are neither RSS nor GPU memory. Baseline modules import current unchanged/shared dependencies.",
              "after_source_sha256": {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                      for name, module in current.items()}, "measurements": {}}
    measurements = result["measurements"]
    rng = np.random.default_rng(14803)
    raw = rng.integers(0, 256, (768, 1024, 4), dtype=np.uint8)
    measurements["rgba_mixed_1024x768"] = measure_pair(
        lambda: former_rgba_formula(raw), lambda: universal._rgba_visible_rgb(raw), repeats)
    raw[:, :, 3] = 255
    measurements["rgba_opaque_1024x768"] = measure_pair(
        lambda: former_rgba_formula(raw), lambda: universal._rgba_visible_rgb(raw), repeats)
    colors = rng.integers(0, 256, (1024, 3), dtype=np.uint8)
    measurements["oklab_pairs_1024"] = measure_pair(
        lambda: old_universal.pairwise_oklab_distance(colors, gpu_mode="CPU")[0],
        lambda: universal.pairwise_oklab_distance(colors, gpu_mode="CPU")[0], repeats)
    image = Image.fromarray(rng.integers(0, 256, (768, 1024), dtype=np.uint8))
    try:
        measurements["portrait_contrast_1024x768"] = measure_pair(
            lambda: old_portrait._enhance_local_contrast(image, .42),
            lambda: portrait._enhance_local_contrast(image, .42), repeats)
        candidates = [(int(x), int(y), int(min(1023, x + 5)), int(min(767, y + 5)))
                      for x, y in rng.integers((0, 0), (1024, 768), (30_000, 2))]
        saliency = rng.random(1024 * 768).tolist()
        pixels = image.load()
        for wanted in (200, 26_000):
            arguments = (candidates, wanted, saliency, pixels, 1024, 768, .70)
            measurements[f"portrait_select_30000_want_{wanted}"] = measure_pair(
                lambda: old_portrait._select_tone_candidates(*arguments),
                lambda: portrait._select_tone_candidates(*arguments), repeats)
    finally:
        image.close()
    measurements["benchmark_stimulus_1024"] = measure_pair(
        lambda: former_stimulus(1024), lambda: acceleration._benchmark_image(1024), repeats)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/v148-batch03-gpu-platform-benchmarks.json")
    args = parser.parse_args()
    payload = measure(args.baseline, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in entry.items() if "median" in key or "peak" in key}
                      for name, entry in payload["measurements"].items()}, indent=2))
