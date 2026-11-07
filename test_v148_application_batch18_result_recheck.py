"""The real review action re-scores a visible target without sending input."""
import ast
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json
import importlib
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import StudioUI
import CorrectionHistory
from CorrectionHistory import load_correction_history as real_history_loader
from DrawBot import DrawBotApp
from ScreenGuard import GuardedMouse
from WindowsMouse import WindowsMouse
import test_v148_application_batch17_runtime_report as execution_fixture


class RawNativeMouse(WindowsMouse):
    """Replace the native input boundary, retaining the shipped backend API."""
    __init__ = execution_fixture.NativeMouse.__init__
    get_position = execution_fixture.NativeMouse.get_position
    arm_input = execution_fixture.NativeMouse.arm_input
    disarm_input = execution_fixture.NativeMouse.disarm_input
    move = execution_fixture.NativeMouse.move
    press = execution_fixture.NativeMouse.press
    release = execution_fixture.NativeMouse.release
    click = execution_fixture.NativeMouse.click


class Surface:
    def __init__(self, text='', command=None, **options):
        self.text, self.command, self.options = text, command, options

    def pack(self, *args, **kwargs):
        return None

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def invoke(self):
        return self.command()


class DesktopRoot(execution_fixture.worker_fixtures.ScheduledRoot):
    """Replace only Tk's desktop boundary; ScreenTaskWindow runs unchanged."""
    def __init__(self):
        super().__init__()
        self.mode = 'normal'
        self.transitions = []

    def state(self, value=None):
        if value is not None:
            self.mode = value
        return self.mode

    def iconify(self):
        self.mode = 'iconic'
        self.transitions.append('hide')

    def deiconify(self):
        self.mode = 'normal'
        self.transitions.append('restore')

    def withdraw(self):
        self.mode = 'withdrawn'

    def update_idletasks(self):
        pass

    def winfo_exists(self):
        return True

    def lift(self):
        pass


class DesktopMonitor(execution_fixture.NativeMonitor):
    def __init__(self):
        self.rect = self.client = (0, 0, 300, 250)
        self.scaling = 96
        self.occluded = False
        self.activations = 0
        self.probes = []

    def rectangle(self, handle):
        return self.rect

    def client_rectangle(self, handle):
        return self.client

    def dpi(self, handle):
        return self.scaling

    def activate(self, target):
        self.activations += 1
        return True

    def verify(self, target, point):
        self.probes.append((target, point))
        if self.occluded:
            raise InterruptedError('The target is covered by another window.')


def review_buttons(app):
    """Execute the actual review-card binding statements with native UI replaced."""
    tree = ast.parse(Path(StudioUI.__file__).read_text(encoding='utf-8'))
    build = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == 'build_ui')
    start = next(index for index, node in enumerate(build.body)
                 if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                     and target.id == 'review_actions' for target in node.targets))
    end = next(index for index in range(start + 1, len(build.body))
               if isinstance(build.body[index], ast.Expr)
               and isinstance(build.body[index].value, ast.Call)
               and isinstance(build.body[index].value.func, ast.Name)
               and build.body[index].value.func.id == 'setting_row')
    buttons = {}

    def button(parent, text, command, **options):
        buttons[text] = Surface(text, command, **options)
        return buttons[text]

    namespace = dict(a=app, review_card=Surface(), frame=lambda *a, **k: Surface(),
                     btn=button, tooltip=lambda *a, **k: None)
    exec(compile(ast.Module(body=build.body[start:end], type_ignores=[]),
                 StudioUI.__file__, 'exec'), namespace)
    return buttons


class ResultRecheckApplicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = execution_fixture.RuntimeReportApplicationTests(
            'test_startup_still_loads_saved_history')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app = self.fixture.app
        self.plan = self.fixture.prepare_retry()
        self.app.mouse = RawNativeMouse()
        self.app.root = DesktopRoot()
        self.monitor = DesktopMonitor()
        self.fixture.stack.enter_context(patch('ScreenGuard.WindowMonitor', return_value=self.monitor))
        self.history_path = self.fixture.directory / 'history.json'
        self.fixture.stack.enter_context(patch('CorrectionHistory.profile_correction_history_file',
                                              return_value=self.history_path))
        self.fixture.stack.enter_context(patch('CorrectionHistory.load_correction_history',
                                              wraps=real_history_loader))
        self.snapshots = []
        self.capture_threads = []

        def grab(box):
            self.assertEqual(self.app.root.state(), 'iconic')
            result = self.fixture.grab(box)
            self.snapshots.append(result)
            self.capture_threads.append(threading.get_ident())
            return result
        self.fixture.capture.side_effect = grab

    def start_recheck(self):
        buttons = review_buttons(self.app)
        self.assertTrue(buttons['Re-check result'].invoke(), self.app.status.get())
        self.assertEqual(self.app.activity, 'result-recheck')
        return self.app.worker, self.app.result_recheck_request

    def finish_recheck(self):
        worker, request = self.start_recheck()
        worker.run()
        self.fixture.drain()
        return request

    def assert_no_input(self):
        self.assertEqual(self.app.mouse.actions, [])
        self.assertFalse(self.app.mouse.armed)
        self.assertEqual(self.monitor.activations, 0)
        self.fixture.executor.assert_not_called()

    def assert_capture_closed(self):
        self.assertTrue(self.snapshots)
        for image in self.snapshots:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))

    def test_default_raw_backend_uses_guarded_capture_capability_for_retry(self):
        self.assertIsInstance(self.app.mouse, WindowsMouse)
        self.assertFalse(hasattr(self.app.mouse, 'snapshot_canvas'))
        state = self.app.refresh_correction_review_ui()
        self.assertTrue(state['actions']['retry_correction_only']['enabled'], state)
        self.app.retry_post_draw_correction()
        self.assertIsNotNone(self.app.worker, self.app.status.get())
        self.app.worker.run()
        self.fixture.drain()
        self.assertGreater(self.fixture.capture.call_count, 0)

    def test_advertised_recheck_has_an_actual_review_card_action(self):
        with patch('DrawBot.messagebox.showinfo') as dialog:
            self.app.show_correction_review()
        self.assertIn('Re-check result', dialog.call_args.args[1])
        self.fixture.capture.assert_not_called()
        buttons = review_buttons(self.app)
        self.assertIn('Re-check result', buttons,
                      'Review advertises a result re-check, but its real card has no action.')

    def test_guarded_snapshot_does_not_require_or_arm_a_raw_capture_method(self):
        guarded = GuardedMouse(self.app.mouse, execution_fixture.NativeMonitor(), self.app.target_window)
        self.app.root.iconify()
        snapshot = guarded.snapshot_canvas(self.app.area())
        try:
            self.assertIsInstance(snapshot, Image.Image)
            self.assertEqual(snapshot.getpixel((0, 0)), (0, 0, 0))
            self.assertEqual(snapshot.size, (64, 64))
            self.assertEqual(self.app.mouse.actions, [])
            self.assertFalse(self.app.mouse.armed)
        finally:
            snapshot.close()

    def test_current_observation_uses_real_scorer_and_distinct_history_without_drawing(self):
        options = self.plan['options']
        options['post_draw_correction_meta'] = {'enabled': True, 'safe': True, 'executed_paths': 4,
            'correction_paths': 4, 'post_correction_trust': 'high',
            'post_correction_visual_accuracy_percent': 17., 'post_correction_actual_coverage_percent': 18.}
        options['post_draw_before_correction_accuracy_meta'] = {'visual_accuracy_percent': 12.}
        report = deepcopy(options['runtime_safety_report'])
        self.app.refresh_runtime_safety_ui()
        safety_text = self.app.runtime_safety_summary.get()
        from ResultRecheck import score_final_canvas_snapshot as actual_score
        scored = []
        def score(**kwargs):
            metrics = actual_score(**kwargs)
            scored.append(metrics)
            return metrics
        with patch('ResultRecheck.score_final_canvas_snapshot', side_effect=score):
            worker, request = self.start_recheck()
            worker.run()
        # The producer cannot change the queued result after publication.
        scored[0]['visual_accuracy_percent'] = 0.
        self.fixture.drain()
        fresh = options['post_draw_accuracy_meta']
        self.assertTrue(fresh['available'], fresh)
        self.assertEqual(fresh['visual_accuracy_percent'], 100.)
        self.assertEqual(fresh['observation'], 'read-only result re-check')
        self.assertEqual(self.app.correction_review_meta['real_result']['visual_accuracy_percent'], 100.)
        self.assertNotIn('post_draw_correction_meta', options)
        self.assertNotIn('post_draw_before_correction_accuracy_meta', options)
        self.assertEqual(options['runtime_safety_report'], report)
        self.assertEqual(self.app.runtime_safety_summary.get(), safety_text)
        published = next(value for kind, value in self.app.published if kind == 'result_recheck_complete')
        published.metrics['visual_accuracy_percent'] = 1.
        published.history['latest']['after_visual_accuracy_percent'] = 1.
        self.assertEqual(options['post_draw_accuracy_meta']['visual_accuracy_percent'], 100.)
        self.assertEqual(options['correction_history_meta']['latest']['after_visual_accuracy_percent'], 100.)
        self.assertEqual(self.app.correction_history_meta['latest']['after_visual_accuracy_percent'], 100.)
        for module, function in (('RealSpeedBudget', 'record_runtime_sample'),
                ('DrawTimeEstimate', 'record_completed_draw'),
                ('CompletedDrawingAnalysis', 'record_completed_drawing'),
                ('AutoTunerFeedback', 'record_completed_feedback')):
            getattr(importlib.import_module(module), function).assert_not_called()
        self.assertEqual(self.app.root.transitions, ['hide', 'restore'])
        self.assertEqual(len(self.monitor.probes), 10)
        self.assertIsNone(self.app.activity)
        self.assertIsNone(self.app.result_recheck_request)
        self.assertIsNone(request.plan)
        self.assertIsNone(request.source)
        self.assertIs(self.app.plan, self.plan)
        self.app.original.getpixel((0, 0))
        options['_accuracy_original_source'].getpixel((0, 0))
        self.plan['preview'].getpixel((0, 0))
        self.assert_capture_closed()
        self.assert_no_input()
        entry = json.loads(self.history_path.read_text())['entries'][0]
        self.assertEqual(entry['operation'], 'read-only-verification')
        self.assertEqual(entry['state'], 'rechecked')
        self.assertEqual((entry['before'], entry['delta'], entry['correction']), ({}, {}, {}))
        self.assertEqual(entry['after']['visual_accuracy_percent'], 100.)
        self.assertNotIn('actual_seconds', entry)
        self.assertNotIn('planned_paths', entry)
        self.assertFalse(CorrectionHistory.contains_image_data(entry))
        history = real_history_loader(options)
        self.assertIsNone(history['summary']['average_visual_delta'])
        with patch('DrawBot.messagebox.showinfo') as dialog:
            self.app.show_correction_history()
        self.assertIn('read-only observation', dialog.call_args.args[1])
        self.assertIn('Visual 100.0%', dialog.call_args.args[1])

    def test_read_only_recheck_needs_no_unlock_or_expired_native_preflight(self):
        self.app.full_draw_armed_until = 0.
        self.app.target_lock_passed = self.app.safety_preflight_passed = False
        self.app.stop.set()  # An explicit new action may follow an earlier Stop.
        state = self.app.refresh_correction_review_ui()
        self.assertFalse(state['actions']['retry_correction_only']['enabled'])
        self.assertTrue(state['actions']['rerun_result_verification']['enabled'])
        self.assertFalse(state['actions']['rerun_result_verification']['requires_safety_chain'])
        self.finish_recheck()
        self.assertFalse(self.app.stop.is_set())
        self.assertTrue(self.plan['options']['post_draw_accuracy_meta']['available'])
        self.assert_no_input()

    def test_actual_background_worker_reads_no_tk_and_restores_window_on_ui_thread(self):
        main_thread = threading.get_ident()
        get_profile = self.app.game.get
        def ui_get():
            self.assertEqual(threading.get_ident(), main_thread)
            return get_profile()
        self.app.game.get = ui_get
        with patch('DrawBot.threading.Thread', execution_fixture.worker_fixtures.REAL_THREAD):
            worker, request = self.start_recheck()
            worker.join(3.)
            self.assertFalse(worker.is_alive())
        self.assertEqual(self.app.root.transitions, ['hide'])
        self.fixture.drain()
        self.assertEqual(self.app.root.transitions, ['hide', 'restore'])
        self.assertEqual(len(self.capture_threads), 1)
        self.assertNotEqual(self.capture_threads[0], main_thread)
        self.assertIsNone(request.plan)
        self.assert_no_input()

    def test_stop_at_task_countdown_capture_and_scorer_boundaries_discards_observation(self):
        import SafeCanvasSnapshotScoring
        original_evaluate = SafeCanvasSnapshotScoring.evaluate_preview
        transaction = CorrectionHistory.file_transaction
        old = deepcopy(self.plan['options']['post_draw_accuracy_meta'])
        for boundary in ('before-task', 'countdown', 'capture', 'scorer', 'history'):
            with self.subTest(boundary=boundary), ExitStack() as local:
                self.app.stop.clear()
                if boundary == 'countdown':
                    def wait(seconds):
                        if seconds == 1:
                            self.app._request_stop()
                        return self.app.stop.is_set()
                    local.enter_context(patch.object(self.app.stop, 'wait', side_effect=wait))
                elif boundary == 'capture':
                    grab = self.fixture.capture.side_effect
                    def stopped_capture(box):
                        image = grab(box)
                        self.app._request_stop()
                        return image
                    local.enter_context(patch('ScreenGuard._grab_rgb', side_effect=stopped_capture))
                elif boundary == 'scorer':
                    def stopped_evaluation(*args, **kwargs):
                        self.app._request_stop()
                        return original_evaluate(*args, **kwargs)
                    local.enter_context(patch('SafeCanvasSnapshotScoring.evaluate_preview', side_effect=stopped_evaluation))
                elif boundary == 'history':
                    @contextmanager
                    def stopped_storage(path):
                        with transaction(path):
                            self.app._request_stop()
                            yield
                    local.enter_context(patch('CorrectionHistory.file_transaction', stopped_storage))
                worker, request = self.start_recheck()
                if boundary == 'before-task':
                    self.app._request_stop()
                worker.run()
                self.fixture.drain()
                self.assertTrue(request.cancelled.is_set())
                self.assertIsNone(request.plan)
                self.assertIsNone(self.app.result_recheck_request)
                self.assertEqual(self.app.status.get(), 'Stopped.')
                self.assertEqual(self.plan['options']['post_draw_accuracy_meta'], old)
                self.assertFalse(self.history_path.exists())
                self.assertEqual(self.app.root.state(), 'normal')
        self.assert_capture_closed()
        self.assert_no_input()

    def test_queued_result_and_status_cannot_survive_stop_then_global_signal_reset(self):
        old = deepcopy(self.plan['options']['post_draw_accuracy_meta'])
        worker, request = self.start_recheck()
        worker.run()
        self.assertTrue(self.history_path.exists())  # The observation already committed.
        self.app._request_stop()
        self.app.stop.clear()
        self.app.status.set('A later explicit action owns this status.')
        self.fixture.drain()
        self.assertEqual(self.app.status.get(), 'A later explicit action owns this status.')
        self.assertEqual(self.plan['options']['post_draw_accuracy_meta'], old)
        self.assertIsNone(request.plan)
        self.assertIsNone(self.app.result_recheck_request)
        self.assertEqual(len(json.loads(self.history_path.read_text())['entries']), 1)
        self.assert_no_input()

    def test_late_result_rejects_replaced_plan_source_profile_target_area_client_or_dpi(self):
        old = deepcopy(self.plan['options']['post_draw_accuracy_meta'])
        for field, replacement in (('plan', {}), ('original', object()),
                ('_active_profile_name', 'Gartic Phone'), ('target_window', (2, (0, 0, 300, 250))),
                ('corners', [(101, 100), (165, 164)]), ('target_client_rect', (1, 0, 301, 250)),
                ('target_dpi', 120), ('profile_change_after', 'profile-pending')):
            with self.subTest(field=field):
                worker, request = self.start_recheck()
                worker.run()
                original = getattr(self.app, field)
                setattr(self.app, field, replacement)
                self.fixture.drain()
                setattr(self.app, field, original)
                self.assertEqual(self.plan['options']['post_draw_accuracy_meta'], old)
                self.assertIsNone(request.plan)
                self.assertIsNone(self.app.result_recheck_request)
        self.assert_no_input()

    def test_clear_and_shutdown_revoke_the_active_request_and_drop_queued_result(self):
        for operation in ('clear', 'close'):
            with self.subTest(operation=operation), ExitStack() as local:
                self.app.closing = False
                self.app.plan = self.plan
                old = deepcopy(self.plan['options']['post_draw_accuracy_meta'])
                worker, request = self.start_recheck()
                worker.run()
                if operation == 'clear':
                    local.enter_context(patch('SessionRecovery.clear_snapshot'))
                    for name in ('STATE_FILE', 'RENDER_FILE', 'IMAGE_FILE'):
                        local.enter_context(patch('SessionRecovery.' + name,
                                                  self.fixture.directory / ('absent-' + name)))
                    self.app.clear_cached_drawing()
                    self.fixture.drain()
                    self.app._finish_clear_drawing()
                    self.assertIsNone(self.app.plan)
                    self.assertIsNone(self.app.pending_clear_drawing)
                else:
                    self.app.close()
                    self.fixture.drain()
                    self.assertTrue(self.app.closing)
                self.assertTrue(request.cancelled.is_set())
                self.assertIsNone(request.plan)
                self.assertEqual(self.plan['options']['post_draw_accuracy_meta'], old)
        self.assert_no_input()

    def test_old_done_or_result_cannot_finish_a_new_request_of_the_same_activity(self):
        first, old_request = self.start_recheck()
        first.run()
        old_events = list(self.app.published)
        self.fixture.drain()
        second, current = self.start_recheck()
        for event in old_events:
            if event[0].startswith('result_recheck') or event[0] == 'done':
                self.app._handle_event(*event)
        self.assertIs(self.app.result_recheck_request, current)
        self.assertIs(self.app.worker, second)
        self.assertEqual(self.app.activity, 'result-recheck')
        second.run()
        self.fixture.drain()
        self.assertIsNone(current.plan)
        self.assert_no_input()

    def test_wrong_visibility_or_changed_window_geometry_is_fresh_unavailable_evidence(self):
        for field, bad in (('occluded', True), ('rect', (1, 0, 301, 250)),
                           ('client', (1, 0, 300, 250)), ('scaling', 120)):
            with self.subTest(field=field):
                original = getattr(self.monitor, field)
                setattr(self.monitor, field, bad)
                before = self.fixture.capture.call_count
                self.finish_recheck()
                setattr(self.monitor, field, original)
                fresh = self.plan['options']['post_draw_accuracy_meta']
                self.assertFalse(fresh['available'], fresh)
                self.assertNotIn('visual_accuracy_percent', fresh)
                self.assertEqual(self.app.correction_review_meta['state'], 'verification_unavailable')
                self.assertEqual(self.fixture.capture.call_count, before)
        self.assert_no_input()

    def test_geometry_change_after_capture_closes_image_and_does_not_score_wrong_target(self):
        grab = self.fixture.capture.side_effect
        def changed(box):
            image = grab(box)
            self.monitor.scaling = 120
            return image
        self.fixture.capture.side_effect = changed
        self.finish_recheck()
        self.assertFalse(self.plan['options']['post_draw_accuracy_meta']['available'])
        self.assert_capture_closed()
        self.assert_no_input()

    def test_scoring_failure_releases_owned_images_even_with_retained_traceback(self):
        owned, errors = [], []
        original_close = Image.Image.close
        def close(image):
            owned.append(image)
            return original_close(image)
        def broken_evaluation(*args, **kwargs):
            try:
                raise RuntimeError('scoring boundary failure')
            except RuntimeError as error:
                errors.append(error)
                raise
        with patch('SafeCanvasSnapshotScoring.evaluate_preview', side_effect=broken_evaluation), \
                patch.object(Image.Image, 'close', close):
            self.finish_recheck()
        self.assertTrue(errors[0].__traceback__)
        self.assertGreaterEqual(len({id(image) for image in owned}), 4)
        for image in owned:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))
        fresh = self.plan['options']['post_draw_accuracy_meta']
        self.assertFalse(fresh['available'])
        self.assertIn('scoring boundary failure', fresh['reason'])
        self.app.original.getpixel((0, 0))
        self.plan['preview'].getpixel((0, 0))
        self.assert_no_input()

    def test_history_write_failure_preserves_fresh_result_and_reports_storage_failure(self):
        with patch('CorrectionHistory.atomic_write_text', side_effect=PermissionError('history is read-only')):
            self.finish_recheck()
        self.assertTrue(self.plan['options']['post_draw_accuracy_meta']['available'])
        self.assertEqual(self.plan['options']['post_draw_accuracy_meta']['visual_accuracy_percent'], 100.)
        self.assertIn('history is read-only', self.app.status.get())
        self.assertFalse(self.history_path.exists())
        self.assert_no_input()

    def test_analysis_deadline_and_comparison_cap_close_capture_without_old_success(self):
        from ResultRecheck import recheck_result as actual_recheck
        now = [0.]
        grab = self.fixture.capture.side_effect
        def slow_capture(box):
            image = grab(box)
            now[0] = 16.
            return image
        self.fixture.capture.side_effect = slow_capture
        with patch('DrawBot.recheck_result', side_effect=lambda *a, **k:
                   actual_recheck(*a, **k, clock=lambda: now[0])):
            self.finish_recheck()
        result = self.plan['options']['post_draw_accuracy_meta']
        self.assertFalse(result['available'])
        self.assertIn('bounded analysis time', result['reason'])
        self.assert_capture_closed()
        before = self.fixture.capture.call_count
        large = Image.new('RGB', (2048, 2048), 'black')
        self.addCleanup(large.close)
        previous = self.plan['preview']
        self.plan['preview'] = large
        try:
            self.finish_recheck()
        finally:
            self.plan['preview'] = previous
        result = self.plan['options']['post_draw_accuracy_meta']
        self.assertFalse(result['available'])
        self.assertIn('bounded analysis size', result['reason'])
        self.assertEqual(self.fixture.capture.call_count, before)
        self.assert_no_input()

    def test_monitor_and_thread_stop_handoffs_or_start_failure_leave_no_request_or_capture(self):
        for stage in ('monitor-stop', 'thread-stop', 'thread-failure'):
            with self.subTest(stage=stage), ExitStack() as local:
                self.app.stop.clear()
                if stage == 'monitor-stop':
                    local.enter_context(patch('ScreenGuard.WindowMonitor',
                        side_effect=lambda: self.app._request_stop() or self.monitor))
                else:
                    def thread(**kwargs):
                        if stage == 'thread-failure':
                            raise RuntimeError('native thread constructor failed')
                        result = execution_fixture.worker_fixtures.DeferredThread(**kwargs)
                        self.app._request_stop()
                        return result
                    local.enter_context(patch('DrawBot.threading.Thread', side_effect=thread))
                self.app.recheck_drawing_result()
                if self.app.worker is not None:
                    self.app.worker.run()
                self.fixture.drain()
                self.assertIsNone(self.app.result_recheck_request)
                self.assertIsNone(self.app.activity)
                self.assertEqual(self.app.root.state(), 'normal')
                self.fixture.capture.assert_not_called()
        self.assert_no_input()

    def test_pending_profile_or_clear_does_not_hide_or_construct_native_monitor(self):
        for field, value in (('profile_change_after', 'pending'),
                             ('profile_change_in_progress', True), ('pending_clear_drawing', False)):
            with self.subTest(field=field), patch('ScreenGuard.WindowMonitor') as monitor:
                old = getattr(self.app, field)
                setattr(self.app, field, value)
                self.assertFalse(self.app.recheck_drawing_result())
                setattr(self.app, field, old)
                monitor.assert_not_called()
                self.assertEqual(self.app.root.transitions, [])
                self.assertIsNone(self.app.worker)


if __name__ == '__main__':
    unittest.main()
