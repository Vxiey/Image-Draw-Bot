"""Reproduce batch 40 stage evidence against the unchanged published code.

Only existing repository source images and resized/palette derivatives are used.
Timing pairs alternate A/B order, and allocation tracing is a separate pass.
No source image, rendered image or new motif is written by this benchmark.
"""
from contextlib import closing
from dataclasses import replace
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
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdaptiveDetail
import AdaptiveRegionHybrid as hybrid
import PixelAccuratePlanner as pixels
import PixelStrokeEngine as strokes
from test_v148_rendering_batch39_pixel_runs import public_options, stable
from test_v148_rendering_batch40_detail import source_image
from test_v148_rendering_batch40_region_work import PALETTE

ROOT = Path(__file__).resolve().parent
BASE = '888116094b91758dded968a7e3b5559683db9ad7'


def historical(filename):
    source = subprocess.check_output(['git', 'show', f'{BASE}:{filename}'], cwd=ROOT, text=True)
    module = types.ModuleType('batch40_reference_' + filename[:-3])
    sys.modules[module.__name__] = module
    exec(compile(source, filename, 'exec'), module.__dict__)
    return module


def signature(value):
    return hashlib.sha256(json.dumps(stable(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def observations(before, after, *, pairs=6):
    for call in (before, after):
        result = call()
        del result
    durations = {'before': [], 'after': []}
    for pair in range(pairs):
        order = (('before', before), ('after', after))
        if pair % 2:
            order = order[::-1]
        for name, call in order:
            gc.collect()
            start = time.perf_counter()
            result = call()
            durations[name].append(round(time.perf_counter() - start, 6))
            del result
    peaks = {}
    for name, call in (('before', before), ('after', after)):
        gc.collect()
        tracemalloc.start()
        result = call()
        peaks[name] = tracemalloc.get_traced_memory()[1]
        del result
        tracemalloc.stop()
    return {'pairs_seconds': durations,
        'median_seconds': {name: statistics.median(values) for name, values in durations.items()},
        'tracemalloc_peak_bytes': peaks}


def main():
    old_pixels = historical('PixelAccuratePlanner.py')
    old_strokes = historical('PixelStrokeEngine.py')
    old_hybrid = historical('AdaptiveRegionHybrid.py')
    old_detail = historical('AdaptiveDetail.py')
    report = {'baseline': BASE, 'python': sys.version, 'numpy': np.__version__,
        'method': '6 alternating A/B pairs after warmup; separate traced-allocation pass; stage-local inputs prebuilt',
        'limitations': ['Linux CPU observations, not Windows drawing-time or GPU measurements.',
            'Tracemalloc is not total RSS; vertical batching adds bounded transition-index scratch.',
            'Stage performance is not an application-wide speed claim.'], 'cases': []}
    with source_image(chromatic=True) as source:
        row = {'stage': 'chromatic-detail', 'source': 'palette derivative of golden-regression/small-detail-preservation.png'}
        for name, module in (('before', old_detail), ('after', AdaptiveDetail)):
            output, mask, stats = module.apply_adaptive_detail(source, 'Strong simplify')
            try:
                row[name] = {'changed_source_pixels': int(np.count_nonzero(np.any(np.asarray(output) != np.asarray(source), axis=2))),
                    'protected_pixels': stats.protected_pixels}
            finally:
                output.close(); mask.close()
        report['cases'].append(row)

    with closing(Image.open(ROOT / 'golden-regression/red-bananas-texture.png')) as source:
        for size in ((96, 64), (360, 240), (1536, 1024)):
            with closing(source.resize(size)) as scaled:
                mapped = pixels.build_pixel_map(scaled, PALETTE, gpu_mode='CPU')
            args = mapped.palette_index, mapped.drawable_mask, mapped.edge_map
            before = lambda: old_pixels.micro_detail_map(*args)
            after = lambda: pixels.micro_detail_map(*args)
            a, b = before(), after()
            assert np.array_equal(a, b)
            report['cases'].append(dict(stage='micro-detail', source='golden-regression/red-bananas-texture.png',
                size=size, exact=True, sha256=hashlib.sha256(b.tobytes()).hexdigest(),
                **observations(before, after)))
            del a, b
            if size[0] > 360:
                continue
            _components, labels, _meta = strokes.connected_components(mapped, include_vertical_runs=False)
            before = lambda: old_strokes._vertical_run_chunk(labels, 0, labels.shape[1])
            after = lambda: strokes._vertical_run_chunk(labels, 0, labels.shape[1])
            a, b = before(), after()
            assert a == b
            report['cases'].append(dict(stage='vertical-runs', size=size, exact=True,
                runs=len(b), sha256=signature(b), **observations(before, after)))

            def component_call(function):
                with patch.object(strokes, '_vertical_run_chunk', new=function):
                    components, labels, meta = strokes.connected_components(mapped)
                    return ([vars(component) for component in components], labels.tobytes(), stable(meta))
            a = component_call(old_strokes._vertical_run_chunk)
            b = component_call(strokes._vertical_run_chunk)
            assert a == b
            report['cases'].append(dict(stage='complete-component-builder', size=size, exact=True,
                **observations(lambda: component_call(old_strokes._vertical_run_chunk),
                               lambda: component_call(strokes._vertical_run_chunk))))
            if size != (96, 64):
                continue
            original = hybrid._schedule
            class CountedColor(int):
                calls = 0
                def __int__(self):
                    CountedColor.calls += 1
                    return super().__int__()
            def capture(choices, sequences, *args, **kwargs):
                for timed in (False, True):
                    arguments = list(args)
                    options = dict(arguments[2])
                    if timed:
                        options.update(time_budget_mode='30 sec', unlimited_time=False,
                                       time_budget_active=True, max_seconds=30, manual_max_seconds=30)
                    arguments[2] = options
                    before = lambda: old_hybrid._schedule(choices, sequences, *arguments, **kwargs)
                    after = lambda: original(choices, sequences, *arguments, **kwargs)
                    a, b = before(), after()
                    assert a == b
                    counts = {}
                    counted = [replace(choice, color_index=CountedColor(choice.color_index)) for choice in choices]
                    for name, fn in (('before', old_hybrid._schedule), ('after', original)):
                        CountedColor.calls = 0
                        assert fn(counted, sequences, *arguments, **kwargs) == a
                        counts[name] = CountedColor.calls
                    report['cases'].append(dict(stage='hybrid-schedule', size=size, timed=timed, exact=True,
                        components=len(choices), color_integer_reads=counts, sha256=signature(b),
                        **observations(before, after)))
                return original(choices, sequences, *args, **kwargs)
            with patch.object(hybrid, '_schedule', new=capture):
                plan = hybrid.build_adaptive_execution(mapped, PALETTE, public_options(brush_px=1), size)
            plan['coverage_preview'].close(); plan['error_preview'].close()
    path = ROOT / 'docs/v148-batch40-rendering-validation.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)
    for row in report['cases']:
        print({key: row[key] for key in ('stage', 'size', 'timed', 'before', 'after', 'median_seconds',
            'tracemalloc_peak_bytes', 'color_integer_reads') if key in row})


if __name__ == '__main__':
    main()
