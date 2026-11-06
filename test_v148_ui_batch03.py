"""Image editing and export lifecycle regressions without desktop input."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import queue
import threading
import unittest
from unittest.mock import Mock,patch

from PIL import Image

from BackgroundRemoval import BackgroundRemovalResult
from DrawBot import DrawBotApp
from RuntimePaths import atomic_binary_writer
from UiTransactionRuntime import UiTransaction, MAX_HISTORY, MAX_DETAIL
from WorkspaceLayout import fit_window,window_size
from PreviewDeck import PreviewDeck
from test_v148_ui_lifecycle_batch02 import ui_app


def app_for_edit():
    app=ui_app();app.background_removal_original=None;app.background_removal_meta=None
    app.events=queue.Queue();app.plan={'preview':Image.new('RGB',(5,4),'blue')}
    return app


class WindowGeometryTests(unittest.TestCase):
    def test_initial_geometry_and_minimum_fit_scaled_small_displays(self):
        for screen in ((800,600),(1024,768),(1366,768),(1920,1080)):
            for scale in (1,1.25,1.5,2,3):
                root=Mock();root.winfo_screenwidth.return_value=screen[0];root.winfo_screenheight.return_value=screen[1]
                root._get_window_scaling.return_value=scale
                size=fit_window(root,preferred=(1560,960),minimum=(1080,700),margin=(70,90))
                self.assertLessEqual(size[0]*scale,screen[0]-70)
                self.assertLessEqual(size[1]*scale,screen[1]-90)
                self.assertTrue(all(a<=b for a,b in zip(root.minsize.call_args.args,size)))
                root.geometry.assert_called_once_with(f'{size[0]}x{size[1]}')

    def test_studio_builder_uses_scaled_geometry_before_constructing_widgets(self):
        from StudioUI import build_ui
        root=Mock();root.winfo_screenwidth.return_value=1024;root.winfo_screenheight.return_value=768
        root._get_window_scaling.return_value=1.5
        with patch('StudioUI.ctk.set_appearance_mode'),patch('StudioUI.ttk.Style',side_effect=RuntimeError('end geometry probe')):
            with self.assertRaisesRegex(RuntimeError,'geometry probe'):build_ui(SimpleNamespace(root=root),{}, {})
        width,height=map(int,root.geometry.call_args.args[0].split('x'))
        self.assertLessEqual(width*1.5,954);self.assertLessEqual(height*1.5,678)

    def test_preview_page_failure_keeps_previous_page_visible_and_selected(self):
        deck=object.__new__(PreviewDeck);deck.pages={'Original':Mock(),'Result':Mock()}
        deck._visible_name='Original';deck.current=Mock()
        deck.pages['Result'].pack.side_effect=RuntimeError('page layout failed')
        with self.assertRaisesRegex(RuntimeError,'page layout failed'):deck.set('Result')
        deck.pages['Original'].pack_forget.assert_not_called()
        self.assertEqual(deck._visible_name,'Original');deck.current.set.assert_called_once_with('Original')

    def test_failed_page_registration_rolls_back_registry_and_destroys_widget(self):
        deck=object.__new__(PreviewDeck);deck.pages={'Original':Mock()};deck._visible_name='Original'
        deck.current=Mock();deck.host=Mock();deck.selector=Mock();deck.selector.configure.side_effect=[RuntimeError('menu failed'),None]
        page=Mock()
        with patch('PreviewDeck.ctk.CTkFrame',return_value=page),self.assertRaisesRegex(RuntimeError,'menu failed'):deck.add('Result')
        self.assertEqual(list(deck.pages),['Original']);page.destroy.assert_called_once()


class TransactionEvidenceTests(unittest.TestCase):
    def test_invalid_metadata_cannot_partly_change_the_transaction_state(self):
        tx=UiTransaction();tx.transition('OPEN_DIALOG',attempt=1,item_index=2)
        before=tx.as_dict()
        for value in (True,'3',1.5,float('nan'),-1):
            with self.subTest(value=value),self.assertRaises(ValueError):tx.transition('DONE',attempt=value)
            self.assertEqual(tx.as_dict(),before)

    def test_retry_contract_rejects_unusable_attempt_counts_before_work(self):
        for value in (True,'3',2.5,float('inf'),0,-1):
            with self.subTest(value=value),self.assertRaises(ValueError):UiTransaction(max_attempts=value)

    def test_retry_validates_item_identity_before_calling_input_or_recovery(self):
        for value in (-1,True,'1',1.5,float('nan')):
            operation=Mock();recover=Mock()
            with self.subTest(value=value),self.assertRaises(ValueError):UiTransaction().retry(operation,item_index=value,recover=recover)
            operation.assert_not_called();recover.assert_not_called()

    def test_long_transactions_keep_recent_bounded_telemetry_and_all_observer_calls(self):
        observer=Mock();tx=UiTransaction(on_state=observer)
        for index in range(MAX_HISTORY+10):tx.transition('WRITE_VALUE',item_index=index,detail='x'*(MAX_DETAIL+50))
        data=tx.as_dict()
        self.assertEqual(len(data['events']),MAX_HISTORY);self.assertEqual(data['events_dropped'],10)
        self.assertEqual(data['events'][0]['item_index'],10)
        self.assertEqual(data['events'][-1]['item_index'],MAX_HISTORY+9)
        self.assertTrue(all(len(event['detail'])<=MAX_DETAIL for event in data['events']))
        self.assertEqual(observer.call_count,MAX_HISTORY+10)

    def test_failure_observer_cannot_replace_the_original_operation_error(self):
        original=ValueError('RGB verification failed')
        tx=UiTransaction(max_attempts=1,on_state=Mock(side_effect=RuntimeError('observer failed')))
        with self.assertRaises(ValueError) as raised:tx.retry(Mock(side_effect=original))
        self.assertIs(raised.exception,original);self.assertEqual(tx.state,'FAILED')

    def test_nonretryable_and_recovery_errors_are_terminal_without_repeating_input(self):
        for recovery in (False,True):
            tx=UiTransaction();operation=Mock(side_effect=ValueError('transient') if recovery else OSError('native failed'))
            recover=Mock(side_effect=RuntimeError('recovery failed')) if recovery else None
            with self.subTest(recovery=recovery),self.assertRaises(RuntimeError if recovery else OSError):tx.retry(operation,recover=recover)
            operation.assert_called_once();self.assertEqual(tx.state,'FAILED')


class ImageExportTests(unittest.TestCase):
    def test_failed_streamed_output_preserves_existing_file_and_cleans_stage(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png';path.write_bytes(b'old-complete-file')
            with self.assertRaisesRegex(OSError,'disk full'):
                with atomic_binary_writer(path) as stream:
                    stream.write(b'partial-new-image')
                    raise OSError('disk full')
            self.assertEqual(path.read_bytes(),b'old-complete-file')
            self.assertEqual(list(Path(tmp).iterdir()),[path])

    def test_stop_during_encoding_preserves_old_destination(self):
        stop=threading.Event()
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png';path.write_bytes(b'old')
            with self.assertRaises(InterruptedError):
                with atomic_binary_writer(path,cancelled=stop.is_set) as stream:
                    stream.write(b'new');stop.set()
            self.assertEqual(path.read_bytes(),b'old')
            self.assertEqual(list(Path(tmp).iterdir()),[path])

    def test_stop_while_waiting_for_another_publisher_does_not_replace_the_file(self):
        import RuntimePaths as runtime
        stop=threading.Event();publishing=threading.Event();errors=[];replace=runtime._replace_with_retry
        def observed(*args,**kwargs):
            publishing.set();return replace(*args,**kwargs)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'export.png';path.write_bytes(b'old')
            def work():
                try:
                    with atomic_binary_writer(path,cancelled=stop.is_set) as stream:stream.write(b'new')
                except BaseException as error:errors.append(error)
            with patch.object(runtime,'_replace_with_retry',side_effect=observed):
                with runtime._PUBLICATION_LOCK:
                    thread=threading.Thread(target=work);thread.start()
                    self.assertTrue(publishing.wait(2));stop.set()
                thread.join(2)
            self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
            self.assertIsInstance(errors[0],InterruptedError)
            self.assertEqual(path.read_bytes(),b'old');self.assertEqual(list(Path(tmp).iterdir()),[path])

    def test_png_export_uses_worker_and_decodes_after_atomic_publication(self):
        app=app_for_edit();work=[];app.begin_worker=lambda kind,task:work.append((kind,task)) or True
        with TemporaryDirectory() as tmp,patch('DrawBot.filedialog.asksaveasfilename',return_value=str(Path(tmp)/'export.png')):
            self.assertTrue(DrawBotApp.save_png_copy(app))
            path=Path(tmp)/'export.png'
            self.assertFalse(path.exists())
            self.assertEqual(work[0][0],'png-export');work[0][1]()
            with Image.open(path) as image:
                self.assertEqual(image.convert('RGBA').tobytes(),app.original.tobytes())
            self.assertEqual(app.events.get_nowait(),('png_saved',str(path)))

    def test_export_preview_encodes_off_ui_thread_and_uses_a_snapshot(self):
        app=app_for_edit();work=[];app.begin_worker=lambda kind,task:work.append((kind,task)) or True
        with TemporaryDirectory() as tmp,patch('DrawBot.filedialog.asksaveasfilename',return_value=str(Path(tmp)/'preview.png')):
            self.assertTrue(DrawBotApp.export_preview(app))
            self.assertEqual(work[0][0],'preview-export')
            app.plan['preview'].paste('red',(0,0,5,4))
            work[0][1]()
            with Image.open(Path(tmp)/'preview.png') as image:self.assertEqual(image.getpixel((0,0)),(0,0,255))
            self.assertEqual(app.events.get_nowait(),('status','Simulated final saved as PNG.'))

    def test_refused_workers_release_export_and_edit_snapshots(self):
        copy=Image.Image.copy
        for operation in ('save_png_copy','export_preview','remove_image_background'):
            images=[];app=app_for_edit();app.begin_worker=lambda *args:False
            def traced(image):
                result=copy(image);images.append(result);return result
            with self.subTest(operation=operation),patch('DrawBot.filedialog.asksaveasfilename',return_value='unused.png'),patch.object(Image.Image,'copy',traced):
                self.assertFalse(getattr(DrawBotApp,operation)(app))
            self.assertTrue(images)
            for image in images:
                with self.assertRaises(ValueError):image.getpixel((0,0))
            self.assertEqual(app.original.getpixel((0,0)),(255,0,0,255))
            self.assertIsNone(app.background_removal_original)

    def test_save_failure_never_reports_success_or_replaces_destination(self):
        app=app_for_edit();work=[];app.begin_worker=lambda kind,task:work.append(task) or True
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'export.png';path.write_bytes(b'existing')
            with patch('DrawBot.filedialog.asksaveasfilename',return_value=str(path)):
                DrawBotApp.save_png_copy(app)
            def fail(image,stream,**kwargs):
                stream.write(b'half');raise OSError('encoder failed')
            with patch.object(Image.Image,'save',fail),self.assertRaisesRegex(OSError,'encoder failed'):work[0]()
            self.assertEqual(path.read_bytes(),b'existing')
            self.assertTrue(app.events.empty())


class BackgroundUiTests(unittest.TestCase):
    def test_failed_background_request_does_not_create_undo_state(self):
        app=app_for_edit();work=[];app.begin_worker=lambda kind,task:work.append(task) or True
        self.assertTrue(DrawBotApp.remove_image_background(app))
        self.assertIsNone(app.background_removal_original)
        with patch('BackgroundRemoval.remove_background',side_effect=ValueError('cannot segment')),self.assertRaises(ValueError):work[0]()
        self.assertIsNone(app.background_removal_original)

    def test_noop_background_result_keeps_existing_plan_and_undo(self):
        app=app_for_edit();old=app.original;plan=app.plan
        result=BackgroundRemovalResult(old.copy(),{'no_op_reason':'subject guard'})
        DrawBotApp._handle_event(app,'background_removed',result)
        self.assertIs(app.original,old);self.assertIs(app.plan,plan)
        self.assertIsNone(app.background_removal_original)
        app.show_previews.assert_not_called();app._mark_plan_stale.assert_not_called()
        with self.assertRaises(ValueError):result.image.getpixel((0,0))

    def test_successful_result_creates_undo_only_when_adopted(self):
        app=app_for_edit();old=app.original;result=BackgroundRemovalResult(Image.new('RGBA',(3,2)),{})
        with patch.object(DrawBotApp,'_clear_render_resume'):
            DrawBotApp._handle_event(app,'background_removed',result)
        self.assertEqual(app.background_removal_original.tobytes(),old.tobytes())
        self.assertIs(app.original,result.image)
        self.assertIsNot(app.background_removal_original,old)

    def test_closing_ui_does_not_open_export_dialog_or_start_an_edit(self):
        app=app_for_edit();app.closing=True;app.begin_worker=Mock()
        with patch('DrawBot.filedialog.asksaveasfilename') as dialog:
            for name in ('save_png_copy','export_preview','remove_image_background','undo_background_removal'):
                self.assertFalse(getattr(DrawBotApp,name)(app))
        app.begin_worker.assert_not_called();dialog.assert_not_called()


class HardwareWorkerTests(unittest.TestCase):
    def app(self):
        app=app_for_edit();app.hardware_benchmark_running=False
        app.auto_tune_summary=Mock();app.auto_tune_detail=Mock();app.apply_performance_tune=Mock()
        return app

    def test_tuner_uses_tracked_worker_and_forwards_stop_without_applying_late_result(self):
        app=self.app();tasks=[];app.begin_worker=lambda name,task:tasks.append((name,task)) or True
        self.assertTrue(DrawBotApp.run_performance_auto_tuner(app,apply=True))
        self.assertEqual(tasks[0][0],'performance-auto-tuner')
        with patch('DrawBot.run_auto_tune',return_value={'recommendation':{}}) as tune:
            tasks[0][1]()
        self.assertEqual(tune.call_args.kwargs['cancelled'],app.stop.is_set)
        app.stop.set();kind,payload=app.events.get_nowait()
        DrawBotApp._handle_event(app,kind,payload)
        app.apply_performance_tune.assert_not_called();self.assertFalse(app.hardware_benchmark_running)

    def test_tuner_startup_rejection_and_shutdown_never_leave_a_running_flag(self):
        for closing in (False,True):
            app=self.app();app.closing=closing;app.begin_worker=Mock(return_value=False)
            self.assertFalse(DrawBotApp.run_performance_auto_tuner(app))
            self.assertFalse(app.hardware_benchmark_running)
            if closing:app.begin_worker.assert_not_called()

    def test_delayed_automatic_tuner_does_not_clear_the_users_stop(self):
        app=self.app();app.stop.set();app.begin_worker=Mock()
        self.assertFalse(DrawBotApp.run_performance_auto_tuner(app,automatic=True))
        app.begin_worker.assert_not_called();self.assertTrue(app.stop.is_set())

    def test_tuner_interruption_is_a_cancel_result_instead_of_failure_or_success(self):
        app=self.app();tasks=[];app.begin_worker=lambda name,task:tasks.append(task) or True
        DrawBotApp.run_performance_auto_tuner(app)
        with patch('DrawBot.run_auto_tune',side_effect=InterruptedError()):tasks[0]()
        kind,payload=app.events.get_nowait();self.assertEqual(payload,{'cancelled':True})
        DrawBotApp._handle_event(app,kind,payload)
        app.apply_performance_tune.assert_not_called()
        self.assertIn('cancelled',app.auto_tune_summary.set.call_args.args[0])

    def test_compute_test_is_tracked_and_does_not_publish_after_stop(self):
        app=self.app();tasks=[];app.begin_worker=lambda name,task:tasks.append((name,task)) or True
        for name,value in (('gpu_mode','NVIDIA CUDA'),('gpu_vram','Auto'),('gpu_performance','Balanced')):
            setattr(app,name,Mock());getattr(app,name).get.return_value=value
        self.assertTrue(DrawBotApp.test_gpu_acceleration(app));self.assertEqual(tasks[0][0],'gpu-benchmark')
        def interrupted(*args,**kwargs):
            self.assertEqual(kwargs['cancelled'],app.stop.is_set);app.stop.set();return {'used_gpu':False}
        with patch('DrawBot.gpu_benchmark',side_effect=interrupted),self.assertRaises(InterruptedError):tasks[0][1]()
        self.assertTrue(app.events.empty())

    def test_resource_test_snapshots_ui_settings_before_starting_its_worker(self):
        app=self.app();tasks=[];app.begin_worker=lambda name,task:tasks.append((name,task)) or True
        values=('2','Threads','Auto','4096')
        for name,value in zip(('cpu_workers','cpu_engine','ram_budget','ram_custom_mb'),values):
            setattr(app,name,Mock());getattr(app,name).get.return_value=value
        allocation={'cpu_workers_resolved':2,'logical_cpus':8,'cpu_engine':'Threads','ram_budget_mb':4096}
        with patch('DrawBot.resolve_allocation',return_value=allocation):self.assertTrue(DrawBotApp.test_resource_allocation(app))
        self.assertEqual(tasks[0][0],'resource-benchmark')
        for name in ('cpu_workers','cpu_engine','ram_budget','ram_custom_mb'):
            getattr(app,name).get.side_effect=RuntimeError('Tk must not be read by this worker')
        result=dict(allocation,benchmark_tasks=2,benchmark_backend='Threads',benchmark_score=1,benchmark_elapsed_ms=1)
        with patch('DrawBot.benchmark_allocation',return_value=result) as benchmark,patch('DrawBot.benchmark_scheduler',return_value={'recommended_workers':2}) as scheduler:
            tasks[0][1]()
        benchmark.assert_called_once_with(*values,cancelled=app.stop.is_set)
        scheduler.assert_called_once_with(result,cancelled=app.stop.is_set)
        self.assertIn('complete',app.events.get_nowait()[1])


if __name__=='__main__':unittest.main()
