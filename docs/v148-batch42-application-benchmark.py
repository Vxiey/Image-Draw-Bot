"""Reproduce the two bounded application copy comparisons on existing assets.

Run from the repository using its normal Python environment. Native Tk widgets
and bitmap upload are excluded from the capture-dialog timings; the public
display_screen body and its complete Pillow thumbnail preparation still run.
Mobile measurements include the complete PNG encoder. No asset is generated.
"""
import argparse
import ast
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time
import tracemalloc
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
import MobilePreview as mobile

BASELINE = 'b75ef8e'
PUBLIC_BASELINE = 'e33fa67d17e3c33ccda8e736e7e16c2582d9fc06'
CASES = {
    'mobile-rgba-small': ('mobile', 'image-draw-bot-icon.png', 'RGBA', (256, 256)),
    'mobile-rgba-bound': ('mobile', 'image-draw-bot-icon.png', 'RGBA', (1600, 1600)),
    'mobile-rgba-reduced': ('mobile', 'image-draw-bot-icon.png', 'RGBA', (2400, 2400)),
    'mobile-rgb-control': ('mobile', 'image-draw-bot-icon.png', 'RGB', (1600, 1600)),
    'mobile-l-control': ('mobile', 'image-draw-bot-icon.png', 'L', (256, 256)),
    'capture-rgb-screen': ('capture', 'image-draw-bot-app-screenshot.png', 'RGB', None),
    'capture-rgba-screen': ('capture', 'image-draw-bot-app-screenshot.png', 'RGBA', None),
    'capture-small-control': ('capture', 'image-draw-bot-icon.png', 'RGBA', (63, 37)),
}


def old_function(module, name, owner=None):
    content = subprocess.check_output(['git', 'show', f'{BASELINE}:{module.__name__}.py'], cwd=ROOT, text=True)
    tree = ast.parse(content)
    parent = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner) if owner else tree
    node = next(node for node in parent.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 f'{BASELINE}:{module.__name__}.py', 'exec'), namespace)
    return namespace[name]


class Widget:
    def __init__(self, *args, **kwargs):
        pass
    def title(self, *args):
        pass
    def bind(self, *args, **kwargs):
        pass
    def destroy(self):
        pass
    def pack(self, **kwargs):
        pass


def input_image(case):
    _kind, name, mode, size = CASES[case]
    with Image.open(ROOT / 'assets' / name) as decoded:
        result = decoded.convert(mode)
    if size is not None and result.size != size:
        old = result
        result = old.resize(size, Image.Resampling.LANCZOS)
        old.close()
    return result


def implementations(kind, stack, *, photo=None):
    if kind == 'mobile':
        return {'baseline': old_function(mobile, '_image_png_bytes'), 'candidate': mobile._image_png_bytes}
    import DrawBot
    stack.enter_context(patch('DrawBot.tk.Toplevel', Widget))
    stack.enter_context(patch('DrawBot.ttk.Label', Widget))
    stack.enter_context(patch('DrawBot.ttk.Button', Widget))
    stack.enter_context(patch('PIL.ImageTk.PhotoImage', new=photo or (lambda _view: object())))
    app = SimpleNamespace(closing=False, root=None)
    old = old_function(DrawBot, 'display_screen', 'DrawBotApp')
    return {'baseline': lambda source: old(app, source),
            'candidate': lambda source: DrawBot.DrawBotApp.display_screen(app, source)}


def allocation_probe(case, variant):
    """Fresh-process high-water RSS and separate whole-call allocation probes."""
    kind = CASES[case][0]
    with ExitStack() as stack:
        call = implementations(kind, stack)[variant]
        source = input_image(case)
        stack.callback(source.close)
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result = call(source)
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        del result
        tracemalloc.start()
        result = call(source)
        _current, python_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del result
        copies = []
        original_copy = Image.Image.copy
        def copied(image):
            if image is source:
                copies.append(image.width * image.height * max(4, len(image.getbands())))
            return original_copy(image)
        with patch.object(Image.Image, 'copy', new=copied):
            call(source)
        return {'rss_before_kib': before, 'rss_after_kib': after,
                'rss_high_water_growth_kib': after - before,
                'whole_call_python_peak_bytes': python_peak,
                'source_copy_count': len(copies),
                'source_copy_pixel_payload_bytes': sum(copies)}


def measure(case, rounds):
    kind, name, mode, _size = CASES[case]
    with ExitStack() as stack:
        observed = []
        def photo(view):
            observed.append((view.mode, view.size, hashlib.sha256(view.tobytes()).hexdigest()))
            return object()
        parity_calls = implementations(kind, stack, photo=photo)
        source = input_image(case)
        stack.callback(source.close)
        pixels = hashlib.sha256(source.tobytes()).hexdigest()
        previous = parity_calls['baseline'](source)
        candidate = parity_calls['candidate'](source)
        parity = previous == candidate if kind == 'mobile' else observed[0] == observed[1]
        if not parity:
            raise AssertionError('Baseline/candidate output mismatch: ' + case)
        if kind == 'mobile':
            output = {'png_sha256': hashlib.sha256(candidate).hexdigest(), 'png_bytes': len(candidate)}
        else:
            output = {'mode': observed[1][0], 'size': observed[1][1], 'pixel_sha256': observed[1][2]}
        calls = implementations(kind, stack)
        for call in calls.values():
            call(source)  # Equal complete-call warmups.
        times = {name: [] for name in calls}
        order = []
        for iteration in range(rounds):
            variants = ('baseline', 'candidate') if iteration % 2 == 0 else ('candidate', 'baseline')
            order.append(variants)
            for variant in variants:
                started = time.perf_counter()
                result = calls[variant](source)
                elapsed = time.perf_counter() - started
                times[variant].append(elapsed)
                del result
        if hashlib.sha256(source.tobytes()).hexdigest() != pixels:
            raise AssertionError('Borrowed input was modified: ' + case)
        row = {'case': case, 'kind': kind, 'asset': name, 'mode': mode, 'size': source.size,
               'input_pixel_sha256': pixels, 'output_parity': parity, 'output': output,
               'round_order': order, 'raw_seconds': times,
               'median_seconds': {name: statistics.median(values) for name, values in times.items()}}
    row['candidate_over_baseline'] = row['median_seconds']['candidate'] / row['median_seconds']['baseline']
    row['allocations'] = {}
    for variant in ('baseline', 'candidate'):
        raw = subprocess.check_output([sys.executable, str(Path(__file__).resolve()),
            '--allocation', case, variant], cwd=ROOT, text=True)
        row['allocations'][variant] = json.loads(raw)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--allocation', nargs=2)
    parser.add_argument('--rounds', type=int, default=7)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs' / 'v148-batch42-application-performance.json')
    args = parser.parse_args()
    if args.allocation:
        print(json.dumps(allocation_probe(*args.allocation)))
        return
    sources = ['MobilePreview.py', 'DrawBot.py', 'ImageGeometry.py', 'MobilePreviewQueue.py',
               'docs/v148-batch42-application-benchmark.py']
    def hashes():
        return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}
    before = hashes()
    rows = []
    for case in CASES:
        row = measure(case, args.rounds)
        rows.append(row)
        print(json.dumps({'case': case, 'ratio': row['candidate_over_baseline'],
                          'parity': row['output_parity']}), flush=True)
    after = hashes()
    report = {'schema': 1, 'local_baseline_commit': BASELINE, 'equivalent_public_commit': PUBLIC_BASELINE,
        'equivalent_public_tree': '72e55f2a6d3dad971a13e9ab9141aa521cf15177',
        'source_hashes_before': before, 'source_hashes_after': after,
        'changed_sources': sorted(name for name in before if before[name] != after[name]),
        'asset_sha256': {name: hashlib.sha256((ROOT / 'assets' / name).read_bytes()).hexdigest()
                         for name in {case[1] for case in CASES.values()}},
        'method': f'{args.rounds} alternating baseline/candidate complete-call timing pairs after one equal warmup; allocations are separate fresh-process probes.',
        'limits': [
            'Mobile timing includes resize, alpha composition, RGB conversion and PNG encoding; queue snapshot capture and HTTP transport are outside the encoder boundary.',
            'Capture timing executes actual display_screen with native widget allocation and Tk bitmap upload replaced by inert boundaries; this is not native GUI latency.',
            'tracemalloc measures Python allocations and excludes Pillow native pixel cores. Linux ru_maxrss is a process high-water mark affected by earlier input construction and allocator reuse; growth is not an exact encoder live-set size.',
            'Source-copy payload counts only observed identity-source Pillow copy calls, using four bytes per pixel for these RGB/RGBA inputs. It is not a total RSS reduction claim.',
            'All slower and unchanged controls are retained. Results describe these existing-asset inputs on this host, not universal speed or memory improvements.',
        ], 'cases': rows}
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
