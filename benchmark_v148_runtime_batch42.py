"""Paired CPU observations for bounded edge scratch, using an existing asset.

Run only in an otherwise idle test window. No raster is generated or saved.
The historical UniversalGpuAcceleration consumer is held constant in both
directions, so its old helper call signature needs no adapter and the only
measured implementation difference is ImageGradients.
"""
from contextlib import ExitStack, closing
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
from unittest.mock import patch

import numpy as np
from PIL import Image

import ImageGradients as current


BASELINE = 'e33fa67d17e3c33ccda8e736e7e16c2582d9fc06'
ROOT = Path(__file__).resolve().parent


def historical(filename):
    name = '_runtime42_baseline_' + Path(filename).stem
    source = subprocess.check_output(['git', 'show', f'{BASELINE}:{filename}'], cwd=ROOT)
    module = ModuleType(name)
    module.__file__ = f'{BASELINE}:{filename}'
    sys.modules[name] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def digest(value):
    if isinstance(value, np.ndarray):
        return {'shape': value.shape, 'dtype': value.dtype.str,
                'sha256': hashlib.sha256(value.tobytes()).hexdigest()}
    if isinstance(value, dict):
        return {key: digest(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [digest(item) for item in value]
    if hasattr(value, '__dataclass_fields__'):
        return digest(vars(value))
    if isinstance(value, np.generic):
        return value.item()
    return value


def elapsed(call):
    start = time.perf_counter()
    result = call()
    duration = time.perf_counter() - start
    return duration * 1000.0, result


def peak(call):
    gc.collect()
    tracemalloc.start()
    try:
        result = call()
        _live, maximum = tracemalloc.get_traced_memory()
        return maximum, digest(result)
    finally:
        tracemalloc.stop()


def compare(label, call, before_module, baseline_gpu, *, pairs=4):
    def execute(module):
        with patch.dict(sys.modules, {'ImageGradients': module,
                                      'UniversalGpuAcceleration': baseline_gpu}):
            return call(module)
    warm_before, warm_after = execute(before_module), execute(current)
    expected = digest(warm_before)
    if digest(warm_after) != expected:
        raise AssertionError(f'{label}: complete output differs from the fixed historical gradient')
    del warm_before, warm_after
    samples = {'before_ms': [], 'after_ms': []}
    for repeat in range(pairs):
        order = (('before_ms', before_module), ('after_ms', current))
        if repeat % 2:
            order = order[::-1]
        for key, module in order:
            ms, result = elapsed(lambda: execute(module))
            samples[key].append(ms)
            if digest(result) != expected:
                raise AssertionError(f'{label}: timed output changed')
            del result
    before_peak, before_result = peak(lambda: execute(before_module))
    after_peak, after_result = peak(lambda: execute(current))
    if before_result != expected or after_result != expected:
        raise AssertionError(f'{label}: allocation observation changed output')
    return {'name': label, **samples, 'before_median_ms': statistics.median(samples['before_ms']),
            'after_median_ms': statistics.median(samples['after_ms']),
            'before_traced_peak_bytes': before_peak, 'after_traced_peak_bytes': after_peak,
            'exact_complete_output': True, 'output': expected}


def opencl_layout_observation(module, channels):
    """Observe actual public host owners at the matching historical native ABI.

    Native arithmetic is supplied at the unavailable OpenCL boundary only;
    neither these recorded byte requests nor their Python backing stores are a
    physical VRAM observation. No timing is attributed to the native facade.
    """
    from test_v148_runtime_batch42_opencl_layout import (
        PackedLabBoundary, asset_rgb, measured_profile, retained_owner_bytes)

    class LayoutBoundary(PackedLabBoundary):
        def lab(self, queue, global_size, local_size, source, destination, count):
            self.launch(queue, global_size, local_size, count)
            assert source.data.size == count * 4
            assert destination.data.size == count * channels
            values = destination.data.reshape(-1, channels)
            values[:, :3] = module._oklab_cpu(source.data.reshape(-1, 4)[:, :3])
            if channels == 4:
                values[:, 3] = 0

        def delta(self, queue, global_size, local_size, left, right, destination, count):
            self.launch(queue, global_size, local_size, count)
            assert left.data.size == right.data.size == count * channels
            assert destination.data.size == count
            a = left.data.reshape(-1, channels)[:, :3]
            b = right.data.reshape(-1, channels)[:, :3]
            destination.data[:] = np.linalg.norm(a - b, axis=1)

        def pairwise(self, queue, global_size, local_size, source, destination, count):
            self.launch(queue, global_size, local_size, np.int32(count * count))
            assert source.data.size == count * channels
            assert destination.data.size == count * count
            destination.data[:] = module._pairwise_lab_distance(
                source.data.reshape(-1, channels)[:, :3]).reshape(-1)

    source = asset_rgb()
    colors = np.unique((source * 255).astype(np.uint8).reshape(-1, 3), axis=0)[:31]
    profile = measured_profile()
    calls = (
        ('oklab', lambda **kw: module.oklab_array(source, **kw)),
        ('perceptual_pair', lambda **kw: module.perceptual_pair(source, source[:, ::-1], **kw)),
        ('pairwise', lambda **kw: module.pairwise_oklab_distance(colors, **kw)),
    )
    rows = []
    for label, call in calls:
        boundary = LayoutBoundary()
        expected = call(gpu_mode='CPU')[:-1]
        with ExitStack() as native:
            for name in ('_FAILED', '_OPENCL_CACHE', '_OPENCL_IN_USE'):
                native.enter_context(patch.object(module, name, {}))
            native.enter_context(patch.object(module, '_opencl_context', return_value=boundary.native))
            result = call(profile=profile)
        if not result[-1]['accelerated']:
            raise AssertionError(f'{label}: observation fell back from its native boundary')
        for actual, reference in zip(result[:-1], expected):
            np.testing.assert_array_equal(actual, reference)
        rows.append({'name': label, 'device_buffer_requests_bytes': boundary.allocations,
                     'device_buffer_request_total': sum(size for _flags, size in boundary.allocations),
                     'logical_output_bytes': sum(value.nbytes for value in result[:-1]),
                     'retained_host_owner_bytes': sum(retained_owner_bytes(value) for value in result[:-1]),
                     'outputs_contiguous': [bool(value.flags.c_contiguous) for value in result[:-1]],
                     'exact_cpu_output': True, 'output': digest(result[:-1])})
    return rows


def main():
    import AccuracyEvaluator
    import PixelAccuratePlanner
    import VisualImportanceMap
    before = historical('ImageGradients.py')
    baseline_gpu = historical('UniversalGpuAcceleration.py')
    import UniversalGpuAcceleration as current_gpu
    layout_before = opencl_layout_observation(baseline_gpu, 4)
    layout_after = opencl_layout_observation(current_gpu, 3)
    for old, new in zip(layout_before, layout_after):
        if old['name'] != new['name'] or old['output'] != new['output']:
            raise AssertionError('Complete OpenCL-boundary output changed across the layout revision')
    rows = []
    source_path = ROOT / 'assets' / 'paint-tools-reference.png'
    with closing(Image.open(source_path)) as original, closing(original.convert('RGB')) as rgb:
        for size in ((384, 256), (1536, 1024)):
            with closing(rgb.resize(size, Image.Resampling.NEAREST)) as source, \
                    closing(source.convert('L')) as gray, \
                    closing(source.resize((max(1, size[0] // 4), max(1, size[1] // 4)), Image.Resampling.BOX)) as small, \
                    closing(small.resize(size, Image.Resampling.NEAREST)) as preview:
                luminance = np.asarray(gray, dtype=np.float32) / np.float32(255)
                rows.append(compare(f'gradient_{size[0]}x{size[1]}',
                                    lambda module: module.luminance_edges(luminance), before, baseline_gpu))
                rows.append(compare(f'complete_accuracy_{size[0]}x{size[1]}',
                                    lambda _: AccuracyEvaluator.evaluate_preview(source, preview, gpu_mode='CPU'),
                                    before, baseline_gpu))
                rows.append(compare(f'complete_importance_{size[0]}x{size[1]}',
                                    lambda _: VisualImportanceMap.build_importance_map(source, {'gpu_mode': 'CPU'}),
                                    before, baseline_gpu))
        for size in ((385, 257), (771, 517)):
            with closing(rgb.resize(size, Image.Resampling.NEAREST)) as source:
                palette = ((0, 0, 0), (255, 255, 255), (128, 128, 128), (200, 40, 40), (20, 70, 210))
                rows.append(compare(f'complete_pixel_map_{size[0]}x{size[1]}',
                                    lambda _: PixelAccuratePlanner.build_pixel_map(source, palette, gpu_mode='CPU'),
                                    before, baseline_gpu))
    files = ('ImageGradients.py', 'UniversalGpuAcceleration.py', 'AccuracyEvaluator.py',
             'VisualImportanceMap.py', 'PixelAccuratePlanner.py', 'ShadowDetailEngine.py',
             'test_v148_runtime_batch42_opencl_layout.py',
             Path(__file__).name)
    report = {
        'baseline_commit': BASELINE,
        'baseline_tree': subprocess.check_output(['git', 'rev-parse', f'{BASELINE}^{{tree}}'], cwd=ROOT, text=True).strip(),
        'method': 'Four alternating AB/BA elapsed pairs after exact-output warm checks; separate tracemalloc observations. Fixed historical gradient and universal CPU consumer; other public consumers are current source in both directions.',
        'scope': 'CPU helper and complete numeric consumer calls, not physical GPU execution, native drawing, process RSS or a universal speed claim. Caller-owned source/preview preparation is outside measurements; required returned arrays and all traced scratch inside each call are included.',
        'python': sys.version, 'numpy': np.__version__,
        'fixture': {'path': source_path.relative_to(ROOT).as_posix(),
                    'sha256': hashlib.sha256(source_path.read_bytes()).hexdigest()},
        'sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
        'cases': rows,
    }
    output = ROOT / 'docs' / 'v148-batch42-runtime-gradients.json'
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    layout_report = {key: report[key] for key in ('baseline_commit', 'baseline_tree', 'python', 'numpy', 'fixture', 'sha256')}
    layout_report.update(
        method='Actual public callers with matching historical/current native Lab layouts, deterministic CPU arithmetic only at the native ABI, and exact whole-output comparison. No physical GPU or timing claim.',
        before=layout_before, after=layout_after)
    (ROOT / 'docs' / 'v148-batch42-runtime-opencl-layout.json').write_text(
        json.dumps(layout_report, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps([{key: row[key] for key in ('name', 'before_median_ms', 'after_median_ms',
                     'before_traced_peak_bytes', 'after_traced_peak_bytes', 'exact_complete_output')}
                     for row in rows], indent=2))


if __name__ == '__main__':
    main()
