"""Compare complete spectrum searches on shipped rasters, with exact parity.

The historical ScreenGuard module comes from Git; both implementations share
current dependencies. Only the desktop-capture boundary is replaced with an
owned copy of existing pixels. This does not measure Paint or native drawing.
"""
from contextlib import closing
import argparse
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import tracemalloc
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import ScreenGuard
from benchmark_v148_image_workflow import old_module


ROOT = Path(__file__).resolve().parent
BASELINE = 'be30fa54a0c58a8d2b6535d31cb6672727f4e6cc'


def source_hashes():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in (
        'ScreenGuard.py', 'DpiSupport.py', 'WindowsSystem.py',
        'benchmark_v148_spectrum.py', 'benchmark_v148_image_workflow.py',
        'test_v148_native_batch22_spectrum.py')}


def scanner(module, source, expected, budget):
    target = (123, (-2000, -2000, 2000, 2000))
    monitor = SimpleNamespace(rectangle=lambda _handle: target[1],
                              verify_modal=lambda *_: None)
    mouse = SimpleNamespace(get_position=lambda: (0, 0))
    guard = module.GuardedMouse(mouse, monitor, target)
    def run():
        with patch('PIL.ImageGrab.grab', side_effect=lambda **_: source.copy()):
            return guard.calibrated_modal_nearest_color_rect(
                (-100, 20), (source.width-101, source.height+19), expected, max_samples=budget)
    return run


def paired(before, after, repeats):
    expected = before()
    if after() != expected:
        raise AssertionError('Warm spectrum result differs from the historical implementation.')
    samples = {'before': [], 'after': []}
    functions = {'before': before, 'after': after}
    orders = []
    for index in range(repeats):
        order = ('before', 'after') if index % 2 == 0 else ('after', 'before')
        orders.append(order)
        for name in order:
            started = time.perf_counter()
            actual = functions[name]()
            elapsed = (time.perf_counter() - started) * 1000
            if actual != expected:
                raise AssertionError('Timed spectrum coordinate/RGB/error parity failed.')
            samples[name].append(elapsed)
    result = {'orders': orders, 'exact_output_parity': True, 'output': expected,
              'output_sha256': hashlib.sha256(json.dumps(expected).encode()).hexdigest()}
    for name, operation in functions.items():
        result[name + '_samples_ms'] = samples[name]
        result[name + '_median_ms'] = statistics.median(samples[name])
        calls = [0]
        getpixel = Image.Image.getpixel
        def read(image, point):
            calls[0] += 1
            return getpixel(image, point)
        with patch.object(Image.Image, 'getpixel', new=read):
            if operation() != expected:
                raise AssertionError('Observed-work result parity failed.')
        result[name + '_getpixel_calls'] = calls[0]
        gc.collect()
        tracemalloc.start()
        try:
            if operation() != expected:
                raise AssertionError('Traced spectrum result parity failed.')
            result[name + '_traced_peak_bytes'] = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    return result


def measure(repeats=6):
    if type(repeats) is not int or repeats < 2 or repeats % 2:
        raise ValueError('Use an even number of at least two balanced pairs.')
    hashes = source_hashes()
    legacy = old_module('ScreenGuard', BASELINE)
    definitions = (
        ('app_capture_720x393', 'assets/image-draw-bot-app-screenshot.webp', None, (121,79,201), 70000),
        ('large_capture_1600x1000', 'assets/image-draw-bot-app-screenshot.png', (0,40,1600,1040), (20,160,80), 70000),
        ('paint_reference_76x76', 'assets/paint-tools-reference.png', None, (180,120,40), 70000),
        ('tiny_control_8x8', 'assets/image-draw-bot-app-screenshot.webp', (10,10,18,18), (80,120,160), 70000),
    )
    result = {'baseline_commit': BASELINE, 'python': sys.version.split()[0],
        'platform': platform.platform(), 'numpy': np.__version__, 'pillow': pillow_version,
        'balanced_pairs_per_workload': repeats, 'source_sha256': hashes,
        'scope': 'Complete public GuardedMouse spectrum analysis including capture-copy ownership, geometry checks and refinement. Existing repository pixels only; no new image files. Capture and Win32 monitor boundaries are substituted; no native input, Windows/Paint/GPU throughput or total draw-time claim.',
        'allocation_scope': 'Separate Python/NumPy tracemalloc observations. Excludes most native Pillow cores and process RSS. Numeric strips intentionally add bounded scratch memory.',
        'workloads': {}}
    for name, path, crop, expected, budget in definitions:
        with Image.open(ROOT/path) as original:
            with closing(original.crop(crop) if crop else original.copy()) as selected:
                with closing(selected.convert('RGB')) as source:
                    pixels = source.tobytes()
                    before = scanner(legacy, source, expected, budget)
                    after = scanner(ScreenGuard, source, expected, budget)
                    row = paired(before, after, repeats)
                    if source.tobytes() != pixels:
                        raise AssertionError('A spectrum search changed its borrowed source.')
                    row.update(source=path, crop=crop, size=source.size, requested_rgb=expected,
                        max_samples=budget, source_file_sha256=hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),
                        source_rgb_sha256=hashlib.sha256(pixels).hexdigest())
                    result['workloads'][name] = row
    result['source_unchanged'] = source_hashes() == hashes
    if not result['source_unchanged']:
        raise AssertionError('Relevant source changed during measurement.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = measure(args.repeats)
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(json.dumps({key: {name: value for name, value in row.items()
        if name.endswith(('_median_ms', '_traced_peak_bytes', '_getpixel_calls'))}
        for key, row in result['workloads'].items()}, indent=2))


if __name__ == '__main__':
    main()
