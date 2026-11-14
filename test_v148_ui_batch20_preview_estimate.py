"""The accepted preview presents the estimate its real worker already prepared."""
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import queue
import os
import json
import time
import unittest
import subprocess
import sys
import tempfile
import threading
from types import MethodType
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import DrawBot
import DrawTimeEstimate
import DrawTimeCalibration
import RealSpeedBudget
from ExecutionCostModel import ExecutionCostModel
from test_pixel_accurate_v1086 import opts
from test_v148_ui_batch16_plan_status import PlanStatusFixture


@contextmanager
def observe_estimates():
    """Observe the real numeric work, without replacing its results or model."""
    records = []
    active = threading.local()
    original_estimate = DrawTimeEstimate.estimate_from_plan
    original_sequence = ExecutionCostModel.sequence_cost
    original_path = ExecutionCostModel.path_cost

    def estimate(plan):
        record = {'thread': threading.get_ident(), 'sequence_calls': 0,
                  'path_calls': 0, 'rows': 0}
        records.append(record)
        active.record = record
        try:
            result = original_estimate(plan)
            record['metadata'] = deepcopy(result)
            return result
        finally:
            active.record = None

    def sequence(model, rows, **kwargs):
        record = getattr(active, 'record', None)
        if record is not None:
            record['sequence_calls'] += 1
            record['rows'] += len(rows)
        return original_sequence(model, rows, **kwargs)

    def path(model, points, **kwargs):
        record = getattr(active, 'record', None)
        if record is not None:
            record['path_calls'] += 1
        return original_path(model, points, **kwargs)

    with patch.object(DrawTimeEstimate, 'estimate_from_plan', estimate), \
            patch.object(ExecutionCostModel, 'sequence_cost', sequence), \
            patch.object(ExecutionCostModel, 'path_cost', path):
        yield records


def run_preview_process(command, *, timeout=180, env=None, ready_file=None,
                        startup_timeout=60):
    """Reap a stuck child; optionally budget startup separately from its work."""
    with subprocess.Popen(command, cwd=Path(__file__).resolve().parent,
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True) as process:
        try:
            if ready_file is not None:
                deadline = time.monotonic() + startup_timeout
                while not Path(ready_file).exists():
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        raise AssertionError('Preview child exited before ready: ' + stdout + stderr)
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(command, startup_timeout)
                    time.sleep(.01)
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException as exc:
            process.kill()
            process.communicate()
            if isinstance(exc, subprocess.TimeoutExpired):
                raise AssertionError('Isolated preview fixture exceeded its process bound') from exc
            raise
        if process.returncode:
            raise AssertionError(stdout + stderr)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run_preview_case(test_id):
    """Emit machine-readable skip status without hiding child failures."""
    suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print('IDB_PREVIEW_RESULT=' + json.dumps({'skipped': [reason for _, reason in result.skipped]}))
    raise SystemExit(0 if result.wasSuccessful() else 1)


class PreviewEstimateFixture(PlanStatusFixture):
    def run(self, result=None):
        test_id = self.id()
        if test_id.startswith('__main__.'):
            test_id = Path(sys.argv[0]).stem + test_id[len('__main__'):]
        if os.environ.get('IDB_ISOLATED_PREVIEW_TEST') == test_id:
            return super().run(result)
        # No fixture setup or Tcl allocation takes place in this parent. Even
        # an uncooperative worker dies with its child before failure is reported.
        def isolated():
            environment = dict(os.environ, IDB_ISOLATED_PREVIEW_TEST=test_id)
            child = run_preview_process([
                sys.executable, '-X', 'faulthandler', '-c',
                'import sys; from test_v148_ui_batch20_preview_estimate import run_preview_case; '
                'run_preview_case(sys.argv[1])', test_id], env=environment)
            reports = [line.partition('=')[2] for line in child.stdout.splitlines()
                       if line.startswith('IDB_PREVIEW_RESULT=')]
            self.assertEqual(len(reports), 1, 'Child did not report its test outcome')
            skipped = json.loads(reports[0])['skipped']
            if skipped:
                raise unittest.SkipTest('; '.join(skipped))
        from unittest import FunctionTestCase
        proxy = FunctionTestCase(isolated, description=test_id)
        proxy.id = lambda: test_id
        return proxy.run(result)

    def setUp(self):
        super().setUp()
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('DrawTimeCalibration.profile_timing_file',
                                       side_effect=lambda key: self.directory / (key + '.json')))
        self.stack.enter_context(patch('DrawTimeCalibration.FILE', self.directory / 'legacy.json'))
        read_speed = RealSpeedBudget.load_profile
        self.stack.enter_context(patch('RealSpeedBudget.load_profile',
                                       side_effect=lambda key, **kwargs:
                                           read_speed(key, self.directory / 'speed.json', **kwargs)))
        self.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_schedule_poll'))

    def app(self, area=(84, 64)):
        app = super().app()
        app.events = queue.Queue()
        app.preview_mode.set('Auto full')
        app.needs_plan = False
        app.preview_after = None
        app.draw_quality.set('Pixel Accurate')
        app.refresh_runtime_safety_ui = Mock()
        app.refresh_correction_review_ui = Mock()
        app.corners = [(10, 20), (10 + area[0], 20 + area[1])]
        for name in ('begin_worker', '_handle_event', 'update_plan'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        app.options = lambda: opts(
            profile_name='Microsoft Paint', profile_key='microsoft-paint',
            paint_current_color=False, draw_quality='Pixel Accurate',
            render_preset='Manual', unlimited_time=True, time_budget_mode='Unlimited',
            planning_resolution='Standard', cpu_workers='1', detail_zoom='Off',
            _execution_cost_calibration_override={})
        source = Image.new('RGBA', (48, 36), 'white')
        draw = ImageDraw.Draw(source)
        draw.rectangle((5, 4, 24, 25), fill=(29, 66, 173, 255))
        draw.ellipse((23, 12, 43, 32), fill=(214, 49, 31, 255))
        self.images.append(source)
        app.original = source
        return app

    def wait_for_preview_worker(self, app, *, worker_timeout=60, stop_timeout=30):
        # Projected geometry plus instrumentation can take over ten seconds on
        # Windows CI. This is a completion bound, not a performance assertion.
        self.assertIsInstance(app.worker, threading.Thread)
        app.worker.join(timeout=worker_timeout)
        if app.worker.is_alive():
            # Do not let a failed subtest unwind planner patches or start the
            # next worker while this one still borrows its Tcl-backed fixture.
            app.stop.set()
            app.paused.clear()
            app.worker.join(timeout=stop_timeout)
            if app.worker.is_alive():
                # Never unwind mocks or close images while the worker borrows
                # them. The isolated parent deadline terminates this process.
                app.worker.join()
            while not app.events.empty():
                kind, payload = app.events.get_nowait()
                if kind == 'planned':
                    self.plans.append(payload)
            self.fail('Actual preview worker exceeded its fixture bound')

    def build(self, app, *, full_detail=False, worker_timeout=60):
        app.update_plan(user_initiated=True, full_detail=full_detail)
        self.wait_for_preview_worker(app, worker_timeout=worker_timeout)
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait())
        self.assertEqual([kind for kind, _ in events], ['planned', 'done'])
        plan = events[0][1]
        self.plans.append(plan)
        self.assertGreater(plan['count'], 0)
        self.assertTrue(plan['draw_time_estimate']['sequence_model_used'])
        return plan, events[1]

    def adopt(self, app, plan, done):
        app.events.put(('planned', plan))
        app.events.put(done)
        DrawBot.DrawBotApp.poll(app)
        self.assertIs(app.plan, plan)
        self.assertNotIn('UI event error contained:', app.status.get())
        self.assertEqual(app.draw_time_text.get(), DrawTimeEstimate.status_line(plan))


class PreviewEstimateHandoffTests(PreviewEstimateFixture):
    def test_real_preview_worker_hands_native_and_projected_estimate_to_ui_without_rescanning(self):
        for area, full_detail in (((84, 64), False), ((1100, 600), False),
                                  ((84, 64), True)):
            with self.subTest(area=area, full_detail=full_detail):
                app = self.app(area)
                with observe_estimates() as records:
                    plan, done = self.build(app, full_detail=full_detail)
                    worker_records = deepcopy(records)
                    prepared = deepcopy(plan['draw_time_estimate'])
                    self.assertTrue(worker_records)
                    self.assertTrue(all(row['thread'] != threading.get_ident()
                                        for row in worker_records))
                    self.assertGreater(sum(row['path_calls'] for row in worker_records), 0)
                    self.adopt(app, plan, done)
                    self.assertEqual(plan['draw_time_estimate'], prepared)
                    self.assertEqual(records, worker_records,
                                     'UI adoption must not repeat the completed geometry/model scan')
                self.assertEqual(prepared['is_projection'], area == (1100, 600))

    def test_legacy_plan_adoption_still_recomputes_after_target_geometry_changes(self):
        app = self.app()
        plan = DrawBot.make_plan(app.original, (42, 32), app.options())
        self.plans.append(plan)
        previous = deepcopy(plan['draw_time_estimate'])
        plan.update(preview_generation=app.preview_generation,
                    preview_area=(42, 32), target_area=(840, 640))
        expected = DrawTimeEstimate.estimate_from_plan(plan)
        self.assertNotEqual(previous, expected)
        with observe_estimates() as records:
            DrawBot.DrawBotApp._handle_event(app, 'planned', plan)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['thread'], threading.get_ident())
        self.assertEqual(plan['draw_time_estimate'], expected)
        self.assertTrue(plan['draw_time_estimate']['is_projection'])

    def test_handoff_is_consumed_once_and_later_geometry_change_gets_fresh_estimate(self):
        app = self.app()
        plan, done = self.build(app)
        self.adopt(app, plan, done)
        before = deepcopy(plan['draw_time_estimate'])
        plan['target_area'] = (840, 640)
        expected = DrawTimeEstimate.estimate_from_plan(plan)
        with observe_estimates() as records:
            DrawBot.DrawBotApp._handle_event(app, 'planned', plan)
        self.assertEqual(len(records), 1)
        self.assertNotEqual(before, expected)
        self.assertEqual(plan['draw_time_estimate'], expected)

    def test_replaced_metadata_falls_back_to_current_plan_calculation(self):
        app = self.app()
        plan, done = self.build(app)
        expected = deepcopy(plan['draw_time_estimate'])
        plan['draw_time_estimate'] = {'projected_seconds': 0}
        with observe_estimates() as records:
            self.adopt(app, plan, done)
        self.assertEqual(len(records), 1)
        self.assertEqual(plan['draw_time_estimate'], expected)

    def test_failed_final_worker_preparation_retains_the_fresh_ui_fallback(self):
        app = self.app()
        real_attach = DrawTimeEstimate.attach_draw_time_estimate
        calls = []
        def attach(plan):
            calls.append(threading.get_ident())
            if len(calls) == 2:
                raise ValueError('final estimate preparation unavailable')
            return real_attach(plan)
        with patch.object(DrawTimeEstimate, 'attach_draw_time_estimate', attach):
            plan, done = self.build(app)
            self.adopt(app, plan, done)
        self.assertEqual(len(calls), 3)
        self.assertNotEqual(calls[0], threading.get_ident())
        self.assertEqual(calls[-1], threading.get_ident())
        self.assertEqual(plan['draw_time_estimate'], DrawTimeEstimate.estimate_from_plan(plan))

    def test_stale_and_stopped_results_are_released_without_recalculating_or_adopting(self):
        for reason in ('generation', 'stop'):
            with self.subTest(reason=reason):
                app = self.app()
                plan, _done = self.build(app)
                source_pixels = app.original.tobytes()
                if reason == 'generation':
                    app.preview_generation += 1
                else:
                    DrawBot.DrawBotApp._request_stop(app)
                with observe_estimates() as records:
                    DrawBot.DrawBotApp._handle_event(app, 'planned', plan)
                self.assertFalse(records)
                self.assertIsNone(app.plan)
                self.assertEqual(app.original.tobytes(), source_pixels)
                with self.assertRaises(ValueError):
                    plan['preview'].getpixel((0, 0))

    def test_next_real_preview_reads_new_calibration_without_mutating_queued_estimate(self):
        app = self.app()
        plan, done = self.build(app)
        prepared = deepcopy(plan['draw_time_estimate'])
        self.assertEqual(prepared['measured_samples'], 0)
        for _ in range(3):
            recorded = DrawTimeCalibration.record_sample(plan['options'], 10, 20,
                                                         completed_paths=plan['count'])
            self.assertTrue(recorded['recorded'])
        with observe_estimates() as records:
            self.adopt(app, plan, done)
        self.assertFalse(records)
        self.assertEqual(plan['draw_time_estimate'], prepared)
        newer, newer_done = self.build(app)
        self.adopt(app, newer, newer_done)
        self.assertEqual(newer['draw_time_estimate']['measured_samples'], 3)
        self.assertGreater(newer['draw_time_estimate']['projected_seconds'],
                           prepared['projected_seconds'])


if __name__ == '__main__':
    import unittest
    unittest.main()
