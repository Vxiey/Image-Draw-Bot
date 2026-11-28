"""Drive the Simple setup through real widgets, workers and event adoption."""
from contextlib import ExitStack
import gc
import os
from pathlib import Path
import sys
import threading
import time
import unittest
import weakref
from unittest.mock import patch


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'A graphical Tk display is required.')
class GuidedStudioTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        import DrawBot
        from UiCompatibility import scoped_window_class

        class NoInput:
            def add_hotkey(self, *args, **kwargs): return 1
            def remove_hotkey(self, *args): pass
            def get_position(self): return (0, 0)

        self.addCleanup(self.retire_native_fixture)
        self.stack = self.enterContext(ExitStack())
        for name in ('read_settings', 'refresh_runtime_safety_ui', 'refresh_auto_tuner_ui',
                     'maybe_auto_hardware_benchmark', 'offer_safe_session_recovery',
                     'show_welcome', '_schedule_recovery_checkpoint'):
            self.stack.enter_context(patch.object(DrawBot.DrawBotApp, name))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, 'save_settings', return_value=True))
        self.stack.enter_context(patch('DrawBot.previous_run_unclean', return_value=False))
        self.stack.enter_context(patch('ReleaseState.should_show_welcome', return_value=False))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.errors = self.stack.enter_context(patch.object(DrawBot.DrawBotApp, 'report_tk_callback_exception'))
        self.input = self.stack.enter_context(patch.object(DrawBot.DrawBotApp, 'start_full_drawing'))
        self.discovery = self.stack.enter_context(patch('GuidedCanvasDiscovery.discover_guided_canvas'))
        fixture = Path(__file__).parent / 'golden-regression/red-bananas-texture.png'
        self.stack.enter_context(patch('DrawBot.filedialog.askopenfilename', return_value=str(fixture)))
        self.root = scoped_window_class(ctk.CTk)()
        self.root_ref = weakref.ref(self.root)
        self.addCleanup(self.root.destroy)
        self.app = DrawBot.DrawBotApp(self.root, NoInput(), NoInput())
        self.guide = self.app._guided_setup_controller
        self.addCleanup(self.guide.cancel, refresh=False)
        self.root.minsize(500, 400)
        self.root.geometry('720x560')
        self.root.update()
        self.assertEqual(self.app.ui_mode.get(), 'Simple')

    def retire_native_fixture(self):
        # The test has finished using its CTk graph and callback histories.
        # Release them on the interpreter's owner thread before another worker.
        self.errors = self.input = self.discovery = None
        self.app = self.guide = self.root = None
        gc.collect()
        if hasattr(self, 'root_ref'):
            self.assertIsNone(self.root_ref(), 'The native guide test retained its Tcl interpreter')

    def wait(self, completed):
        deadline = time.monotonic() + 12
        while not completed():
            self.root.update()
            if time.monotonic() >= deadline:
                self.fail(f'Guide timed out: {self.app.guided_setup_state()}, activity={self.app.activity}, errors={self.errors.call_args_list!r}')
            time.sleep(.01)
        self.root.update()
        self.errors.assert_not_called()

    def choose_profile(self, name):
        selector = self.app.guided_profile_selector
        selector.set(name)
        selector.event_generate('<<ComboboxSelected>>')
        self.wait(lambda: self.app._active_profile_name == name and not self.app.profile_change_ticket)

    def open_image(self):
        self.assertEqual(self.app.guided_setup_state()['stage'], 'image')
        self.app.guided_action_button.invoke()
        self.wait(lambda: self.app.original is not None and self.app.activity is None)

    @staticmethod
    def candidate(*, handle=42):
        return {'profile_key': 'microsoft-paint', 'canvas_box': (-690, 110, -210, 510),
                'canvas_confidence': .95, 'target_meta': {'handle': handle, 'rect': (-800, 10, -100, 710),
                    'client_rect': (-795, 34, -105, 705), 'dpi': 144, 'target_pid': 18, 'target_thread': 7}}

    def test_manual_profile_primary_opens_image_then_region_picker(self):
        self.open_image()
        self.assertEqual(self.app.original.size, (360, 240))
        with patch('RegionPicker.select_region') as pick:
            self.app.guided_action_button.invoke()
        pick.assert_called_once()
        self.assertEqual(self.app.activity, 'capture')
        self.app.stop_button.invoke()
        self.assertTrue(self.app.stop.is_set())
        self.assertFalse(self.app.corners)
        self.discovery.assert_not_called()
        self.input.assert_not_called()

    def test_passive_paint_offer_requires_fresh_confirmation_of_same_window(self):
        self.choose_profile('Microsoft Paint')
        self.discovery.side_effect = [self.candidate(), self.candidate(handle=43), self.candidate(), self.candidate()]
        self.open_image()
        self.wait(lambda: self.app.guided_setup_state()['stage'] == 'confirm_canvas')
        self.assertEqual(self.app.corners, [])
        self.assertIsNone(self.app.target_window)
        self.app.guided_action_button.invoke()
        self.wait(lambda: self.guide.request is None)
        self.assertEqual(self.app.guided_setup_state()['stage'], 'canvas')
        self.assertEqual(self.app.corners, [])
        self.app.guided_action_button.invoke()
        self.wait(lambda: self.app.guided_setup_state()['stage'] == 'confirm_canvas')
        self.app.guided_action_button.invoke()
        self.wait(lambda: self.app.target_window is not None)
        self.assertEqual(self.app.corners, [(-690, 110), (-210, 510)])
        self.assertEqual(self.app.target_window[0], 42)
        self.assertEqual(self.app.target_dpi, 144)
        self.assertEqual([call.kwargs['previous'] is not None for call in self.discovery.call_args_list],
                         [False, True, False, True])
        self.input.assert_not_called()
        self.assertEqual(self.app.guided_setup_state()['stage'], 'ready')
        with patch('GuidedSetupController.messagebox.askyesno', side_effect=[False, True]) as consent:
            self.app.guided_action_button.invoke()
            self.input.assert_not_called()
            self.app.guided_action_button.invoke()
        self.assertEqual(consent.call_count, 2)
        self.assertEqual(consent.call_args.kwargs['default'], 'no')
        self.input.assert_called_once_with()

    def test_primary_action_and_stop_remain_reachable_in_small_scaled_windows(self):
        import customtkinter as ctk
        import tkinter as tk

        self.addCleanup(ctk.set_widget_scaling, 1.0)
        for scale in (1.0, 1.25, 1.5, 2.0):
            with self.subTest(scale=scale):
                ctk.set_widget_scaling(scale)
                window_scale = self.root._get_window_scaling()
                size = (round(650 * window_scale), round(500 * window_scale))

                def can_resize():
                    low = tk.Wm.wm_minsize(self.root)
                    high = tk.Wm.wm_maxsize(self.root)
                    return all(a <= value <= b for a, value, b in zip(low, size, high))

                self.wait(can_resize)
                self.root.geometry('650x500')
                self.wait(lambda: (self.root.winfo_width(), self.root.winfo_height()) == size
                          and self.app.workspace_layout.job is None and self.app.draw_action_bar.job is None)
                for widget in (self.app.guided_action_button, self.app.stop_button):
                    self.assertTrue(widget.winfo_ismapped())
                    x = widget.winfo_rootx() + widget.winfo_width() // 2
                    for fraction in (.2, .5, .8):
                        y = widget.winfo_rooty() + int(widget.winfo_height() * fraction)
                        hit = self.root.winfo_containing(x, y)
                        while hit is not None and hit is not widget:
                            hit = hit.master
                        self.assertIs(hit, widget, f'{widget.cget("text")} occluded at {(x, y)}')

    def test_replacing_image_discards_pending_offer_and_shows_missing_target(self):
        self.choose_profile('Microsoft Paint')
        running = threading.Event()
        release = threading.Event()
        def discovery(*args, **kwargs):
            if running.is_set():
                raise ValueError('No matching drawing window is open.')
            running.set()
            if not release.wait(8):
                raise TimeoutError('test worker was never released')
            return self.candidate()
        self.discovery.side_effect = discovery
        self.addCleanup(release.set)
        self.open_image()
        self.wait(running.is_set)
        first = self.app.original
        replacement = Path(__file__).parent / 'assets/paint-tools-reference.png'
        self.app.load_source(str(replacement), replacement.name)
        self.wait(lambda: self.app.original is not first and self.app.activity is None)
        release.set()
        self.wait(lambda: self.guide.request is None and bool(self.guide.note))
        self.assertEqual(self.app.original.size, (76, 76))
        self.assertIn('No matching', self.app.guided_setup_state()['detail'])
        self.assertIsNone(self.app.target_window)
        self.assertFalse(self.app.corners)
        self.input.assert_not_called()

    def test_stop_and_profile_switch_ignore_late_discovery_even_after_no_target(self):
        self.choose_profile('Microsoft Paint')
        running = threading.Event()
        release = threading.Event()
        def slow_search(*args, **kwargs):
            running.set()
            if not release.wait(8):
                raise TimeoutError('test worker was never released')
            return self.candidate()
        self.discovery.side_effect = ValueError('Several candidate windows. Select the area manually.')
        self.open_image()
        self.wait(lambda: self.guide.request is None and bool(self.guide.note))
        state = self.app.guided_setup_state()
        self.assertEqual(state['stage'], 'canvas')
        self.assertTrue(state['manual_canvas_enabled'])
        self.assertIn('Several', state['detail'])
        self.discovery.side_effect = slow_search
        self.addCleanup(release.set)
        self.app.guided_action_button.invoke()
        self.wait(running.is_set)
        self.app.stop_button.invoke()
        self.choose_profile('Other drawing app')
        release.set()
        self.wait(lambda: self.guide.worker is None)
        self.assertIsNone(self.app.target_window)
        self.assertFalse(self.app.corners)
        self.assertEqual(self.app.guided_setup_state()['action_label'], 'Select area manually')
        self.input.assert_not_called()


if __name__ == '__main__':
    unittest.main()
