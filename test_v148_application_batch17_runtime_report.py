"""The Studio safety card belongs to the execution which produced its evidence."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import DrawBot
from DrawBot import DrawBotApp
from RuntimeSafetyReport import RuntimeSafetySession, latest_report
from WorkerEventQueue import WorkerEventQueue
from test_v148_application_batch04_settings import Value
import test_v148_application_batch14_browser_start as worker_fixtures
from test_pixel_accurate_v1086 import opts
from test_step15_correction_review_recovery_v10139 import trusted_post


class NativeMouse:
    """Replacement desktop boundary; production GuardedMouse still runs."""
    def __init__(self):
        self.position = (10, 10)
        self.held = self.armed = False
        self.actions = []
        self.on_press = None

    def get_position(self):
        return self.position

    def arm_input(self):
        self.armed = True

    def disarm_input(self):
        self.armed = False

    def move(self, x, y):
        self.position = (x, y)
        self.actions.append(('move', x, y))

    def press(self):
        self.held = True
        self.actions.append(('press',))
        if self.on_press is not None:
            self.on_press()

    def release(self):
        self.held = False
        self.actions.append(('release',))

    def click(self):
        self.actions.append(('click',))

    def snapshot_canvas(self, area):
        # Advertise the real backend capability used by correction readiness.
        # GuardedMouse performs the actual tested capture through _grab_rgb.
        raise AssertionError('Capture must pass through GuardedMouse.')


class NativeMonitor:
    def activate(self, target):
        return True

    def active(self, target):
        return True

    def verify(self, target, point):
        return None

    def rectangle(self, handle):
        return (0, 0, 300, 250)

    def colors(self, positions):
        return [(0, 0, 0) for _ in positions]


class RuntimeReportApplicationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimeSafetyReport.REPORT_DIR', self.directory / 'reports'))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawBot.log_error'))
        self.stack.enter_context(patch('DrawBot.threading.Thread', worker_fixtures.DeferredThread))
        self.stack.enter_context(patch('ScreenGuard.WindowMonitor', NativeMonitor))
        self.capture = self.stack.enter_context(patch('ScreenGuard._grab_rgb', side_effect=self.grab))
        self.probe = self.stack.enter_context(patch('TargetCapture.probe_handle_isolated', return_value={
            'handle': 1, 'rect': (0, 0, 300, 250), 'client_rect': (0, 0, 300, 250), 'dpi': 96}))
        self.stack.enter_context(patch('DrawBot.load_calibration'))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        self.stack.enter_context(patch('CorrectionHistory.load_correction_history', return_value={}))
        for target in ('SessionRecovery.save_render_progress', 'SessionRecovery.clear_render_progress',
                       'RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                       'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                       'CorrectionHistory.record_correction_history'):
            self.stack.enter_context(patch(target, return_value={}))
        self.stack.enter_context(patch('DrawBot.allColors', [
            SimpleNamespace(name='black', RGB=(0, 0, 0), x=20, y=20)]))
        self.loader = self.stack.enter_context(patch('DrawBot.load_latest_runtime_safety_report', wraps=latest_report))
        self.open_file = self.stack.enter_context(patch('os.startfile', create=True))
        self.plans = []
        self.executions = []
        self.stop_capture = False
        self.app = self.make_app()
        real_plan = DrawBot.make_plan
        real_execute = DrawBot.execute_plan
        def plan(*args, **kwargs):
            result = real_plan(*args, **kwargs)
            self.plans.append(result)
            return result
        def execute(plan, *args, **kwargs):
            self.executions.append(plan)
            return real_execute(plan, *args, clock=lambda: 0., **kwargs)
        self.planner = self.stack.enter_context(patch('DrawBot.make_plan', side_effect=plan))
        self.executor = self.stack.enter_context(patch('DrawBot.execute_plan', side_effect=execute))
        self.addCleanup(self.release_plans)
        history = RuntimeSafetySession(profile_name='Previous run', planned_paths=99)
        history.counts.update(drawn=99, paths_processed=99)
        history.mark_completed()
        self.history = history.save()

    def make_app(self):
        app = DrawBotApp.__new__(DrawBotApp)
        app.root = worker_fixtures.ScheduledRoot()
        app.root.deiconify = Mock()
        app.activity = app.worker = None
        app.closing = app.shutdown_complete = False
        app.pending_clear_drawing = None
        app.profile_change_after = None
        app.profile_change_in_progress = False
        app.events = WorkerEventQueue()
        app.published = []
        put = app.events.put
        def publish(event, *args, **kwargs):
            app.published.append(event)
            return put(event, *args, **kwargs)
        app.events.put = publish
        app.stop = worker_fixtures.NoWaitEvent()
        app.paused = threading.Event()
        app.original = Image.new('RGBA', (8, 8), 'black')
        self.addCleanup(app.original.close)
        app.plan = None
        app.upscale_original = app.background_removal_original = None
        app.game = Value('Microsoft Paint')
        app._active_profile_name = 'Microsoft Paint'
        app.paint_simple = Value(True)
        app.paint_tool = Value('Use current tool')
        app.outline = Value(False)
        app.palette_ready = True
        app.corners = [(100, 100), (164, 164)]
        app.saved_area = list(app.corners)
        app.target_window = (1, (0, 0, 300, 250))
        app.target_client_rect = (0, 0, 300, 250)
        app.target_dpi = 96
        app.calibration_path = self.directory / 'palette.json'
        app.color_session_cache = {}
        app.preview_generation = 1
        app.preview_mode = Value('Manual')
        app.needs_plan = False
        app.mouse = NativeMouse()
        app.keyboard = None
        app.progress = {'value': 0}
        app.summary = Value('Existing summary.')
        app.status = Value('Ready.')
        app.draw_time_text = Value('')
        app.preview_diagnostics_text = Value('')
        app.runtime_safety_summary = Value('')
        app.runtime_safety_detail = Value('')
        app.correction_review_text = Value('')
        app.color_plan_text = Value('')
        app.file_label = Value('Image loaded')
        app.url = Value('')
        app.set_busy = lambda value: setattr(app, 'activity', value)
        app.show_previews = Mock()
        app._sync_mobile_preview = Mock()
        app.save_settings = Mock()
        app._schedule_recovery_checkpoint = Mock()
        app._finish_shutdown = Mock()
        app.options = lambda: opts(profile_name='Microsoft Paint', profile_key='microsoft-paint',
            paint_current_color=True, render_preset='Manual', planning_watchdog='Off',
            unlimited_time=True, time_budget_mode='Unlimited', cpu_workers='1', cpu_workers_resolved=1,
            detail_zoom='Off', canvas_edge_verification='Off', strict_color_verification=False,
            adaptive_color_verification=False, visual_verification_enabled=False,
            post_draw_correction_pass='Off', _execution_cost_calibration_override={})
        return app

    def release_plans(self):
        from AutoSketchBudget import _trial_images
        for plan in self.plans:
            for image in _trial_images(plan):
                if image is not self.app.original:
                    image.close()

    def grab(self, box):
        if self.stop_capture:
            self.app.stop.set()
            raise InterruptedError('Stopped during current canvas capture.')
        return Image.new('RGB', (box[2] - box[0], box[3] - box[1]), 'black')

    def start_draw(self, *, dry_run=False):
        self.app.draw(user_initiated=True, paint_prepared=True, dry_run=dry_run)
        self.assertIsNotNone(self.app.worker, self.app.status.get())
        self.app.worker.run()
        self.assertEqual(len(self.executions), 1, [kind for kind, _ in self.app.published])
        return self.executions[-1]

    def drain(self):
        events = []
        while not self.app.events.empty():
            event = self.app.events.get_nowait()
            events.append(event)
            self.app._handle_event(*event)
        return events

    def prepare_retry(self, *, early_failure=False):
        plan = DrawBot.make_plan(self.app.original, (64, 64), self.app.options())
        plan['options'].update(paint_current_color=False,
            post_draw_accuracy_meta=trusted_post(visual_accuracy_percent=60),
            auto_tuner_acceptance_meta={'gates': {'visual_accuracy_min_percent': 76}},
            runtime_safety_report=self.history)
        if early_failure:
            plan['options'].update(unlimited_time=False, max_seconds='invalid deadline')
        self.app.plan = plan
        self.app.paint_simple.set(False)
        self.app.full_draw_armed_until = float('inf')
        self.app.target_lock_passed = True
        self.app.target_lock_signature = self.app._target_lock_signature_from(
            self.app._build_target_lock_fingerprint())
        self.app.safety_preflight_passed = True
        self.app.safety_preflight_valid_until = float('inf')
        self.app.safety_preflight_signature = self.app._current_safety_signature()
        state = self.app.refresh_correction_review_ui()
        self.assertTrue(state['actions']['retry_correction_only']['enabled'], state)
        return plan

    def test_startup_still_loads_saved_history(self):
        self.app.refresh_runtime_safety_ui()
        self.loader.assert_called_once_with()
        self.assertTrue(self.app.runtime_safety_summary.get().startswith('PASS'))
        self.assertIn('Drawn 99', self.app.runtime_safety_summary.get())

    def test_failed_report_save_displays_current_stop_instead_of_old_disk_pass(self):
        self.app.mouse.on_press = self.app.stop.set
        with patch('RuntimeSafetyReport.replace_text_files', side_effect=PermissionError('report directory read-only')):
            plan = self.start_draw()
        payload = plan['options']['runtime_safety_report']
        self.assertFalse(payload['completed'])
        self.assertEqual(payload['counts']['stopped'], 1)
        self.assertIn('save_error', payload)
        self.assertFalse(self.app.mouse.held)
        self.drain()
        self.assertTrue(self.app.runtime_safety_summary.get().startswith('STOPPED'), self.app.runtime_safety_summary.get())
        self.assertIn('report directory read-only', self.app.runtime_safety_detail.get())
        self.loader.assert_not_called()

    def test_current_success_is_published_without_rescanning_disk(self):
        plan = self.start_draw()
        self.drain()
        self.assertTrue(plan['options']['runtime_safety_report']['completed'])
        self.assertTrue(self.app.runtime_safety_summary.get().startswith('PASS'))
        self.assertNotIn('Drawn 99', self.app.runtime_safety_summary.get())
        self.loader.assert_not_called()

    def test_current_dry_run_keeps_its_mode_and_does_not_rescan_disk(self):
        plan = self.start_draw(dry_run=True)
        self.drain()
        self.assertEqual(plan['options']['runtime_safety_report']['mode'], 'dry-run')
        self.assertIn('dry-run', self.app.runtime_safety_summary.get())
        self.assertFalse(any(action[0] in ('press', 'click') for action in self.app.mouse.actions))
        self.loader.assert_not_called()

    def test_retry_publishes_its_own_report_without_replacing_base_report(self):
        base = self.prepare_retry()
        self.app.retry_post_draw_correction()
        self.assertIsNotNone(self.app.worker, self.app.status.get())
        self.app.worker.run()
        self.drain()
        self.assertEqual(len(self.executions), 1)
        current = self.executions[0]['options']['runtime_safety_report']
        self.assertTrue(current['completed'])
        self.assertEqual(current['counts']['drawn'], 0)
        self.assertIs(base['options']['runtime_safety_report'], self.history)
        self.assertIn('Drawn 0', self.app.runtime_safety_summary.get())
        self.loader.assert_not_called()

    def test_early_retry_failure_does_not_republish_the_inherited_pass(self):
        base = self.prepare_retry(early_failure=True)
        self.app.retry_post_draw_correction()
        self.assertIsNotNone(self.app.worker, self.app.status.get())
        self.app.worker.run()
        self.drain()
        self.assertEqual(len(self.executions), 1)
        self.assertNotIn('runtime_safety_report', self.executions[0]['options'])
        self.assertIs(base['options']['runtime_safety_report'], self.history)
        self.assertNotIn('PASS', self.app.runtime_safety_summary.get())
        self.assertNotIn('Drawn 99', self.app.runtime_safety_summary.get())
        self.loader.assert_not_called()

    def test_open_does_not_launch_an_older_report_when_current_save_failed(self):
        self.app.mouse.on_press = self.app.stop.set
        with patch('RuntimeSafetyReport.replace_text_files', side_effect=PermissionError('report directory read-only')):
            self.start_draw()
        self.drain()
        self.app.open_latest_safety_report()
        self.open_file.assert_not_called()
        self.assertIn('not saved', self.app.status.get().lower())
        self.loader.assert_not_called()

    def current_result(self):
        events = [event for event in self.app.published if event[0] == 'runtime_safety_complete']
        self.assertEqual(len(events), 1, [kind for kind, _ in self.app.published])
        return events[0]

    def test_stopped_retry_publishes_current_evidence_without_modifying_base_report(self):
        base = self.prepare_retry()
        self.stop_capture = True
        with patch('RuntimeSafetyReport.replace_text_files', side_effect=PermissionError('retry report not writable')):
            self.app.retry_post_draw_correction()
            self.assertIsNotNone(self.app.worker, self.app.status.get())
            self.app.worker.run()
        current = self.executions[0]['options']['runtime_safety_report']
        self.assertFalse(current['completed'])
        self.assertEqual(current['counts']['stopped'], 1)
        self.drain()
        self.assertTrue(self.app.runtime_safety_summary.get().startswith('STOPPED'))
        self.assertIn('retry report not writable', self.app.runtime_safety_detail.get())
        self.assertIs(base['options']['runtime_safety_report'], self.history)
        self.loader.assert_not_called()

    def test_worker_envelope_and_adopted_cache_do_not_alias_the_mutable_plan(self):
        plan = self.start_draw()
        event = self.current_result()
        expected = dict(plan['options']['runtime_safety_report']['counts'])
        plan['options']['runtime_safety_report']['counts']['drawn'] = 9876
        self.drain()
        summary = self.app.runtime_safety_summary.get()
        self.assertIn(f"Drawn {expected['drawn']}", summary)
        self.assertNotIn('9,876', summary)
        event[1].payload['counts']['drawn'] = 6543
        self.app.refresh_runtime_safety_ui()
        self.assertEqual(self.app.runtime_safety_summary.get(), summary)
        self.loader.assert_not_called()

    def test_new_attempt_cannot_adopt_a_retained_result_from_the_previous_run(self):
        self.start_draw()
        event = self.current_result()
        self.drain()
        self.app.draw(user_initiated=True, paint_prepared=True)
        self.assertIsNotNone(self.app.worker)
        pending = self.app.runtime_safety_summary.get()
        self.assertIn('pending', pending.lower())
        self.app._handle_event(*event)
        self.assertEqual(self.app.runtime_safety_summary.get(), pending)
        self.app.open_latest_safety_report()
        self.open_file.assert_not_called()
        self.app.stop.set()
        self.app.worker.run()
        self.drain()
        stopped = self.app.runtime_safety_summary.get()
        self.assertTrue(stopped.startswith('STOPPED'), stopped)
        self.app._handle_event(*event)
        self.assertEqual(self.app.runtime_safety_summary.get(), stopped)
        self.loader.assert_not_called()

    def test_clear_invalidates_queued_results_and_does_not_restore_disk_history(self):
        self.start_draw()
        event = self.current_result()
        self.drain()
        with patch('SessionRecovery.clear_snapshot'), \
                patch('SessionRecovery.STATE_FILE', self.directory / 'absent-state.json'), \
                patch('SessionRecovery.RENDER_FILE', self.directory / 'absent-render.json'), \
                patch('SessionRecovery.IMAGE_FILE', self.directory / 'absent-source.png'):
            self.app.clear_cached_drawing()
        self.assertIsNone(self.app.pending_clear_drawing)
        self.assertIsNone(self.app.plan)
        self.app._handle_event(*event)
        self.app.refresh_runtime_safety_ui()
        self.assertNotIn('PASS', self.app.runtime_safety_summary.get())
        self.assertIn('No current', self.app.runtime_safety_summary.get())
        self.app.open_latest_safety_report()
        self.open_file.assert_not_called()
        self.loader.assert_not_called()

    def test_closing_rejects_retained_runtime_results_and_open_actions(self):
        self.start_draw()
        event = self.current_result()
        self.app.close()
        self.assertTrue(self.app.closing)
        summary = self.app.runtime_safety_summary.get()
        detail = self.app.runtime_safety_detail.get()
        self.app._handle_event(*event)
        self.app.refresh_runtime_safety_ui()
        self.app.open_latest_safety_report()
        self.assertEqual((self.app.runtime_safety_summary.get(), self.app.runtime_safety_detail.get()),
                         (summary, detail))
        self.open_file.assert_not_called()
        self.loader.assert_not_called()

    def test_stop_before_worker_task_never_relabels_an_old_pass_as_current(self):
        self.app.refresh_runtime_safety_ui()
        self.assertTrue(self.app.runtime_safety_summary.get().startswith('PASS'))
        self.loader.reset_mock()
        self.app.draw(user_initiated=True, paint_prepared=True)
        self.assertIsNotNone(self.app.worker)
        self.app.cancel()
        self.app.worker.run()
        self.drain()
        self.executor.assert_not_called()
        self.assertTrue(self.app.runtime_safety_summary.get().startswith('STOPPED'))
        self.assertNotIn('Drawn 99', self.app.runtime_safety_summary.get())
        self.loader.assert_not_called()

    def test_native_thread_start_failure_keeps_current_missing_report_state(self):
        self.app.refresh_runtime_safety_ui()
        self.loader.reset_mock()
        with patch.object(worker_fixtures.DeferredThread, 'start', side_effect=RuntimeError('native thread start')):
            with self.assertRaisesRegex(RuntimeError, 'native thread start'):
                self.app.draw(user_initiated=True, paint_prepared=True)
        self.executor.assert_not_called()
        self.assertTrue(self.app.runtime_safety_summary.get().startswith('STOPPED'))
        self.assertNotIn('Drawn 99', self.app.runtime_safety_summary.get())
        self.loader.assert_not_called()

    def test_open_and_refresh_keep_the_current_report_when_disk_history_advances(self):
        plan = self.start_draw()
        self.drain()
        expected_path = Path(plan['options']['runtime_safety_report']['text_path'])
        expected_summary = self.app.runtime_safety_summary.get()
        unrelated = RuntimeSafetySession(profile_name='Another saved run', planned_paths=500)
        unrelated.counts.update(drawn=500, paths_processed=500)
        unrelated.mark_completed()
        other = unrelated.save()
        self.assertNotEqual(Path(other['text_path']), expected_path)
        self.app.refresh_runtime_safety_ui()
        self.app.open_latest_safety_report()
        self.open_file.assert_called_once_with(expected_path)
        self.assertEqual(self.app.runtime_safety_summary.get(), expected_summary)
        self.loader.assert_not_called()

    def test_retry_preserves_stop_from_preflight_settings_and_worker_construction(self):
        from ScreenTaskWindow import ScreenTaskWindow
        for stage in ('preflight', 'settings', 'window', 'thread'):
            with self.subTest(stage=stage), ExitStack() as local:
                self.app = self.make_app()
                self.prepare_retry()
                before = len(self.executions)
                if stage == 'preflight':
                    metadata = dict(self.probe.return_value)
                    local.enter_context(patch('TargetCapture.probe_handle_isolated',
                        side_effect=lambda *args, **kwargs: self.app.stop.set() or metadata))
                elif stage == 'settings':
                    self.app.save_settings.side_effect = self.app.stop.set
                elif stage == 'window':
                    local.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow',
                        side_effect=lambda root: self.app.stop.set() or ScreenTaskWindow(root)))
                else:
                    def thread(**kwargs):
                        created = worker_fixtures.DeferredThread(**kwargs)
                        self.app.stop.set()
                        return created
                    local.enter_context(patch('DrawBot.threading.Thread', side_effect=thread))
                self.app.retry_post_draw_correction()
                if self.app.worker is not None:
                    self.app.worker.run()
                self.assertTrue(self.app.stop.is_set(), f'{stage} Stop was cleared during retry handoff')
                self.assertEqual(len(self.executions), before)
                self.assertFalse(any(action[0] in ('press', 'click') for action in self.app.mouse.actions))

    def test_new_explicit_correction_retry_can_follow_an_earlier_stop(self):
        self.prepare_retry()
        self.app.stop.set()
        self.app.retry_post_draw_correction()
        self.assertIsNotNone(self.app.worker, self.app.status.get())
        self.app.worker.run()
        self.drain()
        self.assertFalse(self.app.stop.is_set())
        self.assertEqual(len(self.executions), 1)
        self.assertTrue(self.executions[0]['options']['runtime_safety_report']['completed'])

    def test_retry_waits_for_profile_and_clear_before_os_preflight_or_settings(self):
        for attribute, value in (('profile_change_after', 'pending-profile'),
                                 ('profile_change_in_progress', True), ('pending_clear_drawing', False)):
            with self.subTest(attribute=attribute):
                self.app = self.make_app()
                self.prepare_retry()
                setattr(self.app, attribute, value)
                self.probe.reset_mock()
                self.app.retry_post_draw_correction()
                self.probe.assert_not_called()
                self.app.save_settings.assert_not_called()
                self.assertIsNone(self.app.worker)


if __name__ == '__main__':
    unittest.main()
