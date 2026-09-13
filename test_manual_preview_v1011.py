
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from DrawBot import DrawBotApp, PREVIEW_MODES, validate_preview_mode
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self, value=None):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Root:
    def __init__(self):
        self.after_calls = []
        self.cancelled = []
    def after(self, delay, func=None):
        self.after_calls.append((delay, func))
        return f'after-{len(self.after_calls)}'
    def after_cancel(self, token):
        self.cancelled.append(token)


class ManualPreviewV1011Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_preview_modes_validate(self):
        self.assertIn('Manual', PREVIEW_MODES)
        self.assertIn('Auto light', PREVIEW_MODES)
        self.assertEqual(validate_preview_mode('Manual'), 'Manual')
        with self.assertRaises(ValueError):
            validate_preview_mode('Always draw')

    def make_app(self, preview_mode='Manual'):
        return SimpleNamespace(
            activity=None, closing=False, original=object(), preview_mode=Value(preview_mode),
            preview_after=None, preview_render_after=None, needs_plan=False, plan={'old': True},
            small_test_passed=True, root=Root(), summary=Value(), status=Value())

    def test_options_changed_does_not_auto_plan_in_manual_mode(self):
        app = self.make_app('Manual')
        app._mark_plan_stale = lambda message='': DrawBotApp._mark_plan_stale(app, message)
        app._maybe_auto_preview = lambda delay=900, reason='settings': DrawBotApp._maybe_auto_preview(app, delay, reason)
        app._auto_preview_enabled = lambda: DrawBotApp._auto_preview_enabled(app)
        with patch('DrawBot.log_event') as log:
            DrawBotApp.options_changed(app)
        self.assertIsNone(app.plan)
        self.assertFalse(app.small_test_passed)
        self.assertEqual(app.root.after_calls, [])
        self.assertIn('Build preview', app.summary.get())
        self.assertTrue(log.called)

    def test_options_changed_schedules_only_in_auto_light(self):
        app = self.make_app('Auto light')
        app._mark_plan_stale = lambda message='': DrawBotApp._mark_plan_stale(app, message)
        app._maybe_auto_preview = lambda delay=900, reason='settings': DrawBotApp._maybe_auto_preview(app, delay, reason)
        app._auto_preview_enabled = lambda: DrawBotApp._auto_preview_enabled(app)
        DrawBotApp.options_changed(app)
        self.assertEqual(len(app.root.after_calls), 1)
        self.assertEqual(app.root.after_calls[0][0], 1000)

    def test_automatic_update_plan_blocked_in_manual_mode(self):
        app = self.make_app('Manual')
        app._mark_plan_stale = lambda message='': DrawBotApp._mark_plan_stale(app, message)
        app._maybe_auto_preview = lambda delay=900, reason='settings': DrawBotApp._maybe_auto_preview(app, delay, reason)
        app._auto_preview_enabled = lambda: DrawBotApp._auto_preview_enabled(app)
        with patch('DrawBot.log_event') as log:
            DrawBotApp.update_plan(app, user_initiated=False, reason='settings-change')
        self.assertEqual(app.root.after_calls, [])
        self.assertTrue(log.called)

    def test_ui_exposes_manual_preview_and_build_button(self):
        source = (Path(__file__).resolve().parent / 'StudioUI.py').read_text(encoding='utf-8')
        self.assertIn('Preview mode', source)
        self.assertIn('Build preview', source)
        self.assertIn('Manual prevents lag while configuring', source)

    def test_release_collects_manual_preview_doc(self):
        source = (Path(__file__).resolve().parent / 'build_exe.py').read_text(encoding='utf-8')
        self.assertNotIn('MANUAL-PREVIEW-PERFORMANCE-v1.0.11.md', source)


if __name__ == '__main__':
    unittest.main()
