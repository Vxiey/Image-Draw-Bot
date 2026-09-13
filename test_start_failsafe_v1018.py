import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DrawBot import DrawBotApp
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self, value=None): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class Button:
    def __init__(self): self.config = {}
    def configure(self, **kwargs): self.config.update(kwargs)


class StartFailsafeV1018Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def make_app(self, *, image=True, area=True, palette=True, unlocked=False):
        return SimpleNamespace(
            activity=None, closing=False, original=(object() if image else None),
            corners=[(0,0),(100,100)] if area else [], target_window=((123,(0,0,200,200)) if area else None), palette_ready=palette,
            game=Value('Other drawing app'), paint_simple=Value(False), paint_tool=Value('Auto (recommended)'),
            full_draw_armed_until=(time.monotonic()+10 if unlocked else 0.0), draw_arm_after=None,
            status=Value(), summary=Value(), start=Button(), start_secondary=Button(),
            start_unlock=Button(), start_unlock_secondary=Button(), small_test_passed=True,
            safety_preflight_passed=True, safety_preflight_signature=None, safety_preflight_valid_until=time.monotonic()+60, dry_run_passed=True, dry_run_signature=None, dry_run_valid_until=time.monotonic()+60,
            target_lock_passed=True,target_lock_fingerprint=None,target_lock_signature=None,target_lock_text=Value(),target_lock_button=Button(),target_lock_secondary=Button(),target_client_rect=(0,0,200,200),target_dpi=96)

    def wire(self, app):
        app._paint_tool_preflight_ready = lambda: True
        app._palette_preflight_ready = lambda: DrawBotApp._palette_preflight_ready(app)
        app._start_guard_ready = lambda require_image=True: DrawBotApp._start_guard_ready(app, require_image=require_image)
        app._refresh_start_buttons_text = lambda: DrawBotApp._refresh_start_buttons_text(app)
        app._disarm_full_draw = lambda reason='', update_text=True: DrawBotApp._disarm_full_draw(app, reason, update_text)
        app._full_draw_unlocked = lambda: DrawBotApp._full_draw_unlocked(app)
        app.area = lambda: (0,0,100,100)
        if app.target_window is not None:
            app.target_lock_fingerprint=DrawBotApp._build_target_lock_fingerprint(app)
            app.target_lock_signature=DrawBotApp._target_lock_signature_from(app.target_lock_fingerprint)
        app.safety_preflight_signature = DrawBotApp._current_safety_signature(app)
        app.dry_run_signature = DrawBotApp._current_safety_signature(app)

    def test_start_without_unlock_is_blocked(self):
        app=self.make_app(); self.wire(app)
        with patch.object(DrawBotApp, 'draw') as draw, patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            DrawBotApp.start_full_drawing(app)
        draw.assert_not_called()
        self.assertIn('Unlock', app.status.get())

    def test_unlock_requires_complete_setup(self):
        app=self.make_app(palette=False); self.wire(app)
        with patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            DrawBotApp.unlock_full_drawing(app)
        self.assertEqual(app.full_draw_armed_until, 0.0)
        self.assertIn('palette', app.status.get().lower())

    def test_refresh_text_uses_separate_unlock_and_start_buttons(self):
        app=self.make_app(unlocked=True); self.wire(app)
        DrawBotApp._refresh_start_buttons_text(app)
        self.assertEqual(app.start.config['text'], '▶️  Start Drawing')
        self.assertEqual(app.start_unlock.config['text'], '✓  Unlocked for 12s')

    def test_source_has_two_separate_buttons(self):
        import pathlib
        source=(pathlib.Path(__file__).resolve().parent/'StudioUI.py').read_text(encoding='utf-8')
        self.assertIn('Unlock full drawing', source)
        self.assertIn('Start locked', source)
        self.assertIn('a.start_unlock', source)
        self.assertIn('a.dry_run_button', source)
        self.assertIn('a.start = btn', source)


if __name__ == '__main__': unittest.main()
