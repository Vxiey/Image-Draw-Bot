"""Planning shares a bounded database observation, never a normalized correction."""
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
from contextvars import copy_context
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import weakref

from PIL import Image, ImageDraw

import DrawBot
import DrawTimeCalibration as timing
import ExecutionCostModel as execution
import RealSpeedBudget as speed
from test_pixel_accurate_v1086 import opts
from test_v148_rendering_batch07_transparency import standard_options
from test_v148_rendering_batch10_physical import physical_options
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch17_layered_diagnostics import calibrated
from test_v148_colour_batch19_regions import PALETTE


def public_source(size=(128, 96)):
    image = Image.new('RGBA', size, 'white')
    pen = ImageDraw.Draw(image)
    try:
        for index, box in enumerate(((8, 8, 55, 40), (72, 8, 118, 40),
                                     (8, 55, 55, 88), (72, 55, 118, 88))):
            scaled = tuple(value * size[axis % 2] // (128 if axis % 2 == 0 else 96)
                           for axis, value in enumerate(box))
            pen.rectangle(scaled, fill=PALETTE[2 + index] + (255,))
        pen.line((17 * size[0] // 128, 18 * size[1] // 96,
                  45 * size[0] // 128, 33 * size[1] // 96), fill='black', width=2)
    finally:
        del pen
    return image


def public_options(name, size=(128, 96)):
    fills = dict(fill_tool_available=True, use_region_fill_engine=True,
                 fill_engine='Safe rectangles', fill_tool_actions=[('fill', (10, 10))],
                 fill_restore_actions=[('brush', (20, 10))])
    cases = {
        'paint_pixel': opts(profile_key='microsoft-paint', profile_name='Microsoft Paint',
            time_budget_mode='Unlimited', unlimited_time=True,
            planning_resolution='Standard', detail_zoom='Off'),
        'paint_fill': standard_options(profile_key='microsoft-paint',
            profile_name='Microsoft Paint', skip_white=True, **fills),
        'gartic_hybrid': physical_options((100, 100), size),
        'gartic_hybrid_fill': physical_options((100, 100), size, **fills),
        'paint_dynamic': standard_options(profile_key='microsoft-paint',
            profile_name='Microsoft Paint', time_budget_mode='Manual', max_seconds=45,
            manual_max_seconds=45, unlimited_time=False,
            custom_color_workflow='Adaptive exact (recommended)', exact_color_available=True,
            exact_color_limit='Auto'),
        'gartic_sketch_auto': standard_options(profile_key='gartic-phone',
            profile_name='Gartic Phone', outline=True, sketch_detail='Auto',
            time_budget_mode='Manual', max_seconds=10, manual_max_seconds=10,
            unlimited_time=False),
    }
    result = cases[name]
    for key in ('_execution_cost_calibration_override', '_hybrid_cost_calibration_override',
                '_time_color_calibration_override'):
        result.pop(key, None)
    result.update(cpu_workers='1', cpu_workers_resolved=1, gpu_mode='CPU')
    return result


@contextmanager
def public_environment(directory, module=timing):
    """Real palette/JSON readers and writers, with private deterministic storage."""
    actual_load = module.load_profile
    actual_speed = speed.load_profile
    with calibrated(PALETTE), ExitStack() as stack:
        stack.enter_context(patch.object(module, 'load_profile', new=actual_load))
        stack.enter_context(patch.object(module, 'profile_timing_file',
            side_effect=lambda key: Path(directory) / (key + '.json')))
        stack.enter_context(patch.object(module, 'FILE', Path(directory) / 'legacy.json'))
        speed_path = Path(directory) / 'speed.json'
        stack.enter_context(patch.object(speed, 'SPEED_FILE', speed_path))
        stack.enter_context(patch.object(speed, 'load_profile',
            side_effect=lambda key, path=None: actual_speed(key, speed_path if path is None else path)))
        stack.enter_context(patch('ResourceAllocation.available_ram_mb', return_value=8192))
        stack.enter_context(patch('ResourceAllocation.logical_cpu_count', return_value=8))
        yield


@contextmanager
def observed(module=timing):
    correct = module.correction_for
    calls = []
    def correction(options, **kwargs):
        result = correct(options, **kwargs)
        calls.append((dict(options), deepcopy(result)))
        return result
    with patch.object(module, 'correction_for', side_effect=correction), \
            patch.object(execution, 'correction_for', side_effect=correction), \
            patch.object(module, '_ensure_profile_db', wraps=module._ensure_profile_db) as ensured, \
            patch.object(module, 'read_json', wraps=module.read_json) as read, \
            patch.object(module, '_valid_item', wraps=module._valid_item) as validated:
        yield calls, ensured, read, validated


def seed_public_contexts(source, options, module=timing, planner=DrawBot.make_plan):
    with observed(module) as (calls, _ensured, _read, _validated):
        plan = planner(source, source.size, dict(options))
    try:
        contexts = {module._key(settings): settings for settings, _result in calls}
    finally:
        close_plan(plan, source)
    for settings in contexts.values():
        for _ in range(3):
            result = module.record_sample(settings, 10, 12, completed_paths=20,
                operation_runtime={'short_stroke': dict(average_seconds=.06,
                    count=20, samples=1, observations=20)})
            if not result.get('recorded'):
                raise AssertionError(result)
    return contexts


class CalibrationPlanningTests(unittest.TestCase):
    def test_real_pixel_fill_and_nested_hybrid_keep_every_lookup_with_one_database_read(self):
        for name, count, contexts, fills in (
                ('paint_pixel', 3, 1, 0), ('paint_fill', 3, 1, 3),
                ('gartic_hybrid_fill', 6, 3, 0)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory, \
                    closing(public_source()) as source, public_environment(directory):
                options = public_options(name)
                seeded = seed_public_contexts(source, options)
                original = source.tobytes(), dict(source.info), dict(options)
                files = {path: path.read_bytes() for path in Path(directory).glob('*.json')}
                with observed() as (calls, ensured, read, validated):
                    plan = DrawBot.make_plan(source, source.size, options)
                try:
                    self.assertEqual(len(calls), count)
                    self.assertEqual(len(seeded), contexts)
                    self.assertEqual(len({row['key'] for _options, row in calls}), contexts)
                    self.assertTrue(all(row['samples'] == 3 and row['ratio'] == 1.2
                                        for _options, row in calls))
                    self.assertEqual((ensured.call_count, read.call_count), (1, 1),
                        'The real planner must share its parsed database across distinct context lookups.')
                    self.assertEqual(validated.call_count, contexts)
                    self.assertGreater(plan['count'], 0)
                    self.assertEqual(len(plan['options'].get('fill_regions') or ()), fills)
                    self.assertEqual(bool(plan['options'].get('adaptive_hybrid_meta', {}).get('enabled')),
                                     name.startswith('gartic_hybrid'))
                    self.assertEqual((source.tobytes(), source.info, options), original)
                    self.assertEqual({path: path.read_bytes() for path in files}, files)
                finally:
                    close_plan(plan, source)


class CalibrationScopeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.path = self.directory / 'gartic-phone.json'
        self.options = dict(profile_key='gartic-phone', speed='Balanced', precision='Ultra',
            effective_paint_tool='Pencil', brush_px=1, custom_color_workflow='Calibrated palette',
            drawing_mode='Smart paths', render_preset='Manual', draw_quality='High likeness',
            render_style='Standard / Pixel', drawing_style='Auto')
        self.stack.enter_context(patch.object(timing, 'profile_timing_file',
            side_effect=lambda key: self.directory / (key + '.json')))
        self.stack.enter_context(patch.object(timing, 'FILE', self.directory / 'legacy.json'))
        self.stack.enter_context(patch.object(speed, 'SPEED_FILE', self.directory / 'speed.json'))

    def write(self, profiles, *, path=None, version=4):
        (path or self.path).write_text(json.dumps(dict(version=version, profiles=profiles)), encoding='utf-8')

    def row(self, ratio=1.2, samples=3):
        return dict(samples=samples, ratio_ema=ratio, mape_ema=.125,
                    operation_runtime_ema={'short_stroke': dict(average_seconds=.06, count=20)},
                    last_operation_counts={'native': {'steps': [1, 2, {'extra': 3}]}},
                    extension={'nested': [1, {'saved': True}]})

    def test_v4_v2_and_legacy_fallbacks_keep_all_context_dimensions_and_nested_isolation(self):
        variants = [dict(self.options), *[dict(self.options, **change) for change in (
            {'effective_paint_tool': 'Brush'}, {'brush_px': 9}, {'use_region_fill_engine': True},
            {'custom_color_workflow': 'Adaptive exact'}, {'drawing_mode': 'Dots'},
            {'render_preset': 'Fast'}, {'draw_quality': 'Pixel Accurate'},
            {'render_style': 'Adaptive Hybrid 4.0'}, {'drawing_style_resolved': 'Pixel Art'})]]
        profiles = {timing._key(options): self.row(1.0 + index * .1)
                    for index, options in enumerate(variants)}
        v2 = dict(self.options, brush_px=7)
        legacy = dict(self.options, precision='Normal', brush_px=12)
        profiles[timing._v2_key(v2)] = self.row(2.3)
        profiles[timing._legacy_key(legacy)] = self.row(2.7)
        self.write(profiles)
        all_options = [*variants, v2, legacy]
        expected = [timing.correction_for(options) for options in all_options]
        with timing.planning_calibration_scope(), observed() as (_calls, ensured, read, valid):
            actual = [timing.correction_for(options) for options in all_options]
            self.assertEqual(actual, expected)
            loaded = timing.load_profile(self.options)
            loaded['extension']['nested'][1]['saved'] = False
            loaded['operation_runtime_ema']['short_stroke']['average_seconds'] = 999.
            actual[0]['operation_counts']['native']['steps'][2]['extra'] = 999
            self.assertEqual(timing.load_profile(self.options), profiles[timing._key(self.options)])
            self.assertEqual(timing.correction_for(self.options), expected[0])
            self.assertEqual((ensured.call_count, read.call_count, valid.call_count),
                             (1, 1, len(profiles)))

    def test_non_scoped_public_readers_still_read_fresh_owned_nested_values(self):
        self.write({timing._key(self.options): self.row()})
        with observed() as (_calls, ensured, read, _valid):
            first = timing.load_profile(self.options)
            first['extension']['nested'][1]['saved'] = False
            self.write({timing._key(self.options): self.row(1.9)})
            second = timing.load_profile(self.options)
            third = timing.correction_for(self.options)
        self.assertEqual(first['ratio_ema'], 1.2)
        self.assertEqual(second['ratio_ema'], 1.9)
        self.assertTrue(second['extension']['nested'][1]['saved'])
        self.assertEqual(third['ratio'], 1.9)
        self.assertEqual((ensured.call_count, read.call_count), (3, 3))

    def test_one_bounded_primary_database_leaves_other_profiles_and_explicit_paths_fresh(self):
        self.write({timing._key(self.options): self.row()})
        other = dict(self.options, profile_key='skribbl')
        other_path = self.directory / 'skribbl.json'
        explicit = self.directory / 'explicit.json'
        self.write({timing._key(other): self.row(1.8)}, path=other_path)
        self.write({timing._key(self.options): self.row(2.1)}, path=explicit)
        with timing.planning_calibration_scope(), observed() as (_calls, ensured, read, _valid):
            self.assertEqual(timing.correction_for(self.options)['ratio'], 1.2)
            for other_ratio, explicit_ratio in ((1.8, 2.1), (1.9, 2.2)):
                self.assertEqual(timing.correction_for(other)['ratio'], other_ratio)
                self.assertEqual(timing.correction_for(self.options, path=explicit)['ratio'], explicit_ratio)
                self.write({timing._key(other): self.row(1.9)}, path=other_path)
                self.write({timing._key(self.options): self.row(2.2)}, path=explicit)
            self.assertEqual(timing.correction_for(self.options)['ratio'], 1.2)
        self.assertEqual((ensured.call_count, read.call_count), (5, 5))

    def test_nested_scope_borrows_until_outer_exit_and_next_operation_observes_replacement(self):
        self.write({timing._key(self.options): self.row()})
        with observed() as (_calls, ensured, read, _valid):
            with timing.planning_calibration_scope():
                first = timing.correction_for(self.options)
                self.write({timing._key(self.options): self.row(1.8)})
                with timing.planning_calibration_scope():
                    self.assertEqual(timing.correction_for(self.options), first)
                self.assertEqual(timing.correction_for(self.options), first)
            with timing.planning_calibration_scope():
                self.assertEqual(timing.correction_for(self.options)['ratio'], 1.8)
        self.assertEqual((ensured.call_count, read.call_count), (2, 2))

    def test_writers_and_reset_read_current_locked_state_inside_an_existing_read_scope(self):
        self.write({timing._key(self.options): self.row()})
        other = dict(self.options, brush_px=6)
        with timing.planning_calibration_scope():
            first = timing.correction_for(self.options)
            for expected in (4, 5):
                written = timing.record_sample(self.options, 10, 16, completed_paths=20)
                self.assertEqual(written['samples'], expected)
            self.assertTrue(timing.record_sample(other, 10, 11, completed_paths=20)['recorded'])
            self.assertEqual(timing.correction_for(self.options), first)
            self.assertTrue(timing.reset_profile(self.options)['reset'])
            self.assertEqual(timing.correction_for(self.options), first)
            self.assertEqual(set(timing.load_all(self.path)['profiles']), {timing._key(other)})
        with timing.planning_calibration_scope():
            self.assertFalse(timing.correction_for(self.options)['learned'])
            self.assertEqual(timing.correction_for(other)['samples'], 1)

    def test_reader_does_not_apply_the_writers_context_eviction_limit(self):
        variants = [dict(self.options, render_preset=f'saved-context-{index}')
                    for index in range(timing.MAX_CONTEXTS + 1)]
        self.write({timing._key(options): self.row(1.3) for options in variants})
        before = self.path.read_bytes()
        with timing.planning_calibration_scope(), observed() as (_calls, ensured, read, valid):
            for options in (variants[0], variants[-1], variants[timing.MAX_CONTEXTS // 2]):
                self.assertEqual(timing.correction_for(options)['ratio'], 1.3)
            self.assertEqual((ensured.call_count, read.call_count), (1, 1))
            self.assertEqual(valid.call_count, timing.MAX_CONTEXTS + 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_explicit_missing_path_cannot_suppress_default_legacy_migration(self):
        other = dict(self.options, profile_key='skribbl')
        self.write({timing._legacy_key(self.options): self.row(1.7),
                    timing._legacy_key(other): self.row(2.4)}, path=timing.FILE, version=1)
        legacy_bytes = timing.FILE.read_bytes()
        with timing.planning_calibration_scope():
            self.assertFalse(timing.correction_for(self.options, path=self.path)['learned'])
            self.assertFalse(self.path.exists())
            self.assertEqual(timing.correction_for(self.options)['ratio'], 1.7)
            self.assertTrue(self.path.exists())
            self.assertEqual(timing.correction_for(other)['ratio'], 2.4)
        self.assertEqual(timing.FILE.read_bytes(), legacy_bytes)
        self.assertEqual(set(timing.load_all(self.path)['profiles']), {timing._legacy_key(self.options)})
        self.assertEqual(set(timing.load_all(self.directory / 'skribbl.json')['profiles']),
                         {timing._legacy_key(other)})

    def test_missing_invalid_and_legacy_version_snapshots_retry_on_next_operation(self):
        for contents in (None, '{broken', '{"version":999,"profiles":{}}',
                         '{"version":4,"profiles":{"invalid":{"samples":true}}}'):
            with self.subTest(contents=contents):
                if contents is None:
                    self.path.unlink(missing_ok=True)
                else:
                    self.path.write_text(contents, encoding='utf-8')
                with timing.planning_calibration_scope(), observed() as (_calls, ensured, read, _valid):
                    first = timing.correction_for(self.options)
                    self.write({timing._v2_key(self.options): self.row(1.6)}, version=2)
                    self.assertEqual(timing.correction_for(self.options), first)
                    self.assertFalse(first['learned'])
                    self.assertEqual((ensured.call_count, read.call_count),
                                     (1, 0 if contents is None else 1))
                with timing.planning_calibration_scope():
                    self.assertEqual(timing.correction_for(self.options)['ratio'], 1.6)

    def test_temporarily_unreadable_database_recovers_only_on_the_next_operation(self):
        self.write({timing._key(self.options): self.row(1.8)})
        before = self.path.read_bytes()
        with timing.planning_calibration_scope():
            with patch.object(timing, 'read_json', side_effect=PermissionError('temporarily locked')) as read:
                first = timing.correction_for(self.options)
            self.assertEqual(read.call_count, 1)
            self.assertFalse(first['learned'])
            self.assertEqual(timing.correction_for(self.options), first)
        with timing.planning_calibration_scope(), observed() as (_calls, ensured, read, _valid):
            self.assertEqual(timing.correction_for(self.options)['ratio'], 1.8)
            self.assertEqual((ensured.call_count, read.call_count), (1, 1))
        self.assertEqual(self.path.read_bytes(), before)

    def test_two_threads_and_an_explicit_copied_context_do_not_share_observation_owners(self):
        self.write({timing._key(self.options): self.row()})
        results, errors = [], []
        def worker(context=None):
            def run():
                with timing.planning_calibration_scope():
                    results.append(timing.correction_for(self.options)['ratio'])
                    results.append(timing.correction_for(self.options)['ratio'])
            try:
                context.run(run) if context is not None else run()
            except BaseException as error:
                errors.append(error)
        with timing.planning_calibration_scope(), observed() as (_calls, ensured, read, _valid):
            self.assertEqual(timing.correction_for(self.options)['ratio'], 1.2)
            self.write({timing._key(self.options): self.row(1.9)})
            for context in (None, copy_context()):
                thread = threading.Thread(target=worker, args=(context,))
                thread.start(); thread.join(3)
                self.assertFalse(thread.is_alive())
            self.assertEqual(timing.correction_for(self.options)['ratio'], 1.2)
        self.assertFalse(errors, errors)
        self.assertEqual(results, [1.9] * 4)
        self.assertEqual((ensured.call_count, read.call_count), (3, 3))

    def test_failed_lookup_releases_the_shared_database_even_with_retained_traceback(self):
        class ObservedDatabase(dict):
            pass
        self.write({timing._key(self.options): self.row()})
        raw = timing._load_raw
        owners = []
        def loaded(*args, **kwargs):
            database = ObservedDatabase(raw(*args, **kwargs))
            owners.append(weakref.ref(database))
            return database
        retained = None
        with patch.object(timing, '_load_raw', side_effect=loaded):
            try:
                with timing.planning_calibration_scope():
                    self.assertTrue(timing.correction_for(self.options)['learned'])
                    with patch.object(timing, '_key', side_effect=InterruptedError('cancelled context lookup')):
                        timing.correction_for(self.options)
            except InterruptedError as error:
                retained = error
        self.assertIsNotNone(retained)
        self.assertTrue(owners)
        self.assertTrue(all(ref() is None for ref in owners),
                        'An exception frame must not retain the closed observation database.')
        with timing.planning_calibration_scope():
            self.assertTrue(timing.correction_for(self.options)['learned'])

    def test_failed_initial_read_propagates_and_next_operation_still_reads_fresh(self):
        self.write({timing._key(self.options): self.row()})
        for kind in (MemoryError, InterruptedError):
            with self.subTest(kind=kind), patch.object(timing, '_load_raw',
                    side_effect=kind('initial observation failed')):
                with self.assertRaisesRegex(kind, 'initial observation failed'):
                    with timing.planning_calibration_scope():
                        timing.correction_for(self.options)
            with timing.planning_calibration_scope():
                self.assertTrue(timing.correction_for(self.options)['learned'])

    def test_lazy_cancelled_public_operation_performs_no_calibration_io(self):
        with closing(public_source()) as source, public_environment(self.directory), \
                observed() as (_calls, ensured, read, _valid):
            with self.assertRaises(InterruptedError):
                DrawBot.make_plan(source, source.size, public_options('paint_pixel'), lambda: True)
        self.assertEqual((ensured.call_count, read.call_count), (0, 0))


if __name__ == '__main__':
    unittest.main()
