"""Applying a real hardware recommendation owns settings and cached plans."""
from copy import deepcopy
import json
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DrawBot import DrawBotApp
import test_v148_application_batch04_settings as settings_fixture
from test_v148_application_batch04_settings import Value
import test_v148_application_batch17_runtime_report as execution_fixture


RECOMMENDATION = {'cpu_workers': 'Auto', 'cpu_engine': 'Threads', 'ram_budget': 'Custom',
    'ram_custom_mb': '2048', 'planning_resolution': 'High',
    'resource_scheduler': 'Benchmark recommendations', 'gpu_mode': 'CPU',
    'gpu_vram': 'Auto', 'gpu_performance': 'Balanced', 'cpu_workers_effective': 2}
FIELDS = tuple(name for name in RECOMMENDATION if name != 'cpu_workers_effective')


class SavedTuneApplicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = execution_fixture.RuntimeReportApplicationTests('test_startup_still_loads_saved_history')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app = self.fixture.app
        self.plan = self.fixture.prepare_retry()
        settings = settings_fixture.LocalSettingsTests('test_save_result_exposes_disk_failure_and_preserves_old_document')
        settings.setUp()
        self.addCleanup(settings.doCleanups)
        for name, value in vars(settings.app).items():
            if isinstance(value, Value) and not hasattr(self.app, name):
                setattr(self.app, name, value)
        for name in FIELDS:
            getattr(self.app, name).set(str(RECOMMENDATION[name]))
        self.app.ram_budget.set('Auto')
        self.app.settings_path = self.fixture.directory / 'settings.json'
        self.app.save_settings = MethodType(DrawBotApp.save_settings, self.app)
        self.app.auto_tune_summary = Value('Saved recommendation.')
        self.app.auto_tune_detail = Value('Ready.')
        self.app.hardware_benchmark_running = False
        self.app.preview_dirty_reason = ''
        self.app.draw_time_text.set('OLD PLAN ETA')
        self.app.preview_diagnostics_text.set('OLD PLAN DIAGNOSTICS')
        self.app.running = False
        self.app.mobile_preview_server = SimpleNamespace(running=True, queue_images=Mock(return_value=True))
        self.payload = {'recommendation': deepcopy(RECOMMENDATION)}
        self.fixture.stack.enter_context(patch('DrawBot.load_tune_result', return_value=self.payload))
        self.assertTrue(self.app.save_settings())

    def values(self):
        return {name: getattr(self.app, name).get() for name in FIELDS}

    def test_applied_recommendation_invalidates_actual_plan_and_derived_feedback_once(self):
        before_generation = self.app.preview_generation
        self.assertTrue(self.app.apply_performance_tune())
        self.assertEqual(self.app.ram_budget.get(), 'Custom')
        self.assertEqual(json.loads(self.app.settings_path.read_text())['ram_budget'], 'Custom')
        self.assertTrue(self.app.plan is None, 'The accepted recommendation retained the old plan.')
        self.assertEqual(self.app.preview_generation, before_generation + 1)
        self.assertNotIn('OLD PLAN', self.app.draw_time_text.get())
        self.assertNotIn('OLD PLAN', self.app.preview_diagnostics_text.get())
        self.assertFalse(self.app.needs_plan)
        self.assertIsNotNone(self.app.mobile_preview_after)
        self.app.root.run(self.app.mobile_preview_after)
        self.app.mobile_preview_server.queue_images.assert_called_once_with(
            original=self.app.original, preview=None, safety=None)
        self.assertFalse(self.app.target_lock_passed)

    def test_actual_save_failure_rolls_back_settings_and_keeps_prior_plan_and_document(self):
        values, document = self.values(), self.app.settings_path.read_bytes()
        with patch('DrawBot.atomic_write_text', side_effect=PermissionError('settings directory locked')):
            self.assertFalse(self.app.apply_performance_tune())
        self.assertEqual(self.values(), values)
        self.assertEqual(self.app.settings_path.read_bytes(), document)
        self.assertIs(self.app.plan, self.plan)
        self.assertEqual(self.app.draw_time_text.get(), 'OLD PLAN ETA')
        self.assertFalse(self.app.profile_change_in_progress)
        self.assertNotIn('Hardware profile applied:', self.app.status.get())

    def test_busy_clear_shutdown_or_profile_transition_does_not_load_or_apply_saved_tune(self):
        for field, value in (('activity', 'draw'), ('activity', 'performance-auto-tuner'),
                ('closing', True), ('pending_clear_drawing', False),
                ('profile_change_after', 'queued'), ('profile_change_in_progress', True)):
            with self.subTest(field=field, value=value), patch('DrawBot.load_tune_result') as loader:
                before, previous = self.values(), getattr(self.app, field)
                setattr(self.app, field, value)
                try:
                    self.assertFalse(self.app.apply_performance_tune())
                finally:
                    setattr(self.app, field, previous)
                loader.assert_not_called()
                self.assertEqual(self.values(), before)
                self.assertIs(self.app.plan, self.plan)

    def test_identical_recommendation_preserves_current_plan(self):
        self.app.ram_budget.set('Custom')
        before = self.app.preview_generation
        self.assertTrue(self.app.apply_performance_tune())
        self.assertIs(self.app.plan, self.plan)
        self.assertEqual(self.app.preview_generation, before)
        self.assertIsNone(getattr(self.app, 'mobile_preview_after', None))
        self.app.mobile_preview_server.queue_images.assert_not_called()

    def test_actual_run_apply_worker_event_and_done_preserve_automatic_apply_path(self):
        with patch('DrawBot.run_auto_tune', return_value=self.payload):
            self.assertTrue(self.app.run_performance_auto_tuner(apply=True))
            self.app.worker.run()
        self.assertEqual(self.app.activity, 'performance-auto-tuner')
        self.fixture.drain()
        self.assertIsNone(self.app.activity)
        self.assertTrue(self.app.plan is None, 'Run + apply retained the old plan.')
        self.assertEqual(self.app.ram_budget.get(), 'Custom')
        self.assertEqual(json.loads(self.app.settings_path.read_text())['ram_budget'], 'Custom')
        self.assertFalse(self.app.hardware_benchmark_running)

    def test_late_benchmark_result_after_stop_does_not_apply_recommendation(self):
        before = self.values()
        with patch('DrawBot.run_auto_tune', return_value=self.payload):
            self.assertTrue(self.app.run_performance_auto_tuner(apply=True))
            self.app.worker.run()
        self.app._request_stop()
        self.fixture.drain()
        self.assertEqual(self.values(), before)
        self.assertIs(self.app.plan, self.plan)
        self.assertIn('cancelled', self.app.auto_tune_summary.get().lower())


if __name__ == '__main__':
    unittest.main()
