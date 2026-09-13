import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DrawBot import DrawBotApp
from Version import APP_VERSION, FILE_VERSION

class Value:
    def __init__(self,value=None): self.value=value
    def get(self): return self.value
    def set(self,value): self.value=value

class Button:
    def __init__(self): self.config={}
    def configure(self,**kwargs): self.config.update(kwargs)

class Root:
    def after(self,*args): return 'job'
    def after_cancel(self,*args): pass

class PreflightLockV1019Tests(unittest.TestCase):
    def make_app(self, *, test_passed=True, palette=True):
        app=SimpleNamespace(
            activity=None,closing=False,original=object(),corners=[(10,10),(110,110)],
            target_window=(123,(0,0,300,300)),target_client_rect=(0,0,300,300),target_dpi=96,
            palette_ready=palette,game=Value('Microsoft Paint'),paint_simple=Value(False),paint_tool=Value('Use current tool'),
            small_test_passed=test_passed,full_draw_armed_until=0.0,draw_arm_after=None,
            safety_preflight_passed=False,safety_preflight_signature=None,safety_preflight_valid_until=0.0,
            dry_run_passed=False,dry_run_signature=None,dry_run_valid_until=0.0,
            target_lock_passed=True,target_lock_fingerprint=None,target_lock_signature=None,
            status=Value(),summary=Value(),target_lock_text=Value(),root=Root(),start=Button(),start_secondary=Button(),start_unlock=Button(),start_unlock_secondary=Button(),
            target_lock_button=Button(),target_lock_secondary=Button())
        app.area=lambda: (10,10,100,100)
        app.target_lock_fingerprint=DrawBotApp._build_target_lock_fingerprint(app)
        app.target_lock_signature=DrawBotApp._target_lock_signature_from(app.target_lock_fingerprint)
        app._paint_tool_preflight_ready=lambda: True
        app._palette_preflight_ready=lambda: DrawBotApp._palette_preflight_ready(app)
        app._start_guard_ready=lambda require_image=True: DrawBotApp._start_guard_ready(app,require_image=require_image)
        app._refresh_start_buttons_text=lambda: DrawBotApp._refresh_start_buttons_text(app)
        app._disarm_full_draw=lambda reason='',update_text=True: DrawBotApp._disarm_full_draw(app,reason,update_text)
        app._full_draw_unlocked=lambda: DrawBotApp._full_draw_unlocked(app)
        app._refresh_target_for_draw=lambda: app.target_client_rect
        app.set_busy=lambda activity: None
        return app

    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_small_test_is_optional(self):
        app=self.make_app(test_passed=False)
        ready,message=DrawBotApp._start_guard_ready(app)
        self.assertTrue(ready)
        self.assertEqual(message,'Basic setup ready.')

    def test_preflight_passes_without_drawing_or_mouse(self):
        app=self.make_app()
        with patch.object(DrawBotApp,'draw') as draw, patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            result=DrawBotApp.run_safety_preflight(app)
        self.assertTrue(result)
        self.assertTrue(DrawBotApp._safety_preflight_valid(app))
        draw.assert_not_called()
        self.assertIn('passed',app.status.get().lower())

    def test_unlock_available_without_preflight(self):
        app=self.make_app()
        with patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            DrawBotApp.unlock_full_drawing(app)
        self.assertGreater(app.full_draw_armed_until,time.monotonic())
        self.assertIn('preflight',app.status.get().lower())

    def test_unlock_available_without_dry_run(self):
        app=self.make_app()
        with patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            self.assertTrue(DrawBotApp.run_safety_preflight(app))
            DrawBotApp.unlock_full_drawing(app)
        self.assertGreater(app.full_draw_armed_until,time.monotonic())
        self.assertIn('dry run',app.status.get().lower())

    def test_unlock_allowed_after_preflight_and_dry_run(self):
        app=self.make_app()
        with patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            self.assertTrue(DrawBotApp.run_safety_preflight(app))
        app.dry_run_passed=True
        app.dry_run_signature=DrawBotApp._current_safety_signature(app)
        app.dry_run_valid_until=time.monotonic()+60
        with patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            DrawBotApp.unlock_full_drawing(app)
        self.assertGreater(app.full_draw_armed_until,time.monotonic())

    def test_setup_signature_change_invalidates_preflight(self):
        app=self.make_app()
        with patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            self.assertTrue(DrawBotApp.run_safety_preflight(app))
        app.corners=[(20,20),(120,120)]
        self.assertFalse(DrawBotApp._safety_preflight_valid(app))

    def test_expired_preflight_is_invalid(self):
        app=self.make_app()
        with patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            self.assertTrue(DrawBotApp.run_safety_preflight(app))
        app.safety_preflight_valid_until=time.monotonic()-1
        self.assertFalse(DrawBotApp._safety_preflight_valid(app))

if __name__=='__main__': unittest.main()
