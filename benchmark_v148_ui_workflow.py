"""Paired CPU measurements against the published batch04 source.

Run from the repository with the project's Python environment. No network,
desktop capture, mouse/keyboard input or native GUI is used.
"""
from contextlib import ExitStack, closing
import argparse
import base64
import gc
import hashlib
import io
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from types import ModuleType, SimpleNamespace
import tracemalloc
from unittest.mock import patch

import numpy as np
from PIL import Image

import CanvasDropPayload
import GameProfiles
import GettingStarted
from test_v148_ui_workflow_batch05_runtime import Widget

BASELINE = '5f3fcfb5c4519e5ed1b9b770ba951918819d725d'
ROOT = Path(__file__).resolve().parent


def previous_module(name, reference):
    source = subprocess.run(['git', 'show', f'{reference}:{name}.py'], cwd=ROOT,
                            check=True, capture_output=True, text=True, encoding='utf8').stdout
    module = ModuleType('_batch05_previous_' + name)
    module.__file__ = str(ROOT / (name+'.py'))
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def compare(before, after, samples):
    expected = before()
    assert after() == expected, 'Before/after outputs differ'
    times = {'before_ms': [], 'after_ms': []}
    for iteration in range(samples):
        order = (('before_ms', before), ('after_ms', after))
        if iteration % 2:
            order = tuple(reversed(order))
        for key, operation in order:
            started = time.perf_counter()
            result = operation()
            times[key].append((time.perf_counter()-started)*1000)
            assert result == expected, 'Repeated output changed'
    peaks = {}
    for key, operation in (('before_bytes', before), ('after_bytes', after)):
        gc.collect()
        tracemalloc.start()
        result = operation()
        _, peaks[key] = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert result == expected
    return {
        'samples_ms': times,
        'median_ms': {key: statistics.median(values) for key, values in times.items()},
        'python_peak_bytes': peaks,
        'output_sha256': hashlib.sha256(json.dumps(expected, ensure_ascii=False,
                                                  sort_keys=True).encode('utf8')).hexdigest(),
    }


def guide_fixture(module, stack):
    for name in ('CTkToplevel', 'CTkLabel', 'CTkOptionMenu', 'CTkFrame', 'CTkButton',
                 'CTkScrollableFrame'):
        stack.enter_context(patch('customtkinter.'+name, Widget))
    stack.enter_context(patch('UiCompatibility.scoped_scrollable_frame', Widget))
    stack.enter_context(patch('WorkspaceLayout.fit_window', return_value=(840, 760)))
    app = SimpleNamespace(root=Widget(), game=tk.StringVar(tk.Tcl(), 'Microsoft Paint'))
    window = module.show_guide(app)
    stack.callback(window.destroy)
    window.flush()
    body = next(child for child in window.children if '<Configure>' in child.bindings)
    labels = []
    pending = [body]
    while pending:
        child = pending.pop()
        if 'text' in child.options:
            labels.append(child)
        pending.extend(child.children)
    counters = {}
    def run():
        for label in labels:
            label.configurations.clear()
        body.width_reads = 0
        for height in range(1000):
            body.bindings['<Configure>'](SimpleNamespace(widget=body, width=700, height=height+300))
        window.flush()
        counters['label_configure_calls'] = sum(len(label.configurations) for label in labels)
        counters['body_width_queries'] = body.width_reads
        return tuple((label.options['text'], label.options['wraplength']) for label in labels)
    return run, counters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default=BASELINE)
    parser.add_argument('--samples', type=int, default=7)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 3 <= args.samples <= 31:
        parser.error('--samples must be between3 and31')
    previous_drops = previous_module('CanvasDropPayload', args.baseline_ref)
    previous_profiles = previous_module('GameProfiles', args.baseline_ref)
    previous_guide = previous_module('GettingStarted', args.baseline_ref)
    rows = {}
    with io.BytesIO() as stream:
        pixels = np.random.default_rng(179).integers(0, 256, (768, 768, 3), dtype=np.uint8)
        with closing(Image.fromarray(pixels)) as image:
            image.save(stream, format='PNG')
        source = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode('ascii')
    def parse_drop(module):
        result = module.parse_canvas_drop(source)
        return result.kind, result.label, result.source
    rows['inline_png'] = compare(lambda: parse_drop(previous_drops),
                                 lambda: parse_drop(CanvasDropPayload), args.samples)
    rows['inline_png']['payload_characters'] = len(source)
    with tempfile.TemporaryDirectory(prefix='v148-ui-workflow-benchmark-') as folder:
        path = Path(folder) / 'profiles.json'
        path.write_text(json.dumps({f'Profile {i:04}': f'custom-{i+1:032x}'
                                    for i in range(1000)}), encoding='utf8')
        snapshots = {module: (dict(module.PROFILES), dict(module.PROFILE_UI))
                     for module in (previous_profiles, GameProfiles)}
        def registry(module):
            original, ui = snapshots[module]
            module.PROFILES.clear()
            module.PROFILES.update(original)
            module.PROFILE_UI.clear()
            module.PROFILE_UI.update(ui)
            module.load_custom_profiles(path)
            return module.PROFILES
        try:
            rows['registry_1000_profiles'] = compare(lambda: dict(registry(previous_profiles)),
                                                      lambda: dict(registry(GameProfiles)), args.samples)
        finally:
            for module, (original, ui) in snapshots.items():
                module.PROFILES.clear()
                module.PROFILES.update(original)
                module.PROFILE_UI.clear()
                module.PROFILE_UI.update(ui)
    with ExitStack() as stack:
        before, before_counts = guide_fixture(previous_guide, stack)
        after, after_counts = guide_fixture(GettingStarted, stack)
        rows['guide_height_events_1000'] = compare(before, after, args.samples)
        rows['guide_height_events_1000']['before_counts'] = dict(before_counts)
        rows['guide_height_events_1000']['after_counts'] = dict(after_counts)
        rows['guide_height_events_1000']['scope'] = (
            'Actual guide callbacks with fake widgets; excludes native Tk layout/rendering. '
            'Fake call recording contributes to the reported Python allocation peak.')
    output = {
        'baseline_ref': args.baseline_ref,
        'python': sys.version,
        'method': 'Seven alternating paired warm samples by default; exact output comparison. '
                  'tracemalloc measures Python allocations, not process RSS or native GUI cost.',
        'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                          for name in ('CanvasDropPayload.py', 'GettingStarted.py', 'GameProfiles.py',
                                       'UiCompatibility.py', 'SmartDropInCanvas.py', 'RegionPicker.py')},
        'results': rows,
    }
    text = json.dumps(output, indent=2, ensure_ascii=False)+'\n'
    if args.output:
        args.output.write_text(text, encoding='utf8')
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
