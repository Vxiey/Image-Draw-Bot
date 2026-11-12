"""The advertised reset removes the browser speed learning actually used next."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import DrawBot
import DrawTimeCalibration as timing
import DrawTimeEstimate as estimate
import ProfilePortability as portability
import ProfileStorage as storage
import RealSpeedBudget as speed
import RuntimePaths
from test_pixel_accurate_v1086 import opts
from test_v148_application_batch04_settings import Value


class RealSpeedResetTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory()))
        self.speed_file = self.root / 'real-speed-profiles.json'
        self.stack.enter_context(patch.object(speed, 'SPEED_FILE', self.speed_file))
        read_speed = speed.load_profile
        self.stack.enter_context(patch.object(speed, 'load_profile', side_effect=lambda key, path=None, **kwargs:
            read_speed(key, self.speed_file if path is None else path, **kwargs)))
        self.stack.enter_context(patch.object(storage, 'data_dir', return_value=self.root))
        self.stack.enter_context(patch.object(portability, 'data_dir', return_value=self.root))
        self.stack.enter_context(patch.object(timing, 'FILE', self.root / 'legacy-timing.json'))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.source = Image.new('RGBA', (16, 12), 'white')
        self.addCleanup(self.source.close)
        for y in range(2, 10):
            for x in range(2, 14):
                self.source.putpixel((x, y), (0, 0, 0, 255) if (x+y)%3 else (255, 0, 0, 255))
        self.options = opts(profile_key='gartic-phone', profile_name='Gartic Phone',
                            render_preset='Manual', cpu_workers='1', planning_resolution='Standard',
                            unlimited_time=True, time_budget_mode='Unlimited')
        self.plan = DrawBot.make_plan(self.source, (16, 12), options=self.options)
        for value in self.plan.values():
            if isinstance(value, Image.Image):
                self.addCleanup(value.close)
        for key, seconds in (('gartic-phone', 100.), ('skribbl', 20.)):
            self.assertTrue(speed.record_runtime_sample(key, 20, seconds, path=self.speed_file)['recorded'])
        # The application reads explicitly bound evidence. Keep the older row
        # too, so the existing reset assertions cover both generations.
        self.assertTrue(speed.record_runtime_sample('gartic-phone', 20, 100.,
            path=self.speed_file, options=self.plan['options'])['recorded'])
        self.other = speed.load_profile('skribbl')
        self.app = SimpleNamespace(activity=None, closing=False,
            game=Value('Gartic Phone'), options=lambda: dict(self.options), plan=self.plan,
            status=Value('Ready.'), draw_time_text=Value('old estimate'))
        self.app._mark_plan_stale = Mock(side_effect=lambda _reason: setattr(self.app, 'plan', None))

    def test_full_profile_reset_removes_only_selected_speed_history_from_real_next_estimate(self):
        self.assertIn('measured path throughput', estimate.estimate_from_plan(self.plan)['estimate_source'])
        with patch.object(portability, '_reload_profile') as reload:
            self.assertEqual(portability.reset_profile(self.app), 'Gartic Phone')
        self.assertIsNone(speed.load_profile('gartic-phone'))
        self.assertEqual(speed.load_profile('skribbl'), self.other)
        self.assertNotIn('measured path throughput', estimate.estimate_from_plan(self.plan)['estimate_source'])
        self.assertFalse(speed.recommend_budget('gartic-phone', 120, path=self.speed_file).learned)
        reload.assert_called_once_with(self.app, 'Gartic Phone')

    def test_learned_timing_action_retires_speed_floor_and_preserves_other_timing_context(self):
        actual = self.plan['options']
        other_context = dict(actual, brush_px=9, effective_paint_tool='Brush')
        self.assertTrue(timing.record_sample(actual, 10, 15, completed_paths=20)['recorded'])
        self.assertTrue(timing.record_sample(other_context, 10, 12, completed_paths=20)['recorded'])
        self.assertTrue(DrawBot.DrawBotApp.reset_draw_time_calibration(self.app))
        self.assertIsNone(speed.load_profile('gartic-phone'))
        self.assertEqual(speed.load_profile('skribbl'), self.other)
        self.assertIsNone(timing.load_profile(actual))
        self.assertIsNotNone(timing.load_profile(other_context))
        self.assertNotIn('measured path throughput', estimate.estimate_from_plan(self.plan)['estimate_source'])
        self.assertIsNone(self.app.plan)

    def seed_timing(self):
        actual = self.plan['options']
        other = dict(actual, brush_px=9, effective_paint_tool='Brush')
        for options in (actual, other):
            self.assertTrue(timing.record_sample(options, 10, 15, completed_paths=20)['recorded'])
        return actual, other

    def snapshot_files(self):
        return {path: path.read_bytes() for path in self.root.rglob('*.json')}

    def test_both_resets_roll_back_every_file_and_keep_visible_plan_on_speed_publication_failure(self):
        self.seed_timing()
        settings = storage.profile_settings_file('gartic-phone')
        settings.write_bytes(b'{"keep": "selected profile settings"}')
        unrelated = storage.profile_settings_file('skribbl')
        unrelated.write_bytes(b'{"keep": "another profile"}')
        before = self.snapshot_files()
        replace = RuntimePaths._replace_with_retry
        for action in ('timing', 'profile'):
            with self.subTest(action=action):
                failed = []
                def fail_final_speed(source, destination):
                    if Path(destination) == self.speed_file and str(source).endswith('.import') and not failed:
                        failed.append(True)
                        raise OSError('speed publication failed')
                    return replace(source, destination)
                with patch.object(RuntimePaths, '_replace_with_retry', side_effect=fail_final_speed), \
                        patch.object(portability, '_reload_profile') as reload:
                    if action == 'profile':
                        with self.assertRaisesRegex(portability.ProfilePortabilityError, 'previous files were restored'):
                            portability.reset_profile(self.app)
                    else:
                        self.assertFalse(DrawBot.DrawBotApp.reset_draw_time_calibration(self.app))
                    reload.assert_not_called()
                self.assertTrue(failed)
                self.assertEqual(self.snapshot_files(), before)
                self.assertIs(self.app.plan, self.plan)
                self.assertEqual(self.app.draw_time_text.get(), 'old estimate')
                self.app._mark_plan_stale.assert_not_called()

    def test_missing_timing_file_is_not_migrated_until_whole_reset_can_publish(self):
        actual = self.plan['options']
        other = dict(actual, brush_px=9, effective_paint_tool='Brush')
        for options in (actual, other):
            self.assertTrue(timing.record_sample(options, 10, 15, completed_paths=20, path=timing.FILE)['recorded'])
        legacy = timing.FILE.read_bytes()
        current = storage.profile_timing_file('gartic-phone')
        self.assertFalse(current.exists())
        real = RuntimePaths._replace_with_retry
        def fail_speed(source, destination):
            if Path(destination) == self.speed_file and str(source).endswith('.import'):
                raise OSError('speed publication failed')
            return real(source, destination)
        with patch.object(RuntimePaths, '_replace_with_retry', side_effect=fail_speed):
            self.assertFalse(DrawBot.DrawBotApp.reset_draw_time_calibration(self.app))
        self.assertFalse(current.exists())
        self.assertEqual(timing.FILE.read_bytes(), legacy)
        self.assertIs(self.app.plan, self.plan)
        self.assertTrue(DrawBot.DrawBotApp.reset_draw_time_calibration(self.app))
        self.assertTrue(current.exists())
        self.assertIsNone(timing.load_profile(actual))
        self.assertIsNotNone(timing.load_profile(other))
        self.assertEqual(timing.FILE.read_bytes(), legacy)

    def test_unreadable_or_invalid_shared_speed_history_cannot_be_silently_erased(self):
        self.seed_timing()
        valid = self.speed_file.read_bytes()
        read = speed.read_json
        for failure in ('permission', 'schema'):
            with self.subTest(failure=failure):
                if failure == 'schema':
                    self.speed_file.write_text('{"version":999,"profiles":{"skribbl":{"private":"preserve"}}}')
                before = self.snapshot_files()
                def blocked(path, **kwargs):
                    if failure == 'permission' and Path(path) == self.speed_file:
                        raise PermissionError('speed history is locked')
                    return read(path, **kwargs)
                with patch.object(speed, 'read_json', side_effect=blocked), \
                        patch.object(portability, '_reload_profile') as reload:
                    self.assertFalse(DrawBot.DrawBotApp.reset_draw_time_calibration(self.app))
                    with self.assertRaises(portability.ProfilePortabilityError):
                        portability.reset_profile(self.app)
                    reload.assert_not_called()
                self.assertEqual(self.snapshot_files(), before)
                self.assertIs(self.app.plan, self.plan)
                self.speed_file.write_bytes(valid)

    def concurrent_reset(self, action):
        self.seed_timing()
        entering, finished = threading.Event(), threading.Event()
        errors = []
        owner = threading.get_ident()
        real_transaction = speed.file_transaction
        @contextmanager
        def observe_transaction(path, **kwargs):
            if threading.get_ident() != owner and Path(path) == self.speed_file:
                entering.set()
            with real_transaction(path, **kwargs):
                yield
        def writer():
            try:
                result = speed.record_runtime_sample('skribbl', 30, 30, path=self.speed_file)
                self.assertTrue(result['recorded'])
            except BaseException as error:
                errors.append(error)
            finally:
                finished.set()
        thread = threading.Thread(target=writer)
        real_replace = RuntimePaths._replace_with_retry
        launched = []
        def publish(source, destination):
            if Path(destination) == self.speed_file and str(source).endswith('.import') and not launched:
                launched.append(True)
                thread.start()
                self.assertTrue(entering.wait(2))
                self.assertFalse(finished.is_set(), 'Writer must wait for the entire reset publication')
            return real_replace(source, destination)
        with patch.object(speed, 'file_transaction', observe_transaction), \
                patch.object(RuntimePaths, '_replace_with_retry', side_effect=publish), \
                patch.object(portability, '_reload_profile'):
            try:
                if action == 'profile':
                    self.assertEqual(portability.reset_profile(self.app), 'Gartic Phone')
                else:
                    self.assertTrue(DrawBot.DrawBotApp.reset_draw_time_calibration(self.app))
            finally:
                if launched:
                    thread.join(3)
        self.assertTrue(launched)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertIsNone(speed.load_profile('gartic-phone'))
        other = speed.load_profile('skribbl')
        self.assertEqual(other['samples'], self.other['samples'] + 1)
        self.assertEqual(other['total_paths'], self.other['total_paths'] + 30)
        self.assertEqual(other['total_seconds'], self.other['total_seconds'] + 30)

    def test_full_profile_reset_preserves_concurrent_other_profile_learning(self):
        self.concurrent_reset('profile')

    def test_timing_reset_preserves_concurrent_other_profile_learning(self):
        self.concurrent_reset('timing')

    def test_whole_profile_reset_waits_for_an_older_timing_writer_then_retires_its_model(self):
        actual, _other_context = self.seed_timing()
        for _ in range(2):
            self.assertTrue(timing.record_sample(actual, 10, 15, completed_paths=20)['recorded'])
        self.assertEqual(timing.load_profile(actual)['samples'], 3)
        another = dict(actual, profile_key='skribbl')
        self.assertTrue(timing.record_sample(another, 10, 14, completed_paths=20)['recorded'])
        other_path = storage.profile_timing_file('skribbl')
        other_bytes = other_path.read_bytes()
        selected_path = storage.profile_timing_file('gartic-phone')
        writer_entered, release_writer = threading.Event(), threading.Event()
        reset_entered, reset_done = threading.Event(), threading.Event()
        errors, order, written_samples = [], [], []
        real_write = timing.atomic_write_text
        real_transaction = portability.file_transaction
        real_replace = RuntimePaths._replace_with_retry
        def delayed_writer(path, text, **kwargs):
            writer_entered.set()
            if not release_writer.wait(3):
                raise TimeoutError('Timing writer was not released')
            value = real_write(path, text, **kwargs)
            order.append('older writer published')
            return value
        @contextmanager
        def observed_reset_lock(path, **kwargs):
            if Path(path) == selected_path:
                reset_entered.set()
            with real_transaction(path, **kwargs):
                yield
        def observe_publication(source, destination):
            if Path(destination) == selected_path and str(source).endswith('.import'):
                order.append('reset published')
            return real_replace(source, destination)
        def writer():
            try:
                result = timing.record_sample(actual, 10, 15, completed_paths=20)
                written_samples.append(result['samples'])
            except BaseException as error:
                errors.append(error)
        def reset():
            try:
                self.assertEqual(portability.reset_profile(self.app), 'Gartic Phone')
            except BaseException as error:
                errors.append(error)
            finally:
                reset_done.set()
        writer_thread = threading.Thread(target=writer)
        reset_thread = threading.Thread(target=reset)
        with patch.object(timing, 'atomic_write_text', delayed_writer), \
                patch.object(portability, 'file_transaction', observed_reset_lock), \
                patch.object(RuntimePaths, '_replace_with_retry', side_effect=observe_publication), \
                patch.object(portability, '_reload_profile') as reload:
            writer_thread.start()
            try:
                self.assertTrue(writer_entered.wait(2))
                reset_thread.start()
                self.assertTrue(reset_entered.wait(2))
                self.assertFalse(reset_done.is_set())
                self.assertEqual(order, [])
            finally:
                release_writer.set()
                writer_thread.join(3)
                if reset_thread.ident is not None:
                    reset_thread.join(3)
            self.assertFalse(writer_thread.is_alive())
            self.assertFalse(reset_thread.is_alive())
            self.assertEqual(errors, [])
            reload.assert_called_once_with(self.app, 'Gartic Phone')
        self.assertEqual(written_samples, [4])
        self.assertEqual(order, ['older writer published', 'reset published'])
        self.assertIsNone(timing.load_profile(actual))
        self.assertIsNone(speed.load_profile('gartic-phone'))
        self.assertEqual(other_path.read_bytes(), other_bytes)
        self.assertEqual(speed.load_profile('skribbl'), self.other)

    def test_timing_reset_waits_for_profile_or_clear_handoff_before_reading_ui_context(self):
        self.seed_timing()
        before = self.snapshot_files()
        self.app.options = Mock(return_value=deepcopy(self.options))
        for field, value in (('profile_change_after', 'pending-change'),
                             ('profile_change_in_progress', True), ('pending_clear_drawing', object())):
            with self.subTest(field=field), patch.object(self.app, field, value, create=True):
                self.assertFalse(DrawBot.DrawBotApp.reset_draw_time_calibration(self.app))
        self.app.options.assert_not_called()
        self.assertEqual(self.snapshot_files(), before)
        self.assertIs(self.app.plan, self.plan)


if __name__ == '__main__':
    unittest.main()
