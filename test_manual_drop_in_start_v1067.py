import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DropInStart import DROP_IN_ACTION, action_for_import, can_arm, normalize_action
from DrawBot import DrawBotApp
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self, value=None): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class Root:
    def __init__(self): self.after_calls = []; self.cancelled = []
    def after(self, delay, func=None): self.after_calls.append((delay, func)); return f'after-{len(self.after_calls)}'
    def after_cancel(self, token): self.cancelled.append(token)


class Button:
    def __init__(self): self.config = {}
    def configure(self, **kwargs): self.config.update(kwargs)


def make_app(profile='Gartic Phone', image=None):
    app = SimpleNamespace(
        activity=None, closing=False, original=image,
        corners=[(10, 10), (510, 310)], target_window=(123, (0, 0, 800, 600)),
        game=Value(profile), palette_ready=True, paint_simple=Value(False), paint_tool=Value('Use current tool'),
        status=Value(), summary=Value(), drop_in_text=Value(), drop_in_button=Button(),
        manual_drop_in_start=Value(False), manual_drop_in_armed_until=0.0, manual_drop_in_after=None,
        drop_action_pending=None, root=Root(), preview_after=None, preview_render_after=None,
        draw_arm_after=None, start=Button(), start_secondary=Button(), start_unlock=Button(), start_unlock_secondary=Button(),
    )
    app._palette_preflight_ready = lambda: True
    app._paint_tool_preflight_ready = lambda: True
    app._refresh_target_for_draw = lambda *a, **kw: (0, 0, 800, 600)
    return app


class ManualDropInStartV1067Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_policy_accepts_only_new_explicit_action(self):
        self.assertEqual(action_for_import(armed=True), DROP_IN_ACTION)
        self.assertIsNone(action_for_import(armed=False))
        self.assertEqual(normalize_action(DROP_IN_ACTION), DROP_IN_ACTION)
        self.assertIsNone(normalize_action('Draw immediately'))

    def test_arm_browser_profile_without_image(self):
        app = make_app(image=None)
        self.assertTrue(DrawBotApp.arm_manual_drop_in(app))
        self.assertTrue(app.manual_drop_in_start.get())
        self.assertGreater(app.manual_drop_in_armed_until, time.monotonic())
        self.assertIn('armed', app.status.get().lower())

    def test_arm_rejects_paint(self):
        app = make_app(profile='Microsoft Paint')
        self.assertFalse(DrawBotApp.arm_manual_drop_in(app))
        self.assertFalse(app.manual_drop_in_start.get())
        self.assertIn('paint', app.status.get().lower())

    def test_loaded_image_starts_one_shot_when_armed(self):
        app = make_app(image=object())
        app.manual_drop_in_start.set(True)
        app.manual_drop_in_armed_until = time.monotonic() + 30
        app.drop_action_pending = DROP_IN_ACTION
        with patch.object(DrawBotApp, 'draw') as draw:
            self.assertTrue(DrawBotApp._run_pending_drop_in_start(app))
        draw.assert_called_once()
        self.assertIs(draw.call_args.args[0], app)
        self.assertTrue(draw.call_args.kwargs['user_initiated'])
        self.assertFalse(app.manual_drop_in_start.get())
        self.assertIsNone(app.drop_action_pending)

    def test_pending_drop_in_requires_live_arm(self):
        app = make_app(image=object())
        app.manual_drop_in_start.set(False)
        app.drop_action_pending = DROP_IN_ACTION
        with patch.object(DrawBotApp, 'draw') as draw:
            self.assertFalse(DrawBotApp._run_pending_drop_in_start(app))
        draw.assert_not_called()
        self.assertIn('expired', app.status.get().lower())

    def test_can_arm_message_never_uses_old_direct_draw(self):
        ok, message = can_arm('Gartic Phone', ready=False, message='Start locked: read the color palette first')
        self.assertFalse(ok)
        self.assertIn('Drop-In Start blocked', message)
        self.assertNotIn('Draw immediately', message)


if __name__ == '__main__':
    unittest.main()
