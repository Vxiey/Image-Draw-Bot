"""Area selection transfers crop ownership and cannot revive a cancelled setup."""
from contextlib import ExitStack
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from DrawBot import DrawBotApp
from test_v148_application_batch04_settings import Value


class AreaSelectionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.select=self.stack.enter_context(patch('RegionPicker.select_region'))
        self.stack.enter_context(patch('DrawBot.log_event'))
        anchors=SimpleNamespace(as_options=lambda:{},corner_count=0,triangle_count=0,
                                expected_triangles=6,confidence=0)
        self.stack.enter_context(patch('CanvasAnchorDetection.detect_canvas_anchors',return_value=anchors))
        root=Mock();root.after.return_value='auto-setup'
        self.app=SimpleNamespace(root=root,activity=None,closing=False,stop=threading.Event(),
            capture_job=None,set_busy=Mock(),corners=[],canvas_anchor_detection=None,
            target_window=None,target_client_rect=None,target_dpi=96,capture_target=Mock(),
            color_session_cache={},game=Value('Skribbl.io'),area_text=Value(''),status=Value(''),
            browser_auto_text=Value(''),save_settings=Mock(),_schedule_recovery_checkpoint=Mock(),
            _mark_plan_stale=Mock(),_maybe_auto_preview=Mock(),show_previews=Mock(),
            auto_calibrate_browser_profile=Mock())

    def start(self):
        DrawBotApp.set_boundary(self.app)
        return self.select.call_args.args[1:]

    def test_picker_observes_stop_and_shutdown_without_starting_when_closing(self):
        self.start()
        cancelled=self.select.call_args.kwargs['cancelled']
        self.assertFalse(cancelled());self.app.stop.set();self.assertTrue(cancelled())
        self.app.stop.clear();self.app.closing=True;self.assertTrue(cancelled())
        self.select.reset_mock();DrawBotApp.set_boundary(self.app)
        self.select.assert_not_called()

    def test_delivered_crop_is_closed_on_success_failure_and_late_stop(self):
        for fail,stop in ((False,False),(True,False),(False,True)):
            with self.subTest(fail=fail,stop=stop):
                self.app.stop.clear();self.app.capture_target.side_effect=OSError('target vanished') if fail else None
                selected,_=self.start()
                image=Image.new('RGB',(40,30),'white')
                if stop:self.app.stop.set()
                if fail or stop:
                    with self.assertRaises((OSError,InterruptedError)):
                        selected((100,100,140,130),image)
                else:selected((100,100,140,130),image)
                with self.assertRaises(ValueError):image.getpixel((0,0))

    def test_pending_auto_setup_rechecks_stop_profile_area_and_window_lifetime(self):
        selected,_=self.start()
        selected((100,100,140,130),Image.new('RGB',(40,30),'white'))
        callback=self.app.root.after.call_args.args[1]
        for change,restore in (
            (lambda:self.app.stop.set(),lambda:self.app.stop.clear()),
            (lambda:setattr(self.app,'closing',True),lambda:setattr(self.app,'closing',False)),
            (lambda:self.app.game.set('Other drawing app'),lambda:self.app.game.set('Skribbl.io')),
            (lambda:setattr(self.app,'corners',[]),lambda:setattr(self.app,'corners',[(100,100),(140,130)])),
            (lambda:setattr(self.app,'activity','draw'),lambda:setattr(self.app,'activity',None)),
        ):
            self.app.capture_job='auto-setup';change();callback();restore()
            self.app.auto_calibrate_browser_profile.assert_not_called()
        self.app.capture_job='auto-setup';callback()
        self.app.auto_calibrate_browser_profile.assert_called_once_with(automatic=True)
        callback();self.app.auto_calibrate_browser_profile.assert_called_once()

    def test_late_failure_during_shutdown_does_not_touch_destroyed_ui(self):
        _,failed=self.start();self.app.set_busy.reset_mock()
        self.app.closing=True;failed('cancelled')
        self.app.set_busy.assert_not_called();self.assertEqual(self.app.status.get(),'')


if __name__=='__main__':unittest.main()
