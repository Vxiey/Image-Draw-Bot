"""Paired actual recovery callbacks; no desktop, input, network or Tk delay.

Run only against a frozen source tree. Both variants use the current real
SessionRecovery implementation and fresh temporary recovery directories. The
baseline compiles only the two historical controller methods, not the old app.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack, closing
import hashlib
import json
from pathlib import Path
import platform
import queue
import statistics
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import weakref


ROOT = Path(__file__).resolve().parent
BASELINE = '3c5fe8fc27ec3b503e2affa6f3ed00cb7856f973'
BASELINE_FILE_SHA256 = 'e1191da0849b3d7cd625a0be82d64e9312ea99a16ce45dd404d615da09cb84e5'
BASELINE_METHODS = ('_save_recovery_checkpoint', '_schedule_recovery_checkpoint')
CANDIDATE_METHODS = BASELINE_METHODS + (
    '_queue_recovery_checkpoint', '_finish_recovery_image_job', '_handle_event',
    '_recovery_option_snapshot', '_cancel_after_attr',
)
SOURCE_FILES = (
    'DrawBot.py', 'RecoveryImagePreparation.py', 'SessionRecovery.py',
    'RuntimePaths.py', 'SubjectFocus.py', Path(__file__).name,
)
SIZE = (2048, 1536)
SEED = 1001
PAIRS = 5


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')


def method_nodes(source, names):
    module = ast.parse(source)
    app = next(node for node in module.body
               if isinstance(node, ast.ClassDef) and node.name == 'DrawBotApp')
    found = {node.name: node for node in app.body if isinstance(node, ast.FunctionDef)}
    return {name: found[name] for name in names}


def method_fingerprints(source, names):
    return {name: {
        'source_sha256': sha256(ast.get_source_segment(source, node).encode('utf-8')),
        'ast_sha256': sha256(ast.dump(node, include_attributes=False).encode('utf-8')),
    } for name, node in method_nodes(source, names).items()}


def source_fingerprints():
    return {name: sha256((ROOT / name).read_bytes()) for name in SOURCE_FILES}


def read_baseline(path):
    raw = (path.read_bytes() if path is not None else subprocess.check_output(
        ['git', 'show', BASELINE + ':DrawBot.py'], cwd=ROOT))
    if sha256(raw) != BASELINE_FILE_SHA256:
        raise ValueError('Baseline file does not match the pinned DrawBot.py source.')
    return raw.decode('utf-8')


def baseline_controller(source, drawbot):
    # Historical methods refer to DrawBotApp by its global name. A private
    # facade preserves that relationship while inheriting unchanged helpers.
    namespace = dict(vars(drawbot))
    namespace['log_event'] = lambda _message: None
    nodes = method_nodes(source, BASELINE_METHODS)
    exec(compile(ast.Module(body=list(nodes.values()), type_ignores=[]),
                 'baseline-' + BASELINE + '-DrawBot.py', 'exec'), namespace)
    facade = type('BaselineRecoveryController', (drawbot.DrawBotApp,),
                  {name: namespace[name] for name in BASELINE_METHODS})
    namespace['DrawBotApp'] = facade
    return facade


class UiRoot:
    """Capture the actual after callback, without simulating its 40 ms wait."""
    def __init__(self):
        self.owner = threading.get_ident()
        self.callbacks = {}
        self.serial = 0

    def after(self, delay, callback):
        if threading.get_ident() != self.owner:
            raise AssertionError('A recovery worker accessed the UI timer.')
        self.serial += 1
        token = f'after#{self.serial}'
        self.callbacks[token] = (delay, callback)
        return token

    def after_cancel(self, token):
        if threading.get_ident() != self.owner:
            raise AssertionError('A recovery worker accessed the UI timer.')
        self.callbacks.pop(token, None)

    def take_callback(self):
        if len(self.callbacks) != 1:
            raise AssertionError('Expected exactly one actual recovery callback.')
        _token, (delay, callback) = self.callbacks.popitem()
        if delay != 40:
            raise AssertionError('Unexpected autosave timer delay.')
        return callback


class UiValue:
    def __init__(self, value, reads):
        self.value = value
        self.owner = threading.get_ident()
        self.reads = reads

    def get(self):
        self.reads.append(threading.current_thread().name)
        if threading.get_ident() != self.owner:
            raise AssertionError('A recovery worker read a UI value.')
        return self.value


def application(source, reads):
    values = {name: UiValue(value, reads) for name, value in {
        'game': 'Other drawing app', 'subject_focus': 'Subject only',
        'gpu_mode': 'CPU', 'brush_px': '2', 'skip_white': True,
        'preview_mode': 'Automatic',
    }.items()}
    return SimpleNamespace(
        root=UiRoot(), events=queue.Queue(), stop=threading.Event(),
        closing=False, shutdown_complete=False, activity=None, worker=None,
        original=source, saved_area=((40, 60), (1064, 828)), corners=[],
        subject_region=(.15, .2, .55, .8), target_lock_passed=False,
        _suppress_recovery=False, recovery_checkpoint_after=None,
        recovery_image_pending=False, **values,
    )


def run_trial(label, controller, source, drawbot, recovery, image_module):
    reads, saves, snapshots = [], [], []
    app = application(source, reads)
    save_image, copy_image = image_module.Image.save, image_module.Image.copy
    ui_ident = threading.get_ident()
    job = None

    def observed_save(image, *args, **kwargs):
        saves.append({'thread': threading.current_thread().name,
                      'on_ui_thread': threading.get_ident() == ui_ident,
                      'format': kwargs.get('format')})
        return save_image(image, *args, **kwargs)

    def observed_copy(image):
        result = copy_image(image)
        if image is source:
            snapshots.append(weakref.ref(result))
        return result

    with tempfile.TemporaryDirectory(prefix='recovery-paired-benchmark-') as directory, ExitStack() as stack:
        directory = Path(directory)
        for name, path in {
            'RECOVERY_DIR': directory, 'STATE_FILE': directory / 'state.json',
            'IMAGE_FILE': directory / 'last-image.png',
            'RENDER_FILE': directory / 'render.json',
        }.items():
            stack.enter_context(patch.object(recovery, name, path))
        stack.enter_context(patch.object(drawbot, 'log_event', lambda _message: None))
        stack.enter_context(patch.object(image_module.Image, 'save', observed_save))
        stack.enter_context(patch.object(image_module.Image, 'copy', observed_copy))
        controller._schedule_recovery_checkpoint(app, include_image=True, delay=40)
        callback = app.root.take_callback()
        publication_ms = None
        try:
            started = time.perf_counter_ns()
            callback()
            dispatched = time.perf_counter_ns()
            if label == 'candidate':
                job = getattr(app, '_recovery_image_job', None)
                if job is None or not job.wait_idle(30):
                    raise RuntimeError('Recovery encoder did not complete.')
                event, value = app.events.get(timeout=5)
                if event != 'recovery_image_prepared' or value is not job:
                    raise AssertionError('Unexpected recovery worker event.')
                # Waiting here replaces Tk polling for measurement purposes;
                # it is never suggested as a production UI-thread operation.
                job._thread.join(timeout=5)
                if job._thread.is_alive():
                    raise RuntimeError('Recovery encoder did not exit.')
                publication_started = time.perf_counter_ns()
                drawbot.DrawBotApp._handle_event(app, event, value)
                finished = time.perf_counter_ns()
                publication_ms = (finished - publication_started) / 1_000_000
            else:
                finished = dispatched
        finally:
            job = job or getattr(app, '_recovery_image_job', None)
            if job is not None:
                job.cancel()
                if not job.wait_idle(30):
                    raise RuntimeError('Benchmark encoder did not finish cleanup.')
                if job._thread is not None:
                    job._thread.join(timeout=5)

        # All inspection/decoding and temporary-directory deletion are outside
        # the measured callback/worker/publication intervals.
        if app.root.callbacks or not app.events.empty():
            raise AssertionError('Recovery left another callback or event pending.')
        if app.original is not source or app._recovery_source_ref() is not source:
            raise AssertionError('Recovery did not retain the borrowed source identity.')
        if list(directory.glob('.recovery-pending-*')):
            raise AssertionError('Recovery left an owned staging directory.')
        state = json.loads(recovery.STATE_FILE.read_text(encoding='utf-8'))
        state.pop('created_at')
        png = recovery._image_path(state['image_sha256']).read_bytes()
        if sha256(png) != state['image_sha256']:
            raise AssertionError('Checkpoint digest differs from the actual PNG.')
        with closing(image_module.open(recovery._image_path(state['image_sha256']))) as cached:
            cached.load()
            if cached.format != 'PNG' or cached.mode != 'RGBA' or cached.size != source.size:
                raise AssertionError('Unexpected saved recovery raster.')
            pixel_digest = sha256(cached.tobytes())
        expected_snapshots = 1 if label == 'candidate' else 0
        if len(snapshots) != expected_snapshots:
            raise AssertionError('Unexpected number of owned source snapshots.')
        for reference in snapshots:
            snapshot = reference()
            if snapshot is not None:
                try:
                    snapshot.getpixel((0, 0))
                except ValueError:
                    pass
                else:
                    raise AssertionError('An owned snapshot remained open.')
        expected_thread = 'MainThread' if label == 'baseline' else 'recovery-image-encoder'
        if saves != [{'thread': expected_thread, 'on_ui_thread': label == 'baseline', 'format': 'PNG'}]:
            raise AssertionError(f'Unexpected PNG execution threads: {saves!r}')
        if not reads or set(reads) != {'MainThread'}:
            raise AssertionError('Checkpoint values were not captured on the UI thread.')
        dispatch_ms = (dispatched - started) / 1_000_000
        return {
            'ui_dispatch_ms': dispatch_ms,
            'ui_final_publication_ms': publication_ms,
            'ui_total_ms': dispatch_ms + (publication_ms or 0),
            'completion_wall_ms': (finished - started) / 1_000_000,
            'png_encode_threads': saves, 'ui_value_read_threads': sorted(set(reads)),
            'owned_source_snapshots': len(snapshots),
            'extra_owned_rgba_payload_bytes': expected_snapshots * source.width * source.height * 4,
            'png_bytes': len(png), 'png_sha256': sha256(png),
            'decoded_pixels_sha256': pixel_digest,
            'checkpoint_without_timestamp_sha256': sha256(canonical(state)),
            'subject_selection': state['subject_selection'],
        }, state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch10-recovery-benchmarks.json')
    parser.add_argument('--baseline-file', type=Path,
                        help='Exact pinned DrawBot.py bytes, instead of reading them with git show.')
    args = parser.parse_args()
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Run the benchmark from the main thread.')
    initial_hashes = source_fingerprints()

    # Imports, deterministic source construction and controller compilation are
    # outside every timed interval. The real app never creates a Tk root here.
    import numpy as np
    import PIL
    from PIL import Image
    import DrawBot as drawbot
    import SessionRecovery as recovery
    from RuntimePaths import atomic_write_text

    historical_source = read_baseline(args.baseline_file)
    current_source = (ROOT / 'DrawBot.py').read_text(encoding='utf-8')
    controllers = {'baseline': baseline_controller(historical_source, drawbot),
                   'candidate': drawbot.DrawBotApp}
    pixels = np.random.default_rng(SEED).integers(0, 256, (SIZE[1], SIZE[0], 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    source = Image.frombytes('RGBA', SIZE, pixels.tobytes())
    del pixels
    pairs = []
    reference_state = None
    try:
        source_pixel_hash = sha256(source.tobytes())
        for index in range(PAIRS):
            order = ('baseline', 'candidate') if index % 2 == 0 else ('candidate', 'baseline')
            pair = {'index': index + 1, 'order': list(order)}
            for label in order:
                result, state = run_trial(label, controllers[label], source, drawbot, recovery, Image)
                if result['decoded_pixels_sha256'] != source_pixel_hash:
                    raise AssertionError('Saved image pixels differ from the borrowed source.')
                if reference_state is None:
                    reference_state = state
                elif state != reference_state:
                    raise AssertionError('Checkpoint or subject state differs between variants/trials.')
                pair[label] = result
            for key in ('png_sha256', 'png_bytes', 'decoded_pixels_sha256',
                        'checkpoint_without_timestamp_sha256', 'subject_selection'):
                if pair['baseline'][key] != pair['candidate'][key]:
                    raise AssertionError(f'Paired output mismatch: {key}')
            pairs.append(pair)
        if sha256(source.tobytes()) != source_pixel_hash:
            raise AssertionError('Recovery modified the borrowed source.')
    finally:
        source.close()
    if source_fingerprints() != initial_hashes:
        raise RuntimeError('Source changed during measurement; no benchmark result was published.')

    metrics = ('ui_dispatch_ms', 'ui_total_ms', 'completion_wall_ms')
    medians = {label: {metric: statistics.median(pair[label][metric] for pair in pairs)
                       for metric in metrics} for label in controllers}
    medians['baseline']['ui_final_publication_ms'] = None  # Included in baseline dispatch.
    medians['candidate']['ui_final_publication_ms'] = statistics.median(
        pair['candidate']['ui_final_publication_ms'] for pair in pairs)
    result = {
        'schema_version': 1, 'baseline_commit': BASELINE,
        'baseline_DrawBot_py_sha256': BASELINE_FILE_SHA256,
        'baseline_input': 'verified-file' if args.baseline_file else 'git-show',
        'python': platform.python_version(), 'platform': platform.platform(),
        'pillow': PIL.__version__, 'numpy': np.__version__,
        'image_size': list(SIZE), 'image_mode': 'RGBA', 'opaque': True,
        'seed': SEED, 'source_pixels_sha256': source_pixel_hash,
        'candidate_extra_owned_rgba_payload_bytes': SIZE[0] * SIZE[1] * 4,
        'pair_count': PAIRS, 'warmup_pairs': 0,
        'scope': (
            'Actual recovery after callback and actual worker event handler; headless timer/value stubs. '
            'Both variants call the same current SessionRecovery in fresh temporary directories. '
            'Timing starts at callback invocation, excludes the configured 40 ms timer delay, and '
            'delivers the actual completed worker event immediately without Tk polling delay. '
            'The benchmark waits for the worker only to measure completion, never as UI guidance. '
            'UI dispatch includes the private source copy; final rename and metadata/fsync remain UI work. '
            'PNG verification, image decoding, source generation and final directory deletion are untimed. '
            'The same lightweight save/copy observers and no-op diagnostic logger are used for both variants.'
        ),
        'memory_scope': (
            'Additional owned RGBA source payload only: width*height*4 bytes, one snapshot per candidate '
            'trial and no concurrent trial. Excludes the shared borrowed source, Python/native allocator '
            'overhead, encoder/hash buffers and all other temporary objects. Process RSS is not measured. '
            'Repeated-request coalescing and cancellation are separately covered by lifecycle regressions.'
        ),
        'source_hashes': initial_hashes,
        'selected_method_hashes': {
            'baseline': method_fingerprints(historical_source, BASELINE_METHODS),
            'candidate': method_fingerprints(current_source, CANDIDATE_METHODS),
        },
        'checkpoint_without_timestamp': reference_state,
        'parity': {'png_bytes_identical': True, 'pixels_identical': True,
                   'subject_state_identical': True, 'borrowed_source_unchanged': True},
        'pairs': pairs, 'medians': medians,
        'interpretation': (
            'This measures one deterministic 3 MP image on this machine and filesystem. '
            'Reduced UI occupancy is distinct from total completion time; asynchronous preparation '
            'need not improve CPU throughput, total wall time or every image workload.'
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps({'output': str(args.output), 'medians': medians, 'parity': result['parity']}, indent=2))


if __name__ == '__main__':
    main()
