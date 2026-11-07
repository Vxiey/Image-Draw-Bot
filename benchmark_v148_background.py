"""Paired public background-removal calls and explicit RGBA-copy accounting."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import time
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, __version__ as pillow_version

import BackgroundRemoval
from benchmark_v148_image_workflow import old_module


ROOT = Path(__file__).resolve().parent
BASELINE = '73788a51c1a3502f03f007e4d2ffe0152f56b7e6'


def run(module, source):
    result = module.remove_background(source)
    with closing(result.image) as image:
        return {'size': list(image.size), 'mode': image.mode,
                'pixels_sha256': hashlib.sha256(image.tobytes()).hexdigest(),
                'metadata': result.metadata}


def copy_accounting(module, source):
    original = Image.Image.copy
    copies = []
    def observed(image):
        result = original(image)
        if result.mode == 'RGBA' and result.size == source.size:
            copies.append(result.width * result.height * 4)
        return result
    with patch.object(Image.Image, 'copy', new=observed):
        run(module, source)
    return {'full_source_rgba_copy_count': len(copies),
            'copied_rgba_pixel_payload_bytes': sum(copies)}


def measure(repeats=5):
    if type(repeats) is not int or not 1 <= repeats <= 20:
        raise ValueError('Use one to twenty repeat pairs.')
    before = old_module('BackgroundRemoval', BASELINE)
    modules = {'before': before, 'after': BackgroundRemoval}
    report = {
        'baseline': BASELINE, 'python': platform.python_version(),
        'pillow': pillow_version, 'numpy': np.__version__, 'platform': platform.platform(),
        'repeats': repeats,
        'scope': 'Public CPU remove_background, including output hashing/closure. Generated local RGBA images; no captures, network, GPU or UI timing.',
        'method': 'One warm exact-output pair, then alternating before/after order. Copy accounting is a separate instrumented call, outside elapsed measurements.',
        'memory_scope': 'Counts only full-source RGBA Image.copy outputs and their width*height*4 pixel payload. Other output/intermediate/native allocations and process RSS are not measured; copied byte volume is not peak memory.',
        'baseline_source_sha256': hashlib.sha256(subprocess.check_output(
            ['git', 'show', BASELINE + ':BackgroundRemoval.py'], cwd=ROOT)).hexdigest(),
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ('BackgroundRemoval.py', 'benchmark_v148_background.py',
                                       'benchmark_v148_image_workflow.py')},
        'cases': {},
    }
    for name in ('opaque_cut', 'partial_alpha_cut', 'transparent_noop', 'uniform_safety_noop'):
        with closing(Image.new('RGBA', (320, 240), (255, 255, 255, 255))) as source:
            if name.endswith('_cut'):
                ImageDraw.Draw(source).rectangle((80, 60, 239, 179), fill=(30, 80, 160, 255))
                if name.startswith('partial'):
                    ImageDraw.Draw(source).rectangle((100, 80, 139, 119), fill=(30, 80, 160, 128))
                    source.putpixel((0, 0), (200, 40, 150, 0))
            elif name == 'transparent_noop':
                source.putalpha(0)
            original = hashlib.sha256(source.tobytes()).hexdigest()
            expected, actual = (run(module, source) for module in modules.values())
            if expected != actual:
                raise AssertionError(f'Output or metadata changed for {name}')
            samples = {label: [] for label in modules}
            for repeat in range(repeats):
                order = tuple(modules) if repeat % 2 == 0 else tuple(reversed(modules))
                for label in order:
                    started = time.perf_counter()
                    value = run(modules[label], source)
                    samples[label].append((time.perf_counter() - started) * 1000)
                    if value != expected:
                        raise AssertionError(f'Output changed during measurement for {name}')
            if hashlib.sha256(source.tobytes()).hexdigest() != original:
                raise AssertionError('Borrowed input was changed')
            report['cases'][name] = {'size': list(source.size), 'exact_output_parity': True,
                'output': actual, 'samples_ms': samples,
                'median_ms': {label: statistics.median(values) for label, values in samples.items()},
                'copy_accounting': {label: copy_accounting(module, source) for label, module in modules.items()}}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch08-background-benchmarks.json')
    args = parser.parse_args()
    report = measure(args.repeats)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({name: {key: case[key] for key in ('median_ms', 'copy_accounting', 'exact_output_parity')}
                      for name, case in report['cases'].items()}, indent=2))
