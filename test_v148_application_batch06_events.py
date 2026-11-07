"""Stop owns the visible status until the actual worker has exited."""
import threading
import unittest
from unittest.mock import Mock,patch

from DrawBot import DrawBotApp
from test_v148_application_batch04_recovery import app_state
from test_v148_application_batch04_settings import Value


class CancelledStatusTests(unittest.TestCase):
    def app(self):
        app=app_state();app.activity='plan';app.paused=threading.Event()
        app.status=Value('Planning…');app.progress={'value':20}
        return app

    def test_queued_success_and_progress_cannot_replace_explicit_stopping_status(self):
        app=self.app()
        app.events.put(('status','Building preview…'))
        app.events.put(('progress',(10,10)))
        app.events.put(('status','Finished locally'))
        with patch.object(DrawBotApp,'_close_smart_drop_overlay'),\
             patch.object(DrawBotApp,'_disarm_manual_drop_in'),\
             patch.object(DrawBotApp,'_disarm_full_draw'),\
             patch.object(DrawBotApp,'_cancel_after_attr',return_value=False):
            DrawBotApp.cancel(app)
        self.assertEqual(app.status.get(),'Stopping…')
        while not app.events.empty():DrawBotApp._handle_event(app,*app.events.get_nowait())
        self.assertEqual(app.status.get(),'Stopping…')
        self.assertEqual(app.progress['value'],20)
        DrawBotApp._handle_event(app,'done','another-worker')
        self.assertEqual(app.status.get(),'Stopping…');self.assertEqual(app.activity,'plan')
        DrawBotApp._handle_event(app,'done','plan')
        self.assertEqual(app.status.get(),'Stopped.');self.assertIsNone(app.activity)
        DrawBotApp._handle_event(app,'status','Old status after completion')
        self.assertEqual(app.status.get(),'Stopped.')

    def test_normal_worker_updates_and_completion_keep_their_final_message(self):
        app=self.app()
        DrawBotApp._handle_event(app,'progress',(5,10))
        self.assertEqual(app.progress['value'],50)
        DrawBotApp._handle_event(app,'status','Preview ready')
        DrawBotApp._handle_event(app,'done','plan')
        self.assertEqual(app.status.get(),'Preview ready')
        self.assertIsNone(app.activity)

    def test_worker_error_without_user_stop_is_still_visible(self):
        app=self.app()
        DrawBotApp._handle_event(app,'status','Time limit reached; drawing stopped.')
        DrawBotApp._handle_event(app,'done','plan')
        self.assertEqual(app.status.get(),'Time limit reached; drawing stopped.')

    def test_stop_and_save_recording_retains_confirmed_completion_and_disk_errors(self):
        for message in ('Recording saved: sketch.gif','Operation failed: disk full'):
            app=self.app();app.activity='record';app.stop.set();app.status.set('Stopping…')
            DrawBotApp._handle_event(app,'terminal_status',('record',message))
            self.assertEqual(app.status.get(),'Stopping…')
            DrawBotApp._handle_event(app,'done','record')
            self.assertEqual(app.status.get(),message)
            self.assertIsNone(app._worker_terminal_status)

    def test_terminal_message_from_a_different_worker_cannot_override_stop(self):
        app=self.app();app.stop.set();app.status.set('Stopping…')
        DrawBotApp._handle_event(app,'terminal_status',('record','Recording saved: old.gif'))
        DrawBotApp._handle_event(app,'done','plan')
        self.assertEqual(app.status.get(),'Stopped.')


if __name__=='__main__':unittest.main()
