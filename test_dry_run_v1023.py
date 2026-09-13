import time
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

from DrawBot import DrawBotApp, execute_plan, make_plan
from Version import APP_VERSION, FILE_VERSION
from test_drawbot import Mouse, NoWait, options


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


class DryRunV1023Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_execute_plan_dry_run_moves_but_never_clicks(self):
        plan=make_plan(Image.new('RGBA',(4,2),'black'),(40,20),options())
        mouse=Mouse();events=[]
        execute_plan(plan,(100,100,40,20),[(10,i) for i in range(18)],mouse,NoWait(),threading.Event(),lambda *e:events.append(e),dry_run=True)
        actions=[a[0] for a in mouse.actions]
        self.assertIn('move', actions)
        self.assertNotIn('click', actions)
        self.assertNotIn('press', actions)
        self.assertNotIn('release', actions)
        self.assertFalse(mouse.held)
        self.assertTrue(any(e[0]=='status' and 'Dry run finished' in e[1] for e in events))

    def make_app(self):
        app=SimpleNamespace(
            activity=None,closing=False,original=object(),corners=[(10,10),(110,110)],
            target_window=(123,(0,0,300,300)),target_client_rect=(0,0,300,300),target_dpi=96,
            palette_ready=True,game=Value('Microsoft Paint'),paint_simple=Value(False),paint_tool=Value('Use current tool'),
            small_test_passed=True,full_draw_armed_until=0.0,draw_arm_after=None,
            safety_preflight_passed=True,safety_preflight_signature=None,safety_preflight_valid_until=time.monotonic()+60,
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
        app.safety_preflight_signature=DrawBotApp._current_safety_signature(app)
        return app

    def test_dry_run_is_optional_for_unlock(self):
        app=self.make_app()
        with patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            DrawBotApp.unlock_full_drawing(app)
        self.assertGreater(app.full_draw_armed_until,time.monotonic())
        self.assertIn('dry run',app.status.get().lower())
        app.dry_run_passed=True
        app.dry_run_signature=DrawBotApp._current_safety_signature(app)
        app.dry_run_valid_until=time.monotonic()+60
        with patch.object(DrawBotApp,'_verify_target_lock',return_value=True):
            DrawBotApp.unlock_full_drawing(app)
        self.assertGreater(app.full_draw_armed_until,time.monotonic())

    def test_dry_run_signature_invalidates_on_setup_change(self):
        app=self.make_app()
        app.dry_run_passed=True
        app.dry_run_signature=DrawBotApp._current_safety_signature(app)
        app.dry_run_valid_until=time.monotonic()+60
        self.assertTrue(DrawBotApp._dry_run_valid(app))
        app.corners=[(20,20),(120,120)]
        self.assertFalse(DrawBotApp._dry_run_valid(app))

if __name__ == '__main__': unittest.main()
