import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DrawBot import DrawBotApp
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self, value=None): self.value=value
    def get(self): return self.value
    def set(self, value): self.value=value

class Button:
    def __init__(self): self.config={}
    def configure(self, **kwargs): self.config.update(kwargs)

class Root:
    def after(self, *args): return 'job'
    def after_cancel(self, *args): pass


class TargetLockV1024Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def make_app(self):
        image=SimpleNamespace(size=(64, 64))
        app=SimpleNamespace(
            activity=None, closing=False, original=image,
            corners=[(20, 30), (120, 130)], target_window=(123, (0, 0, 400, 400)),
            target_client_rect=(10, 10, 390, 390), target_dpi=96,
            palette_ready=True, game=Value('Other drawing app'), paint_simple=Value(False),
            paint_tool=Value('Use current tool'), calibration_path='unused.json',
            small_test_passed=True, full_draw_armed_until=0.0, draw_arm_after=None,
            safety_preflight_passed=False, safety_preflight_signature=None, safety_preflight_valid_until=0.0,
            dry_run_passed=False, dry_run_signature=None, dry_run_valid_until=0.0,
            target_lock_passed=False, target_lock_fingerprint=None, target_lock_signature=None,
            status=Value(), summary=Value(), target_lock_text=Value(), root=Root(), controls=[],
            start=Button(), start_secondary=Button(), start_unlock=Button(), start_unlock_secondary=Button(),
            target_lock_button=Button(), target_lock_secondary=Button(), safety_preflight_button=Button(), safety_preflight_secondary=Button(),
            dry_run_button=Button(), dry_run_secondary=Button(), next_step=Value())
        app.area=lambda: (20,30,100,100)
        app._paint_tool_preflight_ready=lambda: True
        app._palette_preflight_ready=lambda: DrawBotApp._palette_preflight_ready(app)
        app._start_guard_ready=lambda require_image=True: DrawBotApp._start_guard_ready(app,require_image=require_image)
        app._disarm_full_draw=lambda reason='',update_text=True: DrawBotApp._disarm_full_draw(app,reason,update_text)
        app._full_draw_unlocked=lambda: DrawBotApp._full_draw_unlocked(app)
        app._refresh_start_buttons_text=lambda: DrawBotApp._refresh_start_buttons_text(app)
        app._refresh_target_lock_text=lambda: DrawBotApp._refresh_target_lock_text(app)
        app.set_busy=lambda activity: None
        return app

    def lock_app(self, app):
        fp=DrawBotApp._build_target_lock_fingerprint(app)
        app.target_lock_passed=True
        app.target_lock_fingerprint=fp
        app.target_lock_signature=DrawBotApp._target_lock_signature_from(fp)

    def test_fingerprint_includes_target_geometry_area_and_image(self):
        app=self.make_app(); self.lock_app(app)
        self.assertTrue(DrawBotApp._target_lock_valid(app))
        app.corners=[(21,30),(121,130)]
        self.assertFalse(DrawBotApp._target_lock_valid(app))

    def test_preflight_is_blocked_until_setup_lock_exists(self):
        app=self.make_app()
        DrawBotApp.run_safety_preflight(app)
        self.assertIn('Lock setup', app.status.get())
        self.assertFalse(app.safety_preflight_passed)

    def test_window_move_rebases_target_lock_before_native_input(self):
        app=self.make_app(); self.lock_app(app)
        with patch('TargetCapture.probe_handle_isolated', return_value={'handle':123,'rect':(5,0,405,400),'client_rect':(15,10,395,390),'dpi':96}), patch('DrawBot.load_calibration', return_value={'count':0}):
            self.assertTrue(DrawBotApp._verify_target_lock(app))
        self.assertTrue(app.target_lock_passed)
        self.assertEqual(app.corners,[(25,30),(125,130)])

    def test_ui_source_has_lock_buttons_and_new_flow_text(self):
        from pathlib import Path
        source=(Path(__file__).resolve().parent/'StudioUI.py').read_text(encoding='utf-8')
        self.assertIn('Lock setup', source)
        self.assertIn('a.target_lock_button', source)
        self.assertIn('Paint: load an image, then Prepare Paint & draw.', source)


if __name__ == '__main__': unittest.main()
