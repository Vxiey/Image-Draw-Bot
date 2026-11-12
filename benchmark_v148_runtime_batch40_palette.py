"""Paired whole-mapper comparisons using committed image assets only."""
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
from types import ModuleType

import numpy as np
from PIL import Image

import UniversalGpuAcceleration as current


BASELINE = '888116094b91758dded968a7e3b5559683db9ad7'
ROOT = Path(__file__).resolve().parent


def baseline_module(ref):
    source = subprocess.check_output(['git', 'show', f'{ref}:UniversalGpuAcceleration.py'],
                                     cwd=ROOT, text=True)
    module = ModuleType('_batch40_palette_reference')
    module.__file__ = str(ROOT / 'UniversalGpuAcceleration.py')
    sys.modules[module.__name__] = module
    exec(compile(source, f'{ref}:UniversalGpuAcceleration.py', 'exec'), module.__dict__)
    return module, hashlib.sha256(source.encode()).hexdigest()


def run(ref=BASELINE, pairs=6):
    reference, reference_hash = baseline_module(ref)
    records = []
    # Small and large; byte distance and perceptual; no custom colors and a
    # sparse custom palette spanning block boundaries. The repeated final
    # swatch exercises stable ties across the first/final blocks.
    workloads = (
        ('Paint reference', 'paint-tools-reference.png', None, 20, 'Perceptual match', 'Faithful', False),
        ('Application screenshot RGB', 'image-draw-bot-app-screenshot.webp', (480, 262), 20, 'RGB nearest', 'Balanced', False),
        ('Icon sparse custom', 'image-draw-bot-icon.png', (192, 192), 70, 'Perceptual match', 'Faithful', True),
        ('Screenshot sparse custom', 'image-draw-bot-app-screenshot.webp', (192, 105), 70, 'RGB nearest', 'Off', True),
    )
    for label, asset, size, count, rendering, fidelity, custom_first in workloads:
        with Image.open(ROOT / 'assets' / asset) as original:
            image = original.copy() if size is None else original.resize(size, Image.Resampling.BOX)
        try:
            with image.convert('RGB') as rgb:
                unique = np.unique(np.asarray(rgb).reshape(-1, 3), axis=0)
            positions = np.linspace(0, len(unique) - 1, count - 1, dtype=int)
            palette = [tuple(map(int, unique[index])) for index in positions]
            palette.append(palette[0])
            candidates = tuple(reversed(range(len(palette))))
            custom = tuple(i in (33, 69) for i in range(len(palette)))
            settings = dict(gpu_mode='CPU', color_rendering=rendering,
                            color_fidelity=fidelity, skip_white=True,
                            custom_mode='Custom colors first' if custom_first else 'Calibrated palette')
            expected = reference.palette_indices_rgba(image, palette, candidates, custom, **settings)

            def invoke(module):
                before = time.perf_counter()
                result = module.palette_indices_rgba(image, palette, candidates, custom, **settings)
                elapsed = time.perf_counter() - before
                for actual, wanted in zip(result[0], expected[0]):
                    np.testing.assert_array_equal(actual, wanted)
                if result[1] != expected[1]:
                    raise AssertionError('Complete route metadata changed')
                return elapsed

            invoke(reference)
            invoke(current)
            samples = []
            for pair in range(pairs):
                order = ('before', 'after') if pair % 2 == 0 else ('after', 'before')
                row = {'order': list(order)}
                for name in order:
                    row[name + '_ms'] = invoke(reference if name == 'before' else current) * 1000
                samples.append(row)
            allocations = {}
            for name, module in (('before', reference), ('after', current)):
                gc.collect()
                tracemalloc.start()
                invoke(module)
                _retained, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                allocations[name + '_python_traced_peak_bytes'] = peak
            before_median = statistics.median(row['before_ms'] for row in samples)
            after_median = statistics.median(row['after_ms'] for row in samples)
            records.append(dict(label=label, asset=asset, size=list(image.size), palette_count=len(palette),
                settings=settings, samples=samples, before_median_ms=before_median,
                after_median_ms=after_median, reduction_percent=(1 - after_median / before_median) * 100,
                allocations=allocations, output_sha256=[hashlib.sha256(array.tobytes()).hexdigest()
                                                       for array in expected[0]]))
        finally:
            image.close()
    return dict(baseline_commit=ref, baseline_module_sha256=reference_hash,
        current_module_sha256=hashlib.sha256((ROOT / 'UniversalGpuAcceleration.py').read_bytes()).hexdigest(),
        python=sys.version, numpy=np.__version__, pairs=pairs, workloads=records,
        scope='Whole public CPU palette mapper, exact outputs and metadata on every invocation. '
              'Balanced order; allocation probes separate from timed samples. Local shared Linux environment; '
              'no physical GPU, drawing-time or process-RSS claim.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = run(args.baseline)
    text = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output is None:
        print(text, end='')
    else:
        args.output.write_text(text, encoding='utf-8')
        for item in report['workloads']:
            print(f"{item['label']}: {item['before_median_ms']:.3f} -> {item['after_median_ms']:.3f} ms "
                  f"({item['reduction_percent']:.2f}% reduction)")
