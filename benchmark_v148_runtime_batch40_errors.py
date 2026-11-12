"""Exact paired CPU accuracy/normalization measurements on existing assets."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from unittest.mock import patch

import numpy as np
from PIL import Image

import AccuracyEvaluator as accuracy
import UniversalGpuAcceleration as current
from benchmark_v148_runtime_batch40_palette import BASELINE, ROOT, baseline_module


def equal(actual, expected):
    if isinstance(actual, np.ndarray):
        np.testing.assert_array_equal(actual, expected)
    elif isinstance(actual, tuple):
        if len(actual) != len(expected):
            raise AssertionError('Result length changed')
        for left, right in zip(actual, expected):
            equal(left, right)
    elif actual != expected:
        raise AssertionError('Complete result/metadata changed')


def run(ref=BASELINE, pairs=6):
    reference, reference_hash = baseline_module(ref)
    records = []
    with Image.open(ROOT / 'assets' / 'image-draw-bot-app-screenshot.webp') as source, \
            source.transpose(Image.Transpose.FLIP_LEFT_RIGHT) as preview:
        raw = np.asarray(source)
        normalized = raw.astype(np.float32) / 255
        target = np.ascontiguousarray(normalized[:, ::-1])
        normalized.flags.writeable = target.flags.writeable = False

        def complete(module):
            with patch.dict(sys.modules, {'UniversalGpuAcceleration': module}):
                return accuracy.evaluate_preview(source, preview, gpu_mode='CPU')

        workloads = (
            ('Integer RGB normalization', lambda module: module._rgb01(raw)),
            ('Contiguous channel error', lambda module: module.pixel_channel_error(normalized, target, gpu_mode='CPU')),
            ('Strided channel error', lambda module: module.pixel_channel_error(normalized[:, ::-1], target[::-1], gpu_mode='CPU')),
            ('Perceptual pair', lambda module: module.perceptual_pair(normalized, target, gpu_mode='CPU')),
            ('Complete accuracy evaluator', complete),
        )
        for name, operation in workloads:
            expected = operation(reference)
            equal(operation(current), expected)
            samples = []

            def invoke(module):
                start = time.perf_counter()
                result = operation(module)
                elapsed = time.perf_counter() - start
                equal(result, expected)
                return elapsed * 1000

            invoke(reference)
            invoke(current)
            for pair in range(pairs):
                order = ('before', 'after') if pair % 2 == 0 else ('after', 'before')
                row = {'order': list(order)}
                for label in order:
                    row[label + '_ms'] = invoke(reference if label == 'before' else current)
                samples.append(row)
            allocations = {}
            for label, module in (('before', reference), ('after', current)):
                gc.collect()
                tracemalloc.start()
                result = operation(module)
                retained, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                equal(result, expected)
                allocations[label + '_python_traced_peak_bytes'] = peak
                allocations[label + '_python_traced_retained_bytes'] = retained
                del result
            before = statistics.median(row['before_ms'] for row in samples)
            after = statistics.median(row['after_ms'] for row in samples)
            records.append(dict(workload=name, samples=samples, before_median_ms=before,
                                after_median_ms=after, reduction_percent=(1 - after / before) * 100,
                                allocations=allocations))
    return dict(baseline_commit=ref, baseline_module_sha256=reference_hash,
        current_module_sha256=hashlib.sha256((ROOT / 'UniversalGpuAcceleration.py').read_bytes()).hexdigest(),
        source_asset='assets/image-draw-bot-app-screenshot.webp', source_size=list(source.size),
        python=sys.version, numpy=np.__version__, pairs=pairs, workloads=records,
        scope='Exact outputs/metadata on every invocation. Normalization and scalar reduction workloads '
              'are separate; the complete evaluator includes both. Balanced order and separate allocation probes. '
              'Local shared Linux environment; no process-RSS, GPU or physical drawing-speed claim.')


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
            print(f"{item['workload']}: {item['before_median_ms']:.3f} -> {item['after_median_ms']:.3f} ms "
                  f"({item['reduction_percent']:.2f}% reduction); peaks "
                  f"{item['allocations']['before_python_traced_peak_bytes']} -> "
                  f"{item['allocations']['after_python_traced_peak_bytes']} bytes")
