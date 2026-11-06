"""Failure-injection and visible-behavior regressions for the UI review."""
from contextlib import ExitStack
import io
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from DrawBot import DrawBotApp
from ScreenRecording import save_gif_atomic
from AppToolCalibration import AppToolCalibrationApp
from CalibrationAnchors import make_anchor
import PreviewLayers
import RegionPicker
import SubjectSelector


class ClipboardRuntimeTests(unittest.TestCase):
    def test_text_and_spinbox_paste_stays_native_even_with_a_tcl_widget_path(self):
        for kind in (tk.Text, tk.Spinbox, ttk.Spinbox, tk.Entry, ttk.Combobox):
            widget = object.__new__(kind)
            for target in (widget, '.editor'):
                with self.subTest(kind=kind, target=type(target)):
                    app = SimpleNamespace(paste_image=Mock(), root=Mock())
                    app.root.nametowidget.return_value = widget
                    self.assertIsNone(DrawBotApp.paste_shortcut(app, SimpleNamespace(widget=target)))
                    app.paste_image.assert_not_called()

    def test_clipboard_is_not_read_during_close_or_pending_clear(self):
        for closing, pending in ((True, None), (False, object())):
            app = SimpleNamespace(activity=None, closing=closing, pending_clear_drawing=pending)
            with patch('PIL.ImageGrab.grabclipboard', side_effect=AssertionError('No clipboard access')):
                DrawBotApp.paste_image(app)

    def test_malformed_url_is_reported_without_starting_a_worker(self):
        for source in ('https://[invalid', 'https:///missing-host', 'https://example.com:99999/a.png'):
            app = SimpleNamespace(url=Mock(), status=Mock(), load_source=Mock())
            app.url.get.return_value = source
            DrawBotApp.fetch_url(app)
            app.load_source.assert_not_called()
            app.status.set.assert_called_once()

    def test_uppercase_url_from_clipboard_is_imported(self):
        app = SimpleNamespace(activity=None, closing=False, root=Mock(), url=Mock(), fetch_url=Mock())
        app.root.clipboard_get.return_value = 'HTTPS://example.com/image.png'
        with patch('PIL.ImageGrab.grabclipboard', return_value=None):
            DrawBotApp.paste_image(app)
        app.url.set.assert_called_once_with('HTTPS://example.com/image.png')
        app.fetch_url.assert_called_once()

    def test_pasted_exif_orientation_is_applied_once(self):
        source = Image.new('RGB', (3, 2), 'red'); source.getexif()[274] = 6
        app = SimpleNamespace(activity=None, closing=False, file_label=Mock(), status=Mock(),
                              _mark_plan_stale=Mock(), show_previews=Mock(),
                              _schedule_recovery_checkpoint=Mock(), _maybe_auto_preview=Mock())
        with patch('PIL.ImageGrab.grabclipboard', return_value=source), \
             patch.object(DrawBotApp, '_clear_render_resume'), patch.object(DrawBotApp, '_queue_drop_in_start'):
            DrawBotApp.paste_image(app)
        self.assertEqual(app.original.size, (2, 3))
        self.assertNotIn(274, app.original.getexif())
        self.assertEqual(source.size, (3, 2))


class WorkerRuntimeTests(unittest.TestCase):
    def app(self):
        app = SimpleNamespace(activity=None, closing=False, root=Mock(), stop=threading.Event(), events=queue.Queue())
        app.set_busy = lambda activity: setattr(app, 'activity', activity)
        return app

    def test_all_startup_failures_restore_idle_and_the_screen_window(self):
        for stage in ('hide', 'busy', 'constructor', 'start'):
            with self.subTest(stage=stage), ExitStack() as stack:
                app = self.app(); window = SimpleNamespace(hide=Mock(), restore=Mock())
                original = RuntimeError(f'{stage} failed')
                stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow', return_value=window))
                thread = stack.enter_context(patch('DrawBot.threading.Thread'))
                if stage == 'hide': window.hide.side_effect = original
                elif stage == 'busy':
                    def busy(activity):
                        app.activity = activity
                        if activity: raise original
                    app.set_busy = busy
                elif stage == 'constructor': thread.side_effect = original
                else: thread.return_value.start.side_effect = original
                with self.assertRaises(RuntimeError) as caught:
                    DrawBotApp.begin_worker(app, 'record', Mock())
                self.assertIs(caught.exception, original)
                self.assertIsNone(app.activity)
                self.assertIsNone(app.worker)
                self.assertTrue(app.stop.is_set())
                window.restore.assert_called_once()

    def test_cleanup_failure_does_not_hide_the_original_startup_error(self):
        app = self.app(); app.set_busy = Mock(side_effect=ValueError('busy failure'))
        with patch('ScreenTaskWindow.ScreenTaskWindow') as window:
            window.return_value.restore.side_effect = OSError('restore failure')
            with self.assertRaisesRegex(ValueError, 'busy failure'):
                DrawBotApp.begin_worker(app, 'preview', Mock())
        self.assertIsNone(app.activity)

    def test_cancellation_before_non_screen_task_start_skips_the_task(self):
        app = self.app(); task = Mock()
        def make_thread(*, target, **kwargs):
            def start():
                app.stop.set(); target()
            return SimpleNamespace(start=start)
        with patch('DrawBot.threading.Thread', side_effect=make_thread):
            self.assertTrue(DrawBotApp.begin_worker(app, 'preview', task))
        task.assert_not_called()
        self.assertEqual(list(app.events.queue)[-1], ('done', 'preview'))

    def test_event_drain_yields_with_backlog_and_preserves_fifo_order(self):
        now = [0.0]; handled = []
        app = self.app(); app.drop_action_pending = None; app.needs_plan = False
        def handle(kind, value):
            handled.append((kind, value)); now[0] += .01
        app._handle_event = handle
        for number in range(20): app.events.put(('status', number))
        with patch('DrawBot.time.monotonic', side_effect=lambda: now[0]), \
             patch.object(DrawBotApp, '_schedule_poll') as reschedule:
            DrawBotApp.poll(app)
        self.assertEqual(handled, [('status', 0), ('status', 1)])
        self.assertEqual(list(app.events.queue), [('status', n) for n in range(2, 20)])
        reschedule.assert_called_once_with(app)


class PreviewRuntimeTests(unittest.TestCase):
    def test_missing_mobile_url_never_creates_an_unowned_tk_variable(self):
        app = SimpleNamespace(status=Mock(), root=Mock())
        with patch('DrawBot.tk.StringVar', side_effect=AssertionError('No Tk allocation')):
            DrawBotApp._copy_mobile_preview_url(app)
        app.status.set.assert_called_once_with('Start Mobile Preview first.')
        app.root.clipboard_clear.assert_not_called()

    def test_destroyed_canvas_during_error_fallback_is_contained(self):
        canvas = Mock(); canvas.winfo_exists.return_value = True; canvas.winfo_ismapped.return_value = True
        canvas.winfo_width.side_effect = (ValueError('invalid size'), tk.TclError('destroyed'))
        app = SimpleNamespace(closing=False, original=None, plan=None, photos=[], original_canvas=canvas,
                              result_canvas=Mock(winfo_exists=Mock(return_value=False)))
        DrawBotApp.show_previews(app)
        self.assertFalse(app.preview_rendering)

    def layer(self, **overrides):
        kwargs = dict(source=Image.new('RGBA', (30, 20), (30, 60, 90, 120)), size=(30, 20),
                      groups=[[(0, 0, 10, 10)]], palette_rgb=[(255, 0, 0)],
                      point=lambda x, y: (x, y), brush=1, options={})
        kwargs.update(overrides)
        return PreviewLayers.build_auxiliary_previews(**kwargs)

    def test_large_safety_path_is_cancelled_inside_the_path(self):
        path = [(i % 30, i % 20) for i in range(10000)]
        calls = [0]
        def cancelled():
            calls[0] += 1
            return calls[0] == 3
        with patch.object(PreviewLayers.ImageDraw, 'Draw') as draw:
            with self.assertRaises(InterruptedError):
                self.layer(options={'_preview_safety_groups': [[path]]}, cancelled=cancelled)
        self.assertLess(draw.return_value.line.call_count, 300)

    def test_cancelled_preview_does_not_allocate_images(self):
        with patch.object(PreviewLayers.Image, 'new', side_effect=AssertionError('No allocation')):
            with self.assertRaises(InterruptedError):
                PreviewLayers.build_auxiliary_previews(None, (30, 20), [], [], None, 1, {}, lambda: True)

    def test_same_size_source_is_not_resized_twice_and_layers_do_not_alias(self):
        with patch.object(Image.Image, 'resize', side_effect=AssertionError('No resize at equal size')):
            result = self.layer()
        self.assertEqual(result['color'].getpixel((0, 0)), (149, 163, 177))
        result['fill'].putpixel((0, 0), (1, 2, 3))
        self.assertEqual(result['color'].getpixel((0, 0)), (149, 163, 177))

    def test_bad_fill_box_does_not_discard_valid_preview_layers(self):
        result = self.layer(options={'fill_regions': [{'bbox': (0, 0, float('inf'), 10)},
                                                     {'bbox': (2, 2, 10, 10), 'color_index': 0}]})
        self.assertEqual(set(result), {'stroke', 'fill', 'color'})
        self.assertNotEqual(result['fill'].getpixel((5, 5)), result['color'].getpixel((5, 5)))

    def test_sampled_coordinates_preserve_exact_integer_pixel_boundaries(self):
        result = self.layer(source=Image.new('RGB',(70,70),'white'),size=(70,70),
                            palette_rgb=[(255,0,0)], options={
                                '_preview_safety_groups': [[[(90,90),(90,95)]]],
                                'preview_safety_meta': {'canvas_guard': {'area': (0,0,100,100)}}})
        self.assertEqual(result['stroke'].getpixel((63,63)), (255,49,49))
        self.assertEqual(result['stroke'].getpixel((62,63)), (15,20,29))


class RecordingRuntimeTests(unittest.TestCase):
    def test_recording_uses_unique_staging_and_preserves_unrelated_tmp_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'recording.gif'; unrelated = Path(str(path) + '.tmp')
            unrelated.write_text('existing user file')
            with Image.new('P', (3, 3), 2) as frame:
                save_gif_atomic(path, [frame], [250])
            with Image.open(path) as result: self.assertEqual(result.format, 'GIF')
            self.assertEqual(unrelated.read_text(), 'existing user file')
            self.assertEqual(set(Path(folder).iterdir()), {path, unrelated})

    def test_failed_encode_or_flush_preserves_the_previous_recording(self):
        for operation in ('encode', 'flush'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'recording.gif'; path.write_bytes(b'previous')
                with Image.new('P', (3, 3), 2) as frame:
                    target = 'PIL.Image.Image.save' if operation == 'encode' else 'ScreenRecording.os.fsync'
                    with patch(target, side_effect=OSError('disk full')):
                        with self.assertRaisesRegex(OSError, 'disk full'):
                            save_gif_atomic(path, [frame], [250])
                self.assertEqual(path.read_bytes(), b'previous')
                self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_partial_capture_failure_closes_all_owned_frames(self):
        raw = Image.new('RGB', (5, 5), 'red'); quantized = raw.quantize()
        worker = []
        app = SimpleNamespace(corners=[(0, 0), (10, 10)], area=lambda: (0, 0, 10, 10),
                              stop=Mock(), events=queue.Queue(), begin_worker=lambda activity, work: worker.append(work))
        app.stop.wait.return_value = False; app.stop.is_set.return_value = False
        with patch('DrawBot.filedialog.asksaveasfilename', return_value='unused.gif'):
            DrawBotApp.record_screen(app)
        with patch('DrawBot.grab_area', side_effect=(raw, OSError('capture failed'))), \
             patch.object(raw, 'quantize', return_value=quantized):
            with self.assertRaisesRegex(OSError, 'capture failed'): worker[0]()
        for frame in (raw, quantized):
            with self.assertRaises(ValueError): frame.getpixel((0, 0))


class CalibrationAndModalTests(unittest.TestCase):
    def test_failed_recapture_does_not_commit_an_incompatible_window_identity(self):
        app = SimpleNamespace(mouse=Mock(), anchor=make_anchor((0, 0, 100, 100)), anchor_handle=None,
                              positions={}, status=Mock(), refresh=Mock())
        app.mouse.get_position.return_value = (10, 10)
        invalid = {'handle': 10, 'client_rect': (0, 0, 200, 100)}
        valid = {'handle': 20, 'client_rect': (5, 5, 105, 105)}
        with patch('TargetCapture.capture_target_metadata_isolated', side_effect=(invalid, valid)):
            AppToolCalibrationApp._capture_now(app, 'Brush')
            self.assertIsNone(app.anchor_handle)
            self.assertFalse(app.positions)
            AppToolCalibrationApp._capture_now(app, 'Brush')
        self.assertEqual(app.anchor_handle, 20)
        self.assertEqual(app.positions['Brush'], (5, 5))

    def test_region_capture_start_failure_restores_an_iconic_owner(self):
        owner = Mock(); owner.master = None; owner.state.return_value = 'iconic'
        owner.after.side_effect = tk.TclError('closing')
        RegionPicker.select_region(owner, Mock(), Mock())
        owner.iconify.assert_called_once()

    def test_region_capture_releases_desktop_buffers_on_selection_and_cancel(self):
        import ctypes
        for choose in (False, True):
            with self.subTest(choose=choose):
                jobs=[]; bindings={}; delivered=[]
                owner=Mock(); owner.master=None; owner.state.return_value='normal'
                owner.after.side_effect=lambda delay, callback: jobs.append(callback) or 'job'
                api=Mock()
                api.GetSystemMetrics.side_effect=lambda index: {76:0,77:0,78:40,79:30}[index]
                api.GetAncestor.return_value=123; api.SetWindowPos.return_value=True
                top=Mock()
                class Overlay:
                    def __new__(cls,*args,**kwargs): return top
                captured=Image.new('RGB',(40,30),'red'); original_convert=captured.convert; copies=[]
                def convert(*args,**kwargs):
                    result=original_convert(*args,**kwargs);copies.append(result);return result
                with patch('WindowsSystem.load_system_library',return_value=api), \
                     patch('RegionPicker.ImageGrab.grab',return_value=captured), \
                     patch.object(captured,'convert',side_effect=convert), \
                     patch('RegionPicker.tk.Toplevel',Overlay), patch('RegionPicker.tk.Canvas') as canvas, \
                     patch('RegionPicker.ImageTk.PhotoImage'):
                    top.bind.side_effect=lambda event,callback:bindings.__setitem__(event,callback)
                    canvas.return_value.bind.side_effect=lambda event,callback:bindings.__setitem__(event,callback)
                    RegionPicker.select_region(owner,lambda box,crop:delivered.append((box,crop)),Mock())
                    jobs.pop(0)()
                    if choose:
                        bindings['<ButtonPress-1>'](SimpleNamespace(x=2,y=3))
                        bindings['<ButtonRelease-1>'](SimpleNamespace(x=20,y=23))
                        jobs.pop(0)()
                        self.assertEqual(delivered[0][0],(2,3,20,23))
                        self.assertEqual(delivered[0][1].getpixel((0,0)),(255,0,0))
                        delivered[0][1].close()
                    else:
                        bindings['<Escape>']()
                for image in [captured]+copies:
                    with self.assertRaises(ValueError): image.getpixel((0,0))

    def test_subject_selector_handles_compact_desktop_and_closes_before_callback(self):
        parent = Mock(); parent.winfo_screenwidth.return_value = 80; parent.winfo_screenheight.return_value = 120
        with patch('customtkinter.CTkToplevel') as top, patch('customtkinter.CTkLabel'), \
             patch('customtkinter.CTkButton'), patch('tkinter.Canvas') as canvas, patch('PIL.ImageTk.PhotoImage'):
            SubjectSelector.select_subject(parent, Image.new('RGB', (10, 10)), Mock())
            self.assertEqual(canvas.call_args.kwargs['width'], 1)
            self.assertEqual(canvas.call_args.kwargs['height'], 1)
        parent.winfo_screenwidth.return_value = 1200; parent.winfo_screenheight.return_value = 800
        bindings = {}; commands = []
        def callback(_region):
            top.return_value.destroy.assert_called_once()
            raise ValueError('callback failure')
        with patch('customtkinter.CTkToplevel') as top, patch('customtkinter.CTkLabel'), \
             patch('customtkinter.CTkButton') as button, patch('tkinter.Canvas') as canvas, patch('PIL.ImageTk.PhotoImage'):
            canvas.return_value.bind.side_effect = lambda event, action: bindings.__setitem__(event, action)
            button.side_effect = lambda *args, **kwargs: commands.append(kwargs['command']) or Mock()
            SubjectSelector.select_subject(parent, Image.new('RGB', (10, 10)), callback)
            bindings['<Button-1>'](SimpleNamespace(x=1, y=1))
            bindings['<B1-Motion>'](SimpleNamespace(x=8, y=8))
            with self.assertRaisesRegex(ValueError, 'callback failure'): commands[0]()


if __name__ == '__main__': unittest.main()
