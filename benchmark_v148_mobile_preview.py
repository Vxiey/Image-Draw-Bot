"""Reproduce mobile publication latency and exact output parity, without HTTP.

Uses the exact pre-batch07 source from Git, seeded images, one warmup pair and
alternating candidate/baseline order. Caller-thread latency includes owned
snapshot capture/reduction. Completion also waits for the PNG worker. Neither
is presented as total GUI latency, GPU performance or process peak memory.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import types
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import MobilePreview as candidate
import MobilePreviewQueue as queue


BASELINE = '8a9c848b9dd0f2c4738aee729dace75be2a5778d'


def baseline_module():
    source = subprocess.run(['git', 'show', f'{BASELINE}:MobilePreview.py'],
                            check=True, capture_output=True, text=True).stdout
    module = types.ModuleType('_mobile_preview_batch07_baseline')
    sys.modules[module.__name__] = module
    exec(compile(source, f'{BASELINE}:MobilePreview.py', 'exec'), module.__dict__)
    return module, hashlib.sha256(source.encode()).hexdigest()


def photo(width, height, seed, *, rgba=False):
    pixels = np.random.default_rng(seed).integers(0, 256, (height, width, 4 if rgba else 3), dtype=np.uint8)
    if rgba:
        pixels[:, :, 3] = 255
    return Image.fromarray(pixels)


def image_frames(case):
    if case == 'first_25mp_rgba':
        original = photo(5000, 5000, 7721, rgba=True)
        preview, safety = photo(640, 400, 7722), photo(640, 400, 7723)
        return [{'original': original, 'preview': preview, 'safety': safety}]
    original = photo(1600, 1000, 7701)
    if case == 'unchanged_frames':
        frame = {'original': original, 'preview': photo(640, 400, 7702), 'safety': photo(640, 400, 7703)}
        return [frame] * 3
    return [{'original': original, 'preview': photo(640, 400, 7710+index),
             'safety': photo(640, 400, 7720+index)} for index in range(3)]


def close_frames(frames):
    for image in {id(image): image for frame in frames for image in frame.values()}.values():
        image.close()


def measure(module, frames, *, queued):
    owner = module.MobilePreviewServer()
    owner._server = Mock()  # Exercise publication with no listener or requests.
    calls = 0
    captured_bytes = []
    encode = module._image_png_bytes
    capture = queue.capture_snapshots

    def counted(image):
        nonlocal calls
        if image is not None:
            calls += 1
        return encode(image)

    def captured(*args, **kwargs):
        result = capture(*args, **kwargs)
        if result is not None:
            captured_bytes.append(sum(queue.pixel_bytes(value) for value in
                                      {id(image): image for image in result.values()}.values()))
        return result

    submit_ms = []
    complete_ms = []
    outputs = []
    try:
        with patch.object(module, '_image_png_bytes', counted), patch.object(queue, 'capture_snapshots', captured):
            for frame in frames:
                started = time.perf_counter_ns()
                if queued:
                    owner.queue_images(**frame)
                else:
                    owner.update_images(**frame)
                submitted = time.perf_counter_ns()
                if queued and not owner._image_queue.wait_idle(30):
                    raise TimeoutError('Mobile benchmark encoder did not finish.')
                completed = time.perf_counter_ns()
                submit_ms.append((submitted-started)/1_000_000)
                complete_ms.append((completed-started)/1_000_000)
                # Hashing is deliberately outside the measured publish window.
                outputs.append({name: hashlib.sha256(value).hexdigest() if value is not None else None
                                for name, value in owner._images.items()})
    finally:
        owner.stop()
        if queued:
            owner._image_queue.wait_idle(30)
    return {'caller_ms': submit_ms, 'completion_ms': complete_ms,
            'total_caller_ms': sum(submit_ms), 'total_completion_ms': sum(complete_ms),
            'png_encodes': calls, 'snapshot_bytes_per_request': captured_bytes,
            'max_retained_snapshot_bytes_per_request': max(captured_bytes, default=0),
            'png_sha256_by_frame': outputs}


def run(repeats):
    baseline, baseline_hash = baseline_module()
    cases = {}
    for case in ('unchanged_frames', 'new_plans_same_original', 'first_25mp_rgba'):
        frames = image_frames(case)
        try:
            warm_old = measure(baseline, frames, queued=False)
            warm_new = measure(candidate, frames, queued=True)
            if warm_old['png_sha256_by_frame'] != warm_new['png_sha256_by_frame']:
                raise AssertionError(f'Warmup PNG parity failed: {case}')
            runs = []
            for index in range(repeats):
                gc.collect()
                if index % 2:
                    new = measure(candidate, frames, queued=True)
                    old = measure(baseline, frames, queued=False)
                else:
                    old = measure(baseline, frames, queued=False)
                    new = measure(candidate, frames, queued=True)
                if old['png_sha256_by_frame'] != new['png_sha256_by_frame']:
                    raise AssertionError(f'PNG parity failed: {case}, pair {index}')
                runs.append({'order': 'candidate-first' if index % 2 else 'baseline-first',
                             'baseline': old, 'candidate': new})
            cases[case] = {
                'frames': [{name: {'size': list(image.size), 'mode': image.mode} for name, image in frame.items()}
                           for frame in frames],
                'exact_png_parity': True,
                'median_total_caller_ms': {name: statistics.median(row[name]['total_caller_ms'] for row in runs)
                                           for name in ('baseline', 'candidate')},
                'median_total_completion_ms': {name: statistics.median(row[name]['total_completion_ms'] for row in runs)
                                               for name in ('baseline', 'candidate')},
                'runs': runs,
            }
        finally:
            close_frames(frames)
    paths = ('MobilePreview.py', 'MobilePreviewQueue.py', Path(__file__).name)
    return {
        'baseline_commit': BASELINE, 'baseline_mobile_sha256': baseline_hash,
        'candidate_source_sha256': {str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths},
        'python': sys.version, 'platform': platform.platform(), 'pillow': pillow_version, 'numpy': np.__version__,
        'repetitions': repeats, 'warmup_pairs_per_case': 1, 'snapshot_budget_bytes': queue.SNAPSHOT_BUDGET_BYTES,
        'scope': 'Local in-memory publisher, no HTTP. Caller copy/resize is measured; no Tk scheduling, driver, network or RSS claim.',
        'memory_limit': 'At most one active and one pending/capturing request, each 32 MiB of retained image cores. Caller sources, native Pillow resize/PNG temporaries and encoded bytes are additional.',
        'cases': cases,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, default=Path('docs/v148-batch07-mobile-benchmarks.json'))
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error('--repeats must be between 1 and 20')
    result = run(args.repeats)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    for name, case in result['cases'].items():
        print(name, json.dumps({'caller_ms': case['median_total_caller_ms'],
                               'completion_ms': case['median_total_completion_ms'],
                               'exact_png_parity': case['exact_png_parity']}))


if __name__ == '__main__':
    main()
