"""Historical palette-dialog parity; no timing or CPU performance measurement.

Loads complete GetColorPositions/PaletteMaps modules from the published parent,
then compares actual selection/rescan controllers with the current worker/poll
route. Only OS selection/target capture, native PhotoImage and presentation are
replaced. Preview bytes are compared exactly before their hashes are reported.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import types
import tkinter as tk
from unittest.mock import patch

from PIL import Image, ImageDraw

import GetColorPositions as current_capture
import PaletteMaps as current_maps
from CalibrationAnchors import make_anchor


ROOT = Path(__file__).resolve().parent
BASELINE = 'bb6dfa6a5e8a43bfcfc77c9e00f52dc2dfd7db9c'
HISTORICAL_FILES = ('GetColorPositions.py', 'PaletteMaps.py')
STATUS_PREFIX = 'Could not scan: '


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def source_manifest():
    return {path.name: digest(path.read_bytes()) for path in sorted(ROOT.glob('*.py'))}


@contextmanager
def historical_modules():
    raw = {name: subprocess.check_output(['git', 'show', f'{BASELINE}:{name}'], cwd=ROOT)
           for name in HISTORICAL_FILES}
    modules = {}
    with ExitStack() as scope:
        for filename in ('PaletteMaps.py', 'GetColorPositions.py'):
            name = '_idb_palette_scan_baseline_' + filename[:-3]
            module = types.ModuleType(name)
            module.__file__ = f'{BASELINE}/{filename}'
            scope.enter_context(patch.dict(sys.modules, {name: module}))
            if filename == 'GetColorPositions.py':
                # Preserve the complete old controller -> complete old scanner
                # relationship, even though the current modules are imported.
                with patch.dict(sys.modules, {'PaletteMaps': modules['PaletteMaps.py']}):
                    exec(compile(raw[filename], module.__file__, 'exec'), module.__dict__)
            else:
                exec(compile(raw[filename], module.__file__, 'exec'), module.__dict__)
            modules[filename] = module
        yield modules['GetColorPositions.py'], modules['PaletteMaps.py'], {
            name: {'bytes': len(value), 'sha256': digest(value)} for name, value in raw.items()}


class Value:
    """A plain numeric/text fixture value with an enforced GUI-thread boundary."""
    def __init__(self, value):
        self.value, self.owner = value, threading.get_ident()

    def get(self):
        assert threading.get_ident() == self.owner, 'Worker read a GUI value'
        return self.value

    def set(self, value):
        assert threading.get_ident() == self.owner, 'Worker wrote a GUI value'
        self.value = value


class Scheduler:
    def __init__(self):
        self.jobs, self.counter = {}, 0
        self.owner = threading.get_ident()

    def after(self, _delay, callback, *args):
        assert threading.get_ident() == self.owner, 'Worker scheduled a Tk callback'
        self.counter += 1
        self.jobs[self.counter] = callback, args
        return self.counter

    def after_cancel(self, token):
        assert threading.get_ident() == self.owner
        self.jobs.pop(token, None)

    def deliver(self, token):
        callback, args = self.jobs.pop(token)
        callback(*args)

    def destroy(self):
        self.jobs.clear()


class Photo:
    def __init__(self, image=None, *, master=None, failure=None):
        assert master is not None and threading.get_ident() == master.owner
        if failure == 'photo':
            raise MemoryError('historical fixture photo allocation')
        self.pixels = None if image is None else (image.mode, image.size, image.tobytes())


class Preview:
    def __init__(self, photo, failure):
        self.photo, self.failure = photo, failure

    def configure(self, *, image, text):
        if self.failure == 'widget':
            raise tk.TclError('historical fixture preview presentation')
        assert text == ''
        self.photo = image


def is_closed(image):
    try:
        image.getpixel((0, 0))
    except ValueError:
        return True
    return False


def fixture_image(recipe, mode):
    if recipe in ('skribbl-preset', 'gartic-preset'):
        preset = current_maps.SKRIBBL if recipe == 'skribbl-preset' else current_maps.GARTIC_PHONE
        colors = tuple(reversed(preset.colors))
        image = Image.new('RGB', (128, ((len(colors)+5)//6)*20+8), (3, 5, 7))
        draw = ImageDraw.Draw(image)
        for index, rgb in enumerate(colors):
            x, y = 8 + index % 6 * 20, 8 + index // 6 * 20
            draw.rectangle((x, y, x+11, y+11), fill=rgb)
    else:
        size = (800, 240) if recipe == 'wide-thumbnail' else (80, 40)
        image = Image.new('RGB', size, (210, 210, 210))
        draw = ImageDraw.Draw(image)
        if recipe not in ('empty-auto', 'paint-grid-empty'):
            draw.rectangle((4, 4, 35, 35), fill=(255, 0, 0))
            draw.rectangle((44, 4, 75, 35), fill=(255, 0, 0) if recipe == 'grid-duplicate' else (0, 0, 255))
        if recipe == 'grid-nonsolid':
            image.putpixel((20, 20), (1, 2, 3))
        if recipe in ('auto-duplicates', 'auto-capped'):
            image.close()
            image = Image.new('RGB', (120, 48), (210, 210, 210))
            draw = ImageDraw.Draw(image)
            for x, rgb in ((4, (255, 0, 0)), (44, (255, 0, 0)), (84, (0, 0, 255))):
                draw.rectangle((x, 4, x+31, 35), fill=rgb)
    draw = None
    if mode == 'RGB':
        return image
    try:
        return image.convert(mode)
    finally:
        image.close()


def cases():
    successful = ('auto', 'grid', 'paint-grid', 'mini-preset', 'preset-fallback',
                  'skribbl-preset', 'gartic-preset', 'auto-duplicates', 'auto-capped',
                  'wide-thumbnail')
    failure = ('empty-auto', 'grid-invalid', 'grid-duplicate', 'grid-nonsolid',
               'paint-grid-empty', 'photo', 'widget')
    for recipe in successful:
        for mode in ('RGB', 'RGBA'):
            for route in ('selection', 'rescan'):
                yield dict(recipe=recipe, mode=mode, route=route)
    for recipe in failure:
        for route in ('selection', 'rescan'):
            yield dict(recipe=recipe, mode='RGBA', route=route)


def run_controller(capture, maps, case):
    recipe, mode, route = case['recipe'], case['mode'], case['route']
    image = fixture_image(recipe, mode)
    original_pixels = image.tobytes()
    previous = image if route == 'rescan' else Image.new('RGB', (16, 12), (17, 33, 51))
    before_previous = previous.tobytes()
    box = (-124, 77, -124+image.width, 77+image.height)
    target_rect = (-200, 0, image.width+300, image.height+300)
    app = capture.CalibrationApp.__new__(capture.CalibrationApp)
    app.root = Scheduler()
    app.closed = False
    app.job = None
    app._scan_job = app._scan_context = app._scan_after = None
    app.on_close = None
    app.profile_key = 'microsoft-paint' if recipe.startswith('paint-grid') else 'generic'
    app.is_paint = recipe.startswith('paint-grid')
    app.max_colors = 1 if recipe == 'auto-capped' else 96
    app.preset = None
    if recipe in ('mini-preset', 'preset-fallback'):
        colors = ((0, 255, 0), (255, 255, 0)) if recipe == 'preset-fallback' else ((0, 0, 255), (255, 0, 0))
        app.preset = maps.Palette('fixture', 'fixture', ('first', 'second'), colors)
    elif recipe in ('skribbl-preset', 'gartic-preset'):
        app.preset = maps.SKRIBBL if recipe == 'skribbl-preset' else maps.GARTIC_PHONE
    app.detect_mode = Value('Grid' if recipe.startswith(('grid', 'paint-grid')) else 'Auto detect')
    app.rows = Value(0 if recipe == 'grid-invalid' else 1)
    app.columns = Value(2)
    app.status = Value('Reviewed old palette')
    app.pending, app.rgbs = [(7, 9)], [(17, 33, 51)]
    app.map_names, app.map_indices = ['reviewed old color'], [9]
    app.anchor, app.anchor_handle = make_anchor((-250, -50, 1100, 900)), 42
    app.snapshot = (box if route == 'rescan' else (0, 0, 16, 12), previous)
    app.photo = Photo(master=app.root)
    app.preview = Preview(app.photo, recipe)
    app.refresh = lambda: None  # Native table/swatch painting is covered by native tests.
    calls, jobs = [], []
    worker_error = None
    try:
        with ExitStack() as scope:
            scope.enter_context(patch.object(capture.ImageTk, 'PhotoImage',
                new=lambda image, **kw: Photo(image, **kw, failure=recipe)))
            scope.enter_context(patch('RegionPicker.select_region',
                new=lambda _owner, selected, _error: selected(box, image)))
            scope.enter_context(patch('TargetCapture.capture_target_metadata_isolated',
                new=lambda _area: {'handle': 99, 'client_rect': target_rect}))
            for name in ('detect_preset', 'sample_grid', 'sample_paint_grid', 'detect_color_swatches'):
                operation = getattr(capture, name)
                def observe(*args, _name=name, _operation=operation, **kwargs):
                    record = {'scanner': _name, 'error': None}
                    calls.append(record)
                    try:
                        return _operation(*args, **kwargs)
                    except BaseException as error:
                        record['error'] = [type(error).__name__, str(error)]
                        raise
                scope.enter_context(patch.object(capture, name, new=observe))
            if route == 'selection':
                app.start_scan()
            else:
                app.read_snapshot()
            job = app._scan_job
            if job is not None:
                jobs.append(job)
                job.thread.join(timeout=10)
                assert not job.thread.is_alive(), 'Historical verification worker did not finish'
                with job._lock:
                    if job._outcome is not None and job._outcome[0] == 'error':
                        worker_error = job._outcome[1]
                app.root.deliver(app._scan_after)
                assert app._scan_job is None and not app.root.jobs
        result = dict(positions=app.pending, rgbs=app.rgbs, names=app.map_names,
            indices=app.map_indices, anchor=app.anchor, anchor_handle=app.anchor_handle,
            status=app.status.get(), preview=app.photo.pixels,
            preview_and_model_agree=app.preview.photo is app.photo,
            source_adopted=app.snapshot[1] is image, source_closed=is_closed(image),
            previous_closed=is_closed(previous), scanner_calls=calls)
        if not result['source_closed']:
            assert image.tobytes() == original_pixels, 'Scan changed source pixels'
        if not result['previous_closed']:
            assert previous.tobytes() == before_previous, 'Scan changed the reviewed snapshot'
        return result, worker_error
    finally:
        if hasattr(app, '_retire_scan'):
            app._retire_scan()
        for job in jobs:
            job.retire()
            if job.thread is not None:
                job.thread.join(timeout=10)
                assert not job.thread.is_alive(), 'Worker outlived verification cleanup'
        app.close()
        previous.close()
        image.close()
        vars(app).clear()


def report_value(value):
    result = dict(value)
    photo = result.pop('preview')
    result['preview'] = None if photo is None else {
        'mode': photo[0], 'size': photo[1], 'bytes': len(photo[2]), 'sha256': digest(photo[2])}
    return result


def verify():
    before = source_manifest()
    report = {'schema': 'image-draw-bot.palette-scan-parity.v1', 'baseline': BASELINE,
        'purpose': 'Exact historical behavior verification; no timing/CPU performance claim',
        'boundaries': ['OS region selection', 'target-window metadata capture',
                       'native PhotoImage allocation', 'native table/swatch presentation'],
        'real_paths': ['complete historical GetColorPositions and PaletteMaps modules',
                       'actual selection callback/read_snapshot',
                       'current PaletteScanJob/worker/mailbox/poll',
                       'all four scanners and preset fallback'],
        'declared_delta': 'Worker scanner errors include their exact exception-class prefix in visible status; no other field is normalized',
        'source_hashes_before': before, 'cases': []}
    try:
        with historical_modules() as (old_capture, old_maps, old_hashes):
            report['historical_modules'] = old_hashes
            for case in cases():
                old, old_worker_error = run_controller(old_capture, old_maps, case)
                new, worker_error = run_controller(current_capture, current_maps, case)
                assert old_worker_error is None
                compared = dict(new)
                delta = None
                if worker_error is not None:
                    errors = [item['error'] for item in old['scanner_calls'] if item['error']]
                    assert errors, ('Unexpected worker error', case, worker_error)
                    error_type, message = errors[-1]
                    assert worker_error == error_type + ': ' + message, (case, worker_error, errors[-1])
                    prefix = STATUS_PREFIX + error_type + ': '
                    assert new['status'].startswith(prefix), (case, new['status'])
                    compared['status'] = STATUS_PREFIX + new['status'][len(prefix):]
                    delta = {'field': 'status', 'exception_prefix': error_type + ': '}
                assert old == compared, (case, report_value(old), report_value(new))
                report['cases'].append({'input': case, 'exact_match': True,
                    'status_delta': delta, 'historical': report_value(old), 'current': report_value(new)})
        report['status'] = 'passed'
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        after = source_manifest()
        report['source_hashes_after'] = after
        report['source_hashes_unchanged'] = before == after
        report['completed_cases'] = len(report['cases'])
        if before != after:
            report['status'] = 'failed'
            report['changed_sources'] = [name for name in sorted(set(before) | set(after))
                                         if before.get(name) != after.get(name)]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/v148-batch24-palette-scan-parity.json')
    args = parser.parse_args()
    report = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'completed_cases': report['completed_cases'],
                      'unchanged_python_sources': len(report['source_hashes_before'])
                        if report['source_hashes_unchanged'] else False,
                      'output': str(args.output), 'error': report.get('error')}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
