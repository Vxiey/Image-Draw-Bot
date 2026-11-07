"""Actual profile publication/reload retires the preceding one-shot Drop-In."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
import time
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import Colors
import DrawBot
import GameProfiles
import ProfileIsolation
import ProfilePortability
import ProfileStorage
import RealSpeedBudget
from DropInSynchronization import AUTO_SETUP_RUNNING, IDLE, READY_TO_DRAW
from DropInStart import DROP_IN_ACTION
from SettingsValidation import ADDITIONAL_VARIABLES
from test_v148_application_batch04_settings import Value
from test_v148_ui_batch20_auto_preview import ScheduledRoot


class ProfileDropInReloadTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=self.directory))
        self.stack.enter_context(patch.object(RealSpeedBudget, 'SPEED_FILE', self.directory / 'speed.json'))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_refresh_start_buttons_text'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_clear_plan_feedback'))
        builtins = {name: value for name, value in GameProfiles.PROFILES.items()
                    if not value[0].startswith('custom-')}
        self.stack.enter_context(patch.dict(GameProfiles.PROFILES, builtins, clear=True))
        self.stack.enter_context(patch.dict(GameProfiles.PROFILE_UI))
        colors = list(Colors.allColors)
        def restore_colors():
            Colors.allColors[:] = colors
            from PixelData import closest_color
            closest_color.cache_clear()
        self.addCleanup(restore_colors)
        self.images = []
        self.addCleanup(lambda: [image.close() for image in self.images])
        self.palette = {'version': 4, 'profile': 'skribbl', 'state': 'verified',
            'verification': {'confidence': .99, 'source': 'other-computer'},
            'colors': [{'name': 'Black', 'position': [20, 30], 'rgb': [0, 0, 0]},
                       {'name': 'White', 'position': [40, 30], 'rgb': [255, 255, 255]}]}
        self.package = ProfilePortability.build_package('Skribbl.io', {'mode': 'Dots'},
                                                        {'palette': self.palette})

    def app(self):
        app = SimpleNamespace(**{name: Value('') for name in
            (*ProfileIsolation.SETTING_NAMES, *ADDITIONAL_VARIABLES)})
        values = {'game': 'Skribbl.io', 'quality': 'Balanced', 'speed': 'Safe',
            'mode': 'Dots', 'contrast': 1., 'brush_px': '2', 'max_seconds': '180',
            'outline': False, 'skip_white': True, 'preview_show_background': True,
            'preview_show_fill': True, 'preview_show_strokes': True, 'ui_mode': 'Simple',
            'subject_focus': 'Off', 'manual_drop_in_start': False, 'preview_mode': 'Manual',
            'auto_clear_canvas': False, 'palette_text': '', 'profile_hint': '',
            'area_text': '', 'summary': '', 'status': '', 'drop_in_text': ''}
        for name, value in values.items():
            setattr(app, name, Value(value))
        app.root = ScheduledRoot()
        app.root.title = Mock()
        app.activity = None
        app.closing = False
        app.profile_change_in_progress = False
        app.profile_change_after = None
        app.profile_change_ticket = None
        app._active_profile_name = 'Skribbl.io'
        app.color_session_cache = {}
        app.canvas_anchor_detection = None
        app.browser_drawing_region = None
        app.plan = None
        app.pending_clear_drawing = None
        app.manual_drop_in_armed_until = 0.
        app.manual_drop_in_after = None
        app.pending_drop_in_after = None
        app.drop_action_pending = None
        app.pending_drop_in_import = None
        app.drop_in_start_context = None
        app.drop_in_sync_phase = IDLE
        app.full_draw_armed_until = time.monotonic() + 10.
        app.draw_arm_after = None
        app.stop = threading.Event()
        app.mouse = Mock()
        app.drop_in_button = Mock()
        app.original = Image.new('RGB', (16, 12), '#205080')
        self.images.append(app.original)
        app.settings_path = ProfileStorage.profile_settings_file('skribbl')
        app.calibration_path = ProfileStorage.profile_palette_file('skribbl')
        self.assertEqual(app.settings_path.parent, self.directory)
        self.assertEqual(ProfilePortability.profile_timing_file('skribbl').parent, self.directory)
        app.calibration_path.write_text(json.dumps(self.palette), encoding='utf-8')
        for name in ('save_settings', 'read_settings', 'refresh_palette', '_apply_profile_change',
                     '_mark_plan_stale', '_palette_preflight_ready', '_paint_tool_preflight_ready',
                     'arm_manual_drop_in', '_expire_manual_drop_in', '_drop_in_sync_tick',
                     '_run_pending_drop_in_start'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        for name in ('refresh_tool_calibration', 'refresh_app_tool_calibration',
                     'refresh_exact_color_status', 'set_busy', 'show_previews',
                     'schedule_previews', '_schedule_recovery_checkpoint'):
            setattr(app, name, Mock())
        # Native window/screenshot verification is the external boundary here;
        # the real readiness, authorization and queued-dispatch policies run.
        app._refresh_target_for_draw = Mock(return_value=(0, 0, 1200, 900))
        self.ready(app)
        return app

    def ready(self, app):
        app.corners = [(100, 120), (500, 420)]
        app.saved_area = tuple(app.corners)
        app.target_window = (71, (0, 0, 1200, 900))
        app.target_client_rect = (0, 0, 1200, 900)
        app.target_dpi = 96
        app.calibration_path.write_text(json.dumps({**self.palette,
            'profile': GameProfiles.PROFILES[app.game.get()][0]}), encoding='utf-8')
        app.refresh_palette()
        self.assertTrue(app.palette_ready)
        self.assertEqual(DrawBot.DrawBotApp._start_guard_ready(app), (True, 'Basic setup ready.'))

    def queued_import(self, app):
        self.assertTrue(app.arm_manual_drop_in())
        app.activity = 'browser-auto-calibration'
        app.drop_in_sync_phase = AUTO_SETUP_RUNNING
        self.assertTrue(DrawBot.DrawBotApp._queue_pending_drop_in_import(
            app, 'previous-image.png', 'previous-image.png', DROP_IN_ACTION))
        # The setup has finished; its queued Tk continuation has not run yet.
        app.activity = None
        app.drop_in_sync_phase = READY_TO_DRAW
        return app.root.history[app.pending_drop_in_after]

    def queued_start(self, app):
        self.assertTrue(app.arm_manual_drop_in())
        self.assertTrue(DrawBot.DrawBotApp._queue_drop_in_start(app, DROP_IN_ACTION,
                                                              source_label='previous-image.png'))
        self.assertTrue(DrawBot.DrawBotApp._schedule_pending_drop_in_start(app))
        return app.root.history[max(app.root.history)]

    def change(self, app, route):
        if route == 'reset':
            return ProfilePortability.reset_profile(app)
        return ProfilePortability.import_package_into_app(app, self.package, action=route,
            copy_name='Skribbl imported copy' if route == 'copy' else None)

    def assert_disarmed(self, app):
        self.assertFalse(DrawBot.DrawBotApp._manual_drop_in_armed(app))
        self.assertFalse(app.manual_drop_in_start.get())
        self.assertEqual(app.manual_drop_in_armed_until, 0.)
        for field in ('manual_drop_in_after', 'pending_drop_in_after', 'drop_action_pending',
                      'pending_drop_in_import', 'drop_in_start_context'):
            self.assertIsNone(getattr(app, field), field)
        self.assertEqual(app.drop_in_sync_phase, IDLE)
        self.assertIn('Drop-In Start is off', app.drop_in_text.get())
        self.assertEqual(app.drop_in_button.configure.call_args.kwargs['text'], '⚡  Arm Drop-In Start')

    def test_actual_replace_and_copy_reload_revoke_waiting_import_and_visible_arm(self):
        for route in ('replace', 'copy'):
            with self.subTest(route=route):
                app = self.app()
                original = app.original
                callback = self.queued_import(app)
                timers = (app.manual_drop_in_after, app.pending_drop_in_after)
                self.change(app, route)
                self.assert_disarmed(app)
                self.assertTrue(app.settings_path.is_file())
                self.assertTrue(app.calibration_path.is_file())
                self.assertTrue(app.palette_ready)
                self.assertIs(app.original, original)
                self.assertIsNone(app.target_window)
                self.assertEqual(app.full_draw_armed_until, 0.)
                self.assertEqual(app.preview_mode.get(), 'Manual')
                self.assertTrue(all(token not in app.root.jobs for token in timers))
                with patch.object(DrawBot.DrawBotApp, 'load_source') as load, \
                        patch.object(DrawBot.DrawBotApp, 'draw') as draw:
                    self.assertFalse(callback())
                load.assert_not_called(); draw.assert_not_called()
                self.assertEqual(app.mouse.mock_calls, [])

    def test_actual_reset_reloads_defaults_and_retires_queued_draw(self):
        app = self.app()
        original = app.original
        callback = self.queued_start(app)
        self.assertEqual(self.change(app, 'reset'), 'Skribbl.io')
        self.assert_disarmed(app)
        self.assertFalse(app.calibration_path.exists())
        self.assertEqual(json.loads(ProfilePortability.profile_timing_file('skribbl').read_text())['profiles'], {})
        self.assertFalse(app.palette_ready)
        self.assertIs(app.original, original)
        self.assertIsNone(app.target_window)
        self.assertEqual(app.full_draw_armed_until, 0.)
        with patch.object(DrawBot.DrawBotApp, 'draw') as draw:
            self.assertFalse(callback())
        draw.assert_not_called()
        self.assertEqual(app.mouse.mock_calls, [])

    def test_old_callback_cannot_dispatch_but_new_explicit_arm_uses_real_queue_policy(self):
        for route in ('replace', 'reset'):
            with self.subTest(route=route):
                app = self.app()
                old_callback = self.queued_start(app)
                self.change(app, route)
                with patch.object(DrawBot.DrawBotApp, 'draw', return_value=True) as draw:
                    self.assertFalse(old_callback())
                    self.assertFalse(DrawBot.DrawBotApp._queue_drop_in_start(app, DROP_IN_ACTION))
                    self.assertFalse(app.arm_manual_drop_in())  # Reload requires setup again.
                    draw.assert_not_called()
                    self.ready(app)
                    new_callback = self.queued_start(app)
                    self.assertTrue(new_callback())
                    draw.assert_called_once_with(app, user_initiated=True)
                self.assert_disarmed(app)
                self.assertEqual(app.mouse.mock_calls, [])

    def test_stop_is_not_cleared_by_reload_or_retained_queued_callbacks(self):
        app = self.app()
        callback = self.queued_start(app)
        app.stop.set()
        self.change(app, 'reset')
        self.assert_disarmed(app)
        with patch.object(DrawBot.DrawBotApp, 'draw') as draw:
            self.assertFalse(callback())
        draw.assert_not_called()
        self.assertTrue(app.stop.is_set())
        self.assertEqual(app.mouse.mock_calls, [])

    def test_rejected_publications_and_stale_apply_leave_current_request_unchanged(self):
        for route in ('bad-import', 'reset-identity', 'save-failed', 'stale-ticket',
                      'old-selection', 'busy', 'closing'):
            with self.subTest(route=route):
                app = self.app()
                self.queued_import(app)
                request = app.pending_drop_in_import
                timers = dict(app.root.jobs)
                if route == 'bad-import':
                    with self.assertRaises(ProfilePortability.ProfilePortabilityError):
                        ProfilePortability.import_package_into_app(app, {})
                elif route == 'reset-identity':
                    with self.assertRaises(ProfilePortability.ProfilePortabilityError):
                        ProfilePortability.reset_profile(app, expected_name='Gartic Phone')
                elif route == 'save-failed':
                    with patch.object(app, 'save_settings', return_value=False), \
                            self.assertRaises(ProfilePortability.ProfilePortabilityError):
                        self.change(app, 'replace')
                else:
                    if route == 'busy': app.activity = 'planning'
                    if route == 'closing': app.closing = True
                    selected = 'Gartic Phone' if route == 'old-selection' else app.game.get()
                    if route == 'stale-ticket':
                        current = app.profile_change_ticket = object()
                        app._apply_profile_change(selected, ticket=object())
                        self.assertIs(app.profile_change_ticket, current)
                    else:
                        app._apply_profile_change(selected)
                self.assertTrue(DrawBot.DrawBotApp._manual_drop_in_armed(app))
                self.assertIs(app.pending_drop_in_import, request)
                self.assertIs(app.drop_in_start_context, request)
                self.assertEqual(app.root.jobs, timers)
                self.assertEqual(app.mouse.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
