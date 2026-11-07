"""Reproduce the batch02 storage benchmarks against an existing local Git commit.

This isolates the changed RenderResume and MobilePreview modules while using the
current environment and shared dependencies. It does not fetch files or measure
whole-application throughput. Run with the project's regular Python dependencies.
"""
from __future__ import annotations

import argparse
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

import MobilePreview as mobile
import RenderResume as resume
from test_rc14_sequence_resume import seq_plan


ROOT = Path(__file__).resolve().parent
BASELINE = '1c09774ad22088c5c30a8f8220b6b451fdee9659'


def baseline_module(name: str, revision: str):
    source = subprocess.check_output(
        ['git', 'show', f'{revision}:{name}.py'], cwd=ROOT, text=True,
        encoding='utf-8',
    )
    module = types.ModuleType(f'_storage_benchmark_baseline_{name}')
    module.__file__ = str(ROOT / (name + '.py'))
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def elapsed(function, repeats: int) -> float:
    values = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        values.append(time.perf_counter() - started)
    return statistics.median(values)


def traced_peak(function) -> int:
    tracemalloc.start()
    try:
        function()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def measure(revision: str, repeats: int) -> dict:
    old_resume = baseline_module('RenderResume', revision)
    old_mobile = baseline_module('MobilePreview', revision)
    result = {
        'python': sys.version.split()[0], 'platform': sys.platform,
        'numpy': np.__version__, 'pillow': pillow_version,
        'baseline': revision, 'repeats': repeats,
        'timing_statistic': 'median',
        'scope': 'Isolated changed modules with current shared dependencies; no RSS or whole-application measurement.',
        'measurements': {},
    }
    plan = seq_plan()
    plan['image'] = Image.new('RGB', (2400, 1600), 'white')
    plan['execution_sequence'] = [
        {'color_index': i % 3,
         'path': [(i % 800, i % 600), ((i + 30) % 800, (i + 20) % 600)],
         'phase': 'structure', 'brush_px': 2, 'operation_type': 'stroke'}
        for i in range(5000)
    ]
    plan['count'] = len(plan['execution_sequence'])
    completed = {
        resume.sequence_entry_key(row): 1
        for row in plan['execution_sequence'][::3]
    }
    before = lambda: old_resume.checkpoint_sequence_progress(plan, completed)
    after = lambda: resume.checkpoint_sequence_progress(plan, completed)
    try:
        if before() != after():
            raise AssertionError('Checkpoint output changed; timing is not comparable')
        result['measurements']['sequence_checkpoint_5000_ops_rgb2400x1600'] = {
            'baseline_seconds': elapsed(before, repeats),
            'new_seconds': elapsed(after, repeats),
            'baseline_traced_peak_bytes': traced_peak(before),
            'new_traced_peak_bytes': traced_peak(after),
            'exact_output_equal': True,
        }
    finally:
        plan['image'].close()

    image = Image.fromarray(
        np.random.default_rng(123).integers(0, 256, (1600, 2400, 3), dtype=np.uint8)
    )
    before = lambda: old_mobile._image_png_bytes(image)
    after = lambda: mobile._image_png_bytes(image)
    try:
        if before() != after():
            raise AssertionError('PNG bytes changed; timing is not comparable')
        result['measurements']['mobile_png_rgb2400x1600_to1600'] = {
            'baseline_seconds': elapsed(before, repeats),
            'new_seconds': elapsed(after, repeats),
            'exact_output_equal': True,
            'avoided_full_size_rgba_nominal_pixel_bytes': 2400 * 1600 * 4,
        }
    finally:
        image.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument(
        '--output', type=Path,
        default=ROOT / 'docs' / 'v148-batch02-storage-benchmarks.json',
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    result = measure(args.baseline, args.repeats)
    text = json.dumps(result, indent=2) + '\n'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
