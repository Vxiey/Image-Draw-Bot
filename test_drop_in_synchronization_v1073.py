import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from DropInStart import DROP_IN_ACTION
from DropInSynchronization import (
    AUTO_RECALIBRATING, AUTO_SETUP_RUNNING, VISUAL_PREFLIGHT_RUNNING,
    DRAW_PENDING, READY_TO_DRAW, make_request, target_fingerprint,
)
from DrawBot import DrawBotApp
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self, value=None): self.value=value
    def get(self): return self.value
    def set(self, value): self.value=value


class Root:
    def __init__(self): self.after_calls=[];self.cancelled=[]
    def after(self, delay, func=None): self.after_calls.append((delay,func)); return f'a{len(self.after_calls)}'
    def after_cancel(self, token): self.cancelled.append(token)


class Button:
    def configure(self, **kwargs): pass


def make_app(activity=None, phase=READY_TO_DRAW):
    now=time.monotonic()
    app=SimpleNamespace(
        activity=activity, closing=False, stop=SimpleNamespace(is_set=lambda:False), original=None,
        game=Value('Gartic Phone'), target_window=(123,(0,0,1200,800)), target_client_rect=(0,30,1200,800), target_dpi=96,
        manual_drop_in_start=Value(True), manual_drop_in_armed_until=now+120, manual_drop_in_after=None,
        pending_drop_in_import=None, pending_drop_in_after=None, drop_in_start_context=None,
        drop_in_sync_phase=phase, drop_action_pending=None, drop_in_text=Value(), status=Value(), summary=Value(),
        root=Root(), drop_in_button=Button(), controls=[], corners=[(400,200),(1100,700)], palette_ready=True,
        paint_simple=Value(False), paint_tool=Value('Use current tool'), worker=None, preview_after=None, preview_render_after=None,
        draw_arm_after=None, start=Button(), start_secondary=Button(), start_unlock=Button(), start_unlock_secondary=Button(),
    )
    app._palette_preflight_ready=lambda:True
    app._paint_tool_preflight_ready=lambda:True
    app._refresh_target_for_draw=lambda *a,**k: app.target_client_rect
    return app


class DropInSynchronizationV1073Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29');self.assertEqual(FILE_VERSION,'1.0.145')

    def _queue_during(self, activity=None, phase=READY_TO_DRAW, label='one.png'):
        app=make_app(activity,phase)
        with patch.object(DrawBotApp,'begin_worker') as begin:
            result=DrawBotApp.load_source(app,object(),label,action=DROP_IN_ACTION)
        self.assertTrue(result)
        begin.assert_not_called()
        self.assertIsNotNone(app.pending_drop_in_import)
        return app

    def test_drop_under_auto_setup_waits(self):
        app=self._queue_during(activity='browser-auto-calibration',phase=AUTO_SETUP_RUNNING)
        self.assertIn('waiting',app.status.get().lower())

    def test_drop_under_visual_preflight_waits(self):
        app=self._queue_during(phase=VISUAL_PREFLIGHT_RUNNING)
        self.assertIn('visual preflight',app.status.get().lower())

    def test_drop_under_auto_recalibration_waits(self):
        app=self._queue_during(phase=AUTO_RECALIBRATING)
        self.assertIn('recalibration',app.status.get().lower())

    def test_target_changed_while_waiting_cancels(self):
        app=make_app(activity=None,phase=DRAW_PENDING)
        fp=target_fingerprint(app.game.get(),app.target_window,app.target_client_rect,app.target_dpi)
        app.pending_drop_in_import=make_request(object(),'queued.png',DROP_IN_ACTION,fp,now=time.monotonic())
        app.target_window=(999,(0,0,1200,800))
        with patch.object(DrawBotApp,'load_source') as load:
            self.assertFalse(DrawBotApp._resume_pending_drop_in_import(app))
        load.assert_not_called()
        self.assertIsNone(app.pending_drop_in_import)
        self.assertFalse(app.manual_drop_in_start.get())
        self.assertIn('target changed',app.status.get().lower())

    def test_new_image_replaces_pending_image(self):
        app=make_app(activity='browser-auto-calibration',phase=AUTO_SETUP_RUNNING)
        with patch.object(DrawBotApp,'begin_worker'):
            DrawBotApp.load_source(app,'first','first.png',action=DROP_IN_ACTION)
            first=app.pending_drop_in_import
            DrawBotApp.load_source(app,'second','second.png',action=DROP_IN_ACTION)
        self.assertEqual(app.pending_drop_in_import.source,'second')
        self.assertEqual(app.pending_drop_in_import.label,'second.png')
        self.assertGreater(app.pending_drop_in_import.sequence,first.sequence)
        self.assertIn('latest image',app.status.get().lower())


if __name__=='__main__': unittest.main()
