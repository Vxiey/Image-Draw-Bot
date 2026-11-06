"""Recovery preparation stays cancellable and cannot revive cleared work."""
import io
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

from PIL import Image
from DrawBot import DrawBotApp


def app_state():
    app=SimpleNamespace(closing=False,activity=None,shutdown_complete=False,stop=threading.Event(),
        status=Mock(),root=Mock(),events=queue.Queue(),original=None,pending_clear_drawing=None,
        worker=None,screen_task_window=None)
    def set_busy(value):app.activity=value
    app.set_busy=Mock(side_effect=set_busy)
    return app


class RecoveryWorkflowTests(unittest.TestCase):
    def test_current_safe_preferences_survive_snapshot_roundtrip_without_authorization(self):
        import SessionRecovery as recovery
        from test_v148_application_batch04_settings import Value
        values={'adaptive_deadline_renderer':False,'deadline_safety_reserve':'12',
                'use_region_fill_engine':False,'fill_aggressiveness':'Conservative',
                'quick_sketch_style':'Detailed','quick_sketch_fill_preference':'Contour First',
                'hybrid_mode':'Off','gartic_opacity':'40%','preview_detail_level':'Balanced'}
        app=app_state()
        for key,value in dict(values,preview_mode='Automatic',full_draw_armed_until=10**12).items():
            setattr(app,key,Value(value))
        options=DrawBotApp._recovery_option_snapshot(app)
        self.assertEqual(options,values)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(recovery,'RECOVERY_DIR',root),patch.object(recovery,'STATE_FILE',root/'state.json'),\
                 patch.object(recovery,'IMAGE_FILE',root/'last-image.png'),patch.object(recovery,'RENDER_FILE',root/'render.json'):
                recovery.save_snapshot(profile='Other drawing app',options=options)
                self.assertEqual(recovery.load_snapshot()['options'],values)

    def test_recovery_decode_is_deferred_until_tracked_worker_runs(self):
        app=app_state();jobs=[]
        def begin(activity,task):app.activity=activity;jobs.append(task);return True
        app.begin_worker=Mock(side_effect=begin)
        state={'profile':'Other drawing app','options':{},'has_image':True,'image_sha256':'a'*64}
        image=Image.new('RGBA',(2,2))
        with patch('SessionRecovery.load_snapshot',return_value=state),patch('SessionRecovery.load_cached_image',return_value=image) as load,patch('DrawBot.messagebox.askyesno',return_value=True),patch('DrawBot.previous_run_unclean',return_value=True),patch.object(DrawBotApp,'_apply_recovery_snapshot') as restore:
            DrawBotApp.offer_safe_session_recovery(app)
            load.assert_not_called();restore.assert_not_called()
            app.begin_worker.assert_called_once();self.assertEqual(app.activity,'recovery-load')
            jobs[0]();kind,value=app.events.get_nowait()
            load.assert_called_once_with(expected_sha256='a'*64,cancelled=app.stop.is_set)
            DrawBotApp._handle_event(app,kind,value);restore.assert_not_called()
            DrawBotApp._handle_event(app,'done','recovery-load')
            restore.assert_called_once_with(app,state,recovered_image=image)
            self.assertIsNone(app.activity)
        image.close()

    def test_dialog_result_cannot_replace_an_operation_started_while_modal(self):
        app=app_state();app.begin_worker=Mock()
        def answer(*args,**kwargs):app.activity='draw';return True
        with patch('SessionRecovery.load_snapshot',return_value={'has_image':True}),patch('DrawBot.messagebox.askyesno',side_effect=answer),patch('SessionRecovery.load_cached_image') as load:
            DrawBotApp.offer_safe_session_recovery(app)
        load.assert_not_called();app.begin_worker.assert_not_called()

    def test_stop_between_recovery_result_and_completion_discards_owned_image(self):
        app=app_state();app.activity='recovery-load';image=Image.new('RGB',(2,2))
        DrawBotApp._handle_event(app,'recovery_loaded',({},image));app.stop.set()
        with patch.object(DrawBotApp,'_apply_recovery_snapshot') as restore:
            DrawBotApp._handle_event(app,'done','recovery-load')
        restore.assert_not_called();self.assertIsNone(app.recovery_loaded_pending)
        with self.assertRaises(ValueError):image.getpixel((0,0))

    def test_explicit_clear_cancels_queued_save_and_forgets_resume_only_on_success(self):
        app=app_state();app.recovery_checkpoint_after='pending';app.recovery_image_pending=True
        app.pending_render_resume={'completed_count':3}
        with patch('SessionRecovery.clear_snapshot') as clear,patch('DrawBot.log_event'):
            DrawBotApp.clear_recovery_snapshot(app)
        clear.assert_called_once();app.root.after_cancel.assert_called_once_with('pending')
        self.assertIsNone(app.recovery_checkpoint_after);self.assertFalse(app.recovery_image_pending)
        self.assertTrue(app._suppress_recovery);self.assertIsNone(app.pending_render_resume)
        with patch('SessionRecovery.save_snapshot') as save:
            DrawBotApp._save_recovery_checkpoint(app,include_image=True)
        save.assert_not_called()

    def test_failed_clear_retains_in_memory_resume(self):
        app=app_state();resume={'completed_count':3};app.pending_render_resume=resume
        with patch('SessionRecovery.clear_snapshot',side_effect=OSError('locked')):
            DrawBotApp.clear_recovery_snapshot(app)
        self.assertIs(app.pending_render_resume,resume)
        self.assertIn('Could not clear',app.status.set.call_args.args[0])

    def test_recovery_failure_disarms_before_loading_or_applying_state(self):
        app=app_state();app.mouse=Mock();app.game=Mock();app.game.get.return_value='Other drawing app'
        app.preview_mode=Mock()
        order=[]
        with patch.object(DrawBotApp,'_disarm_full_draw',side_effect=lambda *a,**k:order.append('disarm')),patch('SessionRecovery.load_cached_image',side_effect=MemoryError('decode')):
            with self.assertRaises(MemoryError):DrawBotApp._apply_recovery_snapshot(app,{'has_image':True,'profile':'Other drawing app','options':{}})
        self.assertEqual(order,['disarm']);app.mouse.disarm_input.assert_called_once()


class RecoveryCancellationTests(unittest.TestCase):
    def test_hashing_observes_stop_between_chunks(self):
        import SessionRecovery as recovery
        stream=io.BytesIO(b'a'*(65536*10));calls=0
        def cancelled():
            nonlocal calls
            calls+=1
            return calls==2
        with self.assertRaises(InterruptedError):recovery._stream_digest(stream,cancelled=cancelled)
        self.assertEqual(stream.tell(),65536*2)

    def test_stop_after_decode_closes_unpublished_image_and_propagates(self):
        import SessionRecovery as recovery
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'last-image.png'
            with Image.new('RGB',(3,2)) as source:source.save(path)
            stopped=False;converted=[];convert=Image.Image.convert
            def interrupted(image,*args,**kwargs):
                nonlocal stopped
                result=convert(image,*args,**kwargs);converted.append(result);stopped=True;return result
            with patch.object(recovery,'IMAGE_FILE',path),patch.object(Image.Image,'convert',interrupted):
                with self.assertRaises(InterruptedError):recovery.load_cached_image(expected_sha256=None,cancelled=lambda:stopped)
            self.assertEqual(len(converted),1)
            with self.assertRaises(ValueError):converted[0].getpixel((0,0))


class DiscardedResultOwnershipTests(unittest.TestCase):
    def test_cancelled_image_results_are_closed_without_closing_current_image(self):
        app=app_state();app.stop.set();app.original=Image.new('RGB',(2,2),'red')
        image=Image.new('RGB',(2,2),'blue')
        DrawBotApp._handle_event(app,'loaded',(image,'file',None))
        with self.assertRaises(ValueError):image.getpixel((0,0))
        self.assertEqual(app.original.getpixel((0,0)),(255,0,0))
        DrawBotApp._discard_worker_result(app,'loaded',(app.original,'shared',None))
        self.assertEqual(app.original.getpixel((0,0)),(255,0,0));app.original.close()

    def test_stale_plan_releases_owned_preview_and_keeps_shared_current_source(self):
        app=app_state();app.preview_generation=5;app.original=Image.new('RGB',(2,2),'red')
        preview=Image.new('RGB',(2,2),'blue')
        value={'preview_generation':4,'preview':preview,'image':app.original,'count':1,'estimate':1}
        DrawBotApp._handle_event(app,'planned',value)
        with self.assertRaises(ValueError):preview.getpixel((0,0))
        self.assertEqual(app.original.getpixel((0,0)),(255,0,0));app.original.close()


if __name__=='__main__':unittest.main()
