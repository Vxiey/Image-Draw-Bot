"""Historical caller parity and host-only OpenCL preparation measurements.

The 586e12d comparison reproduces already-counted P2504/global836; it is not
an additional gain over the incoming 837-entry baseline. This batch completes
that contract with zero new IDs and separately verifies the incoming module.
Only UniversalGpuAcceleration is substituted with its complete Git baseline.
The real public planner and all other shared dependencies are identical. A
typed host facade replaces physical OpenCL context/buffer/kernel boundaries;
its numerical oracle is the same historical cost model on both sides. This
can measure removed CPU preparation in that synthetic pipeline, not device
throughput, real transfer latency, GPU memory, target-app speed or process RSS.
"""
import argparse
import ast
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
import gc
import hashlib
import itertools
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import threading
import time
import tracemalloc
from unittest.mock import patch

import numpy as np
from PIL import Image, __version__ as pillow_version

import DrawBot
import UniversalGpuAcceleration as current
import UniversalHardwareBenchmark as hardware
from benchmark_v148_colour_batch20 import comparable
from benchmark_v148_image_workflow import fingerprint, old_module
from test_v148_platform_batch26_opencl_host import (
    PALETTE, TypedOpenCL, measured_profile, observed_host, pixel_source, public_plan,
    public_plan_settings)
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_sketch_memory import VOLATILE_PATHS
from test_v148_rendering_batch17_layered_diagnostics import calibrated


ROOT = Path(__file__).resolve().parent
BASELINE = '586e12db5ea5142951c844f60dc2364f07a01c37'
COMPLETION_BASELINE = '5b0c22ac5dc620a911fa2a1f6216e272f644f7db'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob('*.py'))}


@contextmanager
def linked(module):
    # Product consumers import this module at their actual operation boundary.
    # Link the whole module, including its health/session/closure helpers.
    with patch.dict(sys.modules, {'UniversalGpuAcceleration': module}), \
            patch.object(module, '_FAILED', {}), patch.object(module, '_OPENCL_CACHE', {}), \
            patch.object(module, '_OPENCL_IN_USE', {}):
        yield


def run(module, numeric, source, *, kind='direct', mode='Auto', record=False, count=False,
        palette=PALETTE, candidates=(), flags=(), failure=None, stop_kind=None, **settings):
    stopped = threading.Event()
    if stop_kind == 'before':
        stopped.set()
    boundary = TypedOpenCL(numeric=numeric, failure=failure,
                           stop=stopped if stop_kind and stop_kind != 'before' else None,
                           record=record)
    with linked(module), ExitStack() as stack:
        stack.enter_context(patch.object(module, '_opencl_context', return_value=boundary.native))
        stack.enter_context(patch.object(hardware, 'load_hardware_profile', return_value=measured_profile()))
        host = stack.enter_context(observed_host(module)) if count else []
        if kind == 'public':
            plan = public_plan(source, mode)
            try:
                result = comparable(plan)
            finally:
                close_plan(plan, source)
        else:
            try:
                result = {'result': fingerprint(module.palette_indices_rgba(
                    source, palette, candidates, flags, gpu_mode=mode, profile=measured_profile(),
                    cancelled=stopped.is_set, **settings))}
            except (ValueError, TypeError, OverflowError, InterruptedError) as error:
                result = {'error': type(error).__name__, 'message': str(error)}
        health = module.backend_health_snapshot()
        if module._OPENCL_IN_USE:
            raise AssertionError('The actual OpenCL session did not release its borrowed context.')
        if not all(reference() is None for reference in boundary.references):
            raise AssertionError('The operation retained a private native buffer.')
        work = {'host_composite_calls': len(host),
                'owned_rgb_and_visibility_bytes': sum(row['rgb_bytes'] + row['visible_bytes'] for row in host)}
        evidence = {'kernel_calls': boundary.calls, 'transfers': boundary.events, 'health': health}
    return result, work, evidence


class Operation:
    """Prepare boundaries outside a whole product-call timer/allocation trace."""
    def __init__(self, source, *, kind='direct', mode='Auto', palette=PALETTE, **settings):
        self.source, self.kind, self.mode = source, kind, mode
        self.palette, self.settings = palette, settings

    def run(self, module, numeric, *, elapsed=False, trace=False):
        if trace and tracemalloc.is_tracing():
            raise RuntimeError('An external allocation trace is already active.')
        boundary = TypedOpenCL(numeric=numeric, record=False)
        profile = measured_profile()
        stopped = threading.Event()
        # The options dictionary, borrowed image/size, routing fixture and
        # physical-boundary facade exist before the timer/trace begins.
        if self.kind == 'public':
            function = DrawBot.make_plan
            args = (self.source, self.source.size, public_plan_settings(self.mode))
            kwargs = {}
        else:
            function = module.palette_indices_rgba
            args = (self.source, self.palette, (), ())
            kwargs = dict(self.settings, gpu_mode=self.mode, profile=profile,
                          cancelled=stopped.is_set)
        result, evidence = None, {}
        with linked(module), \
                patch.object(module, '_opencl_context', return_value=boundary.native), \
                patch.object(hardware, 'load_hardware_profile', return_value=profile):
            if trace:
                gc.collect()
            try:
                if trace:
                    tracemalloc.start()
                try:
                    started = time.perf_counter() if elapsed else None
                    result = function(*args, **kwargs)
                    if elapsed:
                        evidence['elapsed_ms'] = (time.perf_counter() - started) * 1000
                    if trace:
                        retained, peak = tracemalloc.get_traced_memory()
                        evidence.update(peak_python_bytes=peak, retained_with_result_bytes=retained)
                finally:
                    if trace:
                        tracemalloc.stop()
                # The original result is still live when the trace ends.
                # Equality, hashing, ownership checks and close_plan are outside
                # both intervals. The synthetic kernel's CPU arithmetic remains
                # inside the actual product call on both sides.
                output = comparable(result) if self.kind == 'public' else {'result': fingerprint(result)}
                if module._OPENCL_IN_USE:
                    raise AssertionError('A measured call retained its OpenCL session.')
                if not all(reference() is None for reference in boundary.references):
                    raise AssertionError('A measured call retained a private native buffer.')
                return output, evidence
            finally:
                if self.kind == 'public' and result is not None:
                    close_plan(result, self.source)


def paired_calls(operation, before, expected, repeats, *, verify_only=False):
    modules = {'before': before, 'after': current}
    for module in modules.values():
        actual, evidence = operation.run(module, before)
        if actual != expected or evidence:
            raise AssertionError('The measurement entrypoint differs from the counted caller.')
    if verify_only:
        return {'measurement_entrypoint_verified': True}
    samples = {name: [] for name in modules}
    orders = []
    for index in range(repeats):
        order = ('before', 'after') if index % 2 == 0 else ('after', 'before')
        orders.append(list(order))
        for name in order:
            actual, evidence = operation.run(modules[name], before, elapsed=True)
            if actual != expected:
                raise AssertionError('Timed whole-call output parity failed.')
            samples[name].append(evidence['elapsed_ms'])
    result = {'orders': orders, 'measurement_entrypoint_verified': True}
    for name, module in modules.items():
        result[name + '_samples_ms'] = samples[name]
        result[name + '_median_ms'] = statistics.median(samples[name])
        actual, evidence = operation.run(module, before, trace=True)
        if actual != expected:
            raise AssertionError('Traced whole-call output parity failed.')
        result[name + '_peak_python_bytes'] = evidence['peak_python_bytes']
        result[name + '_retained_with_result_bytes'] = evidence['retained_with_result_bytes']
    return result


def historical_parity(before):
    counts, signatures = Counter(), []
    rng = np.random.default_rng(1482501)
    settings_cases = itertools.product(('RGB nearest', 'Perceptual match'),
        ('Fast', 'Balanced', 'Faithful'), (False, True), (False, True))
    settings_cases = list(settings_cases)
    for size in ((8, 1), (1, 9), (17, 13)):
        for alpha_kind in ('opaque', 'mixed', 'transparent'):
            raw = rng.integers(0, 256, (size[1], size[0], 4), dtype=np.uint8)
            raw[..., 3] = 255 if alpha_kind == 'opaque' else (0 if alpha_kind == 'transparent' else
                np.resize(np.array([0, 1, 64, 128, 254, 255], np.uint8), raw.shape[:2]))
            raw[0, 0, :3] = 0
            for candidates in ((), (4, 4, 2, 3, 1, 0), (3, 2, 3)):
                with closing(Image.fromarray(raw)) as source:
                    original = source.tobytes(), dict(source.info)
                    for rendering, fidelity, skip, first in settings_cases:
                        settings = dict(color_rendering=rendering, color_fidelity=fidelity,
                            skip_white=skip, custom_mode='Custom colors first' if first else 'Calibrated palette')
                        values = [run(module, before, source, record=True, candidates=candidates,
                                      flags=(False, False, True, False, True), **settings)
                                  for module in (before, current)]
                        if values[0][0] != values[1][0] or values[0][2] != values[1][2]:
                            raise AssertionError(('Historical typed OpenCL mismatch', size, alpha_kind, candidates, settings))
                        signatures.append(digest((values[0][0], values[0][2])))
                        counts['typed_opencl_results_metadata_and_transfers'] += 1
                    values = [run(module, before, source, mode='CPU', candidates=candidates,
                                  flags=(False, False, True, False, True),
                                  color_fidelity='Faithful', custom_mode='Custom colors first')
                              for module in (before, current)]
                    if values[0][0] != values[1][0] or values[0][2] != values[1][2]:
                        raise AssertionError('Historical CPU control mismatch.')
                    signatures.append(digest(values[0][0])); counts['cpu_controls'] += 1
                    if (source.tobytes(), source.info) != original:
                        raise AssertionError('A caller changed borrowed input pixels or metadata.')
    with closing(pixel_source()) as source:
        for failure_name, stop_kind in itertools.product(('driver', 'memory', 'interrupt', None),
                                                       (None, 'before', 'native')):
            values = []
            for module in (before, current):
                failure = {'driver': RuntimeError, 'memory': MemoryError,
                           'interrupt': InterruptedError}.get(failure_name)
                failure = failure('controlled native failure') if failure else None
                values.append(run(module, before, source, record=True, failure=failure, stop_kind=stop_kind))
            if values[0][0] != values[1][0] or values[0][2] != values[1][2]:
                raise AssertionError(('Historical native error/Stop mismatch', failure_name, stop_kind))
            signatures.append(digest((values[0][0], values[0][2])))
            counts['native_failures_and_stop'] += 1
        for palette, candidates in (((), ()), (PALETTE, (-1,)), (PALETTE, (len(PALETTE),)),
                                    (PALETTE, (True,)), (PALETTE, (1.5,))):
            values = [run(module, before, source, record=True, palette=palette, candidates=candidates)
                      for module in (before, current)]
            if values[0][0] != values[1][0] or values[0][2] != values[1][2]:
                raise AssertionError('Historical input validation mismatch.')
            signatures.append(digest(values[0][0])); counts['input_errors'] += 1
    return {'counts': dict(counts), 'total': sum(counts.values()), 'output_sha256': digest(signatures)}


def function_source(source, name):
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    return ast.get_source_segment(source, node)


def measure(*, repeats=6, verify_only=False):
    baseline_bytes = subprocess.check_output(['git', 'show', BASELINE + ':UniversalGpuAcceleration.py'], cwd=ROOT)
    before = old_module('UniversalGpuAcceleration', BASELINE)
    incoming_bytes = subprocess.check_output(['git', 'show', COMPLETION_BASELINE + ':UniversalGpuAcceleration.py'], cwd=ROOT)
    incoming = old_module('UniversalGpuAcceleration', COMPLETION_BASELINE)
    current_bytes = (ROOT / 'UniversalGpuAcceleration.py').read_bytes()
    helper_before = function_source(baseline_bytes.decode(), '_rgba_visible_rgb')
    if helper_before != function_source(current_bytes.decode(), '_rgba_visible_rgb'):
        raise AssertionError('GP10 host-compositing implementation changed.')
    if before._OPENCL_SOURCE != current._OPENCL_SOURCE:
        raise AssertionError('OpenCL kernel source changed.')
    if incoming._OPENCL_SOURCE != current._OPENCL_SOURCE:
        raise AssertionError('Incoming OpenCL kernel source changed.')
    hashes = source_hashes()
    report = {'baseline_commit': BASELINE,
        'baseline_role': 'Reproduction of already-counted P2504/global836, not an additional gain over 837 entries.',
        'completion_baseline_commit': COMPLETION_BASELINE, 'new_improvement_ids': 0,
        'completion_baseline_module_sha256': hashlib.sha256(incoming_bytes).hexdigest(),
        'completion_baseline_module_bytes': len(incoming_bytes),
        'complete_historical_module_sha256': hashlib.sha256(baseline_bytes).hexdigest(),
        'complete_historical_module_bytes': len(baseline_bytes),
        'unchanged_opencl_source_sha256': hashlib.sha256(before._OPENCL_SOURCE.encode()).hexdigest(),
        'unchanged_rgba_helper_sha256': hashlib.sha256(helper_before.encode()).hexdigest(),
        'source_sha256_before': hashes, 'python': sys.version.split()[0], 'platform': platform.platform(),
        'numpy': np.__version__, 'pillow': pillow_version, 'scope': __doc__,
        'method': ('Complete historical backend linked through sys.modules for actual local imports. Identical current public planner/shared dependencies. Counted work and typed-transfer evidence outside timing; complete result parity per invocation. '
                   + ('Verification only: no elapsed samples or allocation traces are performed. '
                      if verify_only else
                      'One warm pair, at least six balanced AB/BA elapsed pairs and separate tracemalloc probes. ')
                   + 'No physical GPU, RSS or target-app performance claim.'),
        'timing_scope': 'Only actual palette_indices_rgba or DrawBot.make_plan. Boundary/routing/options construction and patching precede the timer; normalization, equality checks, hashes, ownership checks and image cleanup follow it. The host facade numerical kernel and its allocations execute inside the real call symmetrically; this is synthetic CPU arithmetic, not physical OpenCL timing.',
        'allocation_scope': 'Separate tracemalloc around the same actual call after garbage collection; peak and retained bytes sampled with the raw returned result still alive, then tracing stops before fingerprinting or cleanup. Includes Python/NumPy allocations of the call and synthetic kernel; excludes most Pillow native memory, process RSS, device allocations and fixture construction.',
        'public_plan_parity_exclusions': ['.'.join(path) for path in sorted(VOLATILE_PATHS)],
        'repeats': 0 if verify_only else repeats,
        'historical_parity': historical_parity(before),
        'incoming_completion_parity': historical_parity(incoming), 'results': []}
    with ExitStack() as stack, calibrated(PALETTE):
        opaque_source = stack.enter_context(closing(pixel_source((1024, 768))))
        opaque = stack.enter_context(closing(opaque_source.convert('RGB')))
        mixed = stack.enter_context(closing(pixel_source((512, 384))))
        chunked = stack.enter_context(closing(Image.new('RGBA', (1025, 512), (20, 90, 200, 128))))
        public = stack.enter_context(closing(pixel_source((96, 72))))
        cases = (
            ('opencl-opaque-1024x768', opaque, dict(color_rendering='RGB nearest')),
            ('opencl-mixed-alpha-512x384', mixed, dict(color_fidelity='Faithful')),
            ('opencl-two-tiles-tail-1025x512', chunked, dict(palette=PALETTE[:2], color_rendering='RGB nearest')),
            ('cpu-mixed-alpha-control-512x384', mixed, dict(mode='CPU', color_fidelity='Faithful')),
            ('actual-public-pixel-opencl-96x72', public, dict(kind='public')),
            ('actual-public-pixel-cpu-control-96x72', public, dict(kind='public', mode='CPU')),
        )
        for name, source, settings in cases:
            original = source.tobytes(), dict(source.info)
            old, old_work, old_transfer = run(before, before, source, record=True, count=True, **settings)
            new, new_work, new_transfer = run(current, before, source, record=True, count=True, **settings)
            prior, incoming_work, incoming_transfer = run(incoming, before, source, record=True, count=True, **settings)
            if old != new or old_transfer != new_transfer:
                raise AssertionError('Complete caller/transfer parity failed: ' + name)
            if prior != new or incoming_transfer != new_transfer or incoming_work != new_work:
                raise AssertionError('Incoming P2504 caller/result/work parity failed: ' + name)
            row = {'case': name, 'source_mode': source.mode, 'source_size': source.size,
                   'before_work': old_work, 'after_work': new_work, 'exact_output_parity': True,
                   'incoming_work': incoming_work, 'incoming_exact_output_and_work_parity': True,
                   'output_sha256': digest(old), 'typed_transfer_sha256': digest(old_transfer),
                   'kernel_calls': old_transfer['kernel_calls']}
            operation = Operation(source, **settings)
            row.update(paired_calls(operation, before, old, repeats, verify_only=verify_only))
            del old, new, prior, old_transfer, new_transfer, incoming_transfer
            if (source.tobytes(), source.info) != original:
                raise AssertionError('A measured caller changed its borrowed image.')
            report['results'].append(row)
            print(name, old_work['host_composite_calls'], '->', new_work['host_composite_calls'],
                  'host composites', flush=True)
    after = source_hashes()
    report['source_sha256_after'] = after
    report['sources_unchanged'] = hashes == after
    if not report['sources_unchanged']:
        raise AssertionError('Python source changed during the verification/measurement.')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch26-opencl-host-benchmarks.json')
    args = parser.parse_args()
    if args.repeats < 6 or args.repeats % 2:
        parser.error('Use at least six paired samples and an even repeat count.')
    report = measure(repeats=args.repeats, verify_only=args.verify_only)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Historical comparisons:', report['historical_parity']['total'])
    print('Incoming completion comparisons:', report['incoming_completion_parity']['total'])


if __name__ == '__main__':
    main()
