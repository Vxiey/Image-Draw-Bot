"""Real Studio layout and profile continuity, isolated from input and user data.

Each native case runs in a fresh process before importing the application, so
module-level data paths and Tcl owners cannot leak into another test. The UI,
settings, profile callbacks and layout are production code; no images are made.
The parent owns temporary data until the child exits, including the crash-log
descriptor deliberately retained by faulthandler for the process lifetime.
"""
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch


class NoInput:
    def __init__(self):
        self.attempts = []

    def add_hotkey(self, *args, **kwargs):
        return len(args)

    def remove_hotkey(self, *args):
        pass

    def get_position(self):
        return (0, 0)

    def disarm_input(self):
        pass

    def release(self):
        pass

    def move(self, *args, **kwargs):
        self.attempts.append((args, kwargs))
        raise AssertionError('Workspace inspection attempted external input.')

    press = click = move


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native Tk display required')
class NativeStudioWorkspaceTests(unittest.TestCase):
    def isolated(self):
        name = f'{Path(__file__).stem}.{type(self).__name__}.{self._testMethodName}'
        if os.environ.get('IDB_UI_WORKSPACE_CASE') == name:
            return False
        # DrawBot installs a process-lifetime faulthandler stream. Windows must
        # release that child-owned descriptor before this directory is removed.
        with tempfile.TemporaryDirectory(prefix='idb-workspace-') as temporary:
            data = Path(temporary).resolve()
            result = subprocess.run(
                [sys.executable, '-X', 'faulthandler', '-m', 'unittest', '-v', name],
                cwd=Path(__file__).resolve().parent,
                env=dict(os.environ, IDB_UI_WORKSPACE_CASE=name, IDB_UI_WORKSPACE_DATA_DIR=str(data)),
                text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=45,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            for diagnostic in ('invalid command name', 'Tcl_AsyncDelete', 'Exception ignored in'):
                self.assertNotIn(diagnostic, output)
            self.assertTrue((data / 'logs' / 'ImageDrawBot-crash.log').is_file(),
                            'The real child crash-log lifetime must be covered by cleanup.')
        self.assertFalse(data.exists(), 'The parent must remove all child-owned runtime files.')
        return True

    def wait(self, root, predicate, description):
        deadline = time.monotonic() + 5
        while True:
            root.update()
            if predicate():
                root.update_idletasks()
                return
            if time.monotonic() >= deadline:
                self.fail(description + '; actual root geometry: ' + root.geometry())
            time.sleep(.01)

    @contextmanager
    def workspace(self):
        with ExitStack() as stack:
            data = Path(os.environ['IDB_UI_WORKSPACE_DATA_DIR'])
            self.assertTrue(data.is_absolute() and data.is_dir(), 'Parent-owned app data is required.')
            import RuntimePaths
            stack.enter_context(patch.object(RuntimePaths, 'data_dir', lambda: data))
            # All application modules must first load after the data boundary.
            import customtkinter as ctk
            import DrawBot
            errors = []
            for method in ('maybe_auto_hardware_benchmark', 'show_welcome', 'offer_safe_session_recovery'):
                stack.enter_context(patch.object(DrawBot.DrawBotApp, method, lambda *_a, **_k: None))
            original_handler = DrawBot.DrawBotApp.report_tk_callback_exception

            def report(app, *error):
                errors.append(''.join(traceback.format_exception(*error)))
                original_handler(app, *error)

            stack.enter_context(patch.object(DrawBot.DrawBotApp, 'report_tk_callback_exception', report))
            ctk.set_widget_scaling(1)
            root = DrawBot.create_root()
            root.tk.createcommand('bgerror', lambda message: errors.append(str(message)))
            backend = NoInput()
            app = None
            try:
                app = DrawBot.DrawBotApp(root, backend, backend)
                root.minsize(500, 400)
                self.resize(root, app, 1)
                self.select_profile(root, app, 'Microsoft Paint')
                for group in app._compact_ui_layout.groups:
                    group.set_open(True)
                root.update()
                self.assertEqual(DrawBot.DATA_DIR, data)
                yield root, app, backend, data
            finally:
                if app is not None:
                    app.close()
                root.destroy()
            self.assertEqual(errors, [])
            self.assertEqual(backend.attempts, [])

    def resize(self, root, app, scale):
        import customtkinter as ctk
        import tkinter as tk
        ctk.set_widget_scaling(scale)
        expected = tuple(round(value * root._get_window_scaling()) for value in (1280, 900))

        def limits_allow():
            low, high = tk.Wm.wm_minsize(root), tk.Wm.wm_maxsize(root)
            return all(lower <= value <= upper for lower, value, upper in zip(low, expected, high))

        self.wait(root, limits_allow, 'CTk scaling did not restore native size limits')
        root.geometry('1280x900+20+20')
        self.wait(root, lambda: (root.winfo_width(), root.winfo_height()) == expected and all(
            bar.job is None for bar in (app.workspace_layout, app.draw_action_bar, app.help_action_bar)),
            'Workspace geometry did not settle')

    def select_profile(self, root, app, name):
        app.game.set(name)
        app.change_profile()
        self.wait(root, lambda: app._active_profile_name == name and app.profile_change_after is None
                  and not app.profile_change_in_progress, 'Profile change did not finish')
        app.workspace_layout.select('Setup')
        root.update()

    def test_guided_style_background_and_undo_use_the_current_image(self):
        if self.isolated():
            return
        from tkinter import ttk
        from BackgroundRemoval import MODES, STRENGTHS, remove_background
        from DrawingStyleProfiles import DRAWING_STYLES
        from UiKeyboardNavigation import KeyboardButton
        with self.workspace() as (root, app, _backend, _data):
            def open_adjustment(button):
                button.invoke()
                self.wait(root, lambda: root.grab_current() is not None, 'Adjustment dialog did not take focus')
                dialog = root.grab_current()
                self.assertEqual(dialog.title(), 'Adjust background removal')
                selectors = [item for item in descendants(dialog) if isinstance(item, ttk.Combobox)]
                self.assertEqual([tuple(item['values']) for item in selectors], [MODES, STRENGTHS])
                actions = {item.cget('text'): item for item in descendants(dialog) if isinstance(item, KeyboardButton)}
                return selectors, actions

            self.select_profile(root, app, 'Other drawing app')
            self.assertTrue(app.guided_action_button.winfo_ismapped())
            self.assertFalse(app.start.winfo_ismapped())
            self.assertIn(app.start, app.draw_action_bar.overflow)
            self.assertFalse(app.guided_style_selector.winfo_ismapped())

            path = Path(__file__).parent / 'golden-regression' / 'red-bananas-texture.png'
            self.assertTrue(app.load_source(str(path), path.name))
            self.wait(root, lambda: not app.activity and app.guided_style_selector.winfo_ismapped(),
                      'Image editing controls did not become visible')
            source = app.original.tobytes()
            self.assertEqual(tuple(app.guided_style_selector['values']), tuple(DRAWING_STYLES))
            self.assertTrue(app.guided_remove_background_button.winfo_ismapped())
            self.assertTrue(app.guided_adjust_background_button.winfo_ismapped())
            self.assertEqual(app.guided_undo_background_button.cget('state'), 'disabled')
            app._request_stop()
            selectors, actions = open_adjustment(app.guided_adjust_background_button)
            self.assertEqual([field.get() for field in selectors], ['Auto', 'Balanced'])
            self.assertIn('Apply', actions)
            actions['Cancel'].invoke()
            self.assertTrue(app.stop.is_set())
            _selectors, actions = open_adjustment(app.guided_adjust_background_button)
            clear = app.stop.clear
            def stop_during_apply():
                app._request_stop()
                clear()
            with patch.object(app.stop, 'clear', side_effect=stop_during_apply):
                actions['Apply'].invoke()
            self.assertTrue(app.stop.is_set())
            self.assertIsNone(app.worker)
            self.assertIsNone(app.background_removal_original)
            self.assertEqual(app.original.tobytes(), source)

            generation = app.preview_generation
            app.guided_style_selector.set('Pixel Art')
            app.guided_style_selector.event_generate('<<ComboboxSelected>>')
            root.update()
            self.assertEqual(app.drawing_style.get(), 'Pixel Art')
            self.assertGreater(app.preview_generation, generation)
            self.assertIsNone(app.activity)

            app.guided_remove_background_button.invoke()
            self.wait(root, lambda: not app.activity and app.guided_undo_background_button.cget('state') == 'normal',
                      'Background removal did not offer Undo for the edited source')
            first = app.original
            saved = app.background_removal_original
            self.assertNotEqual(first.tobytes(), source)
            app._request_stop()
            selectors, actions = open_adjustment(app.guided_adjust_background_button)
            selectors[0].set('Light background')
            selectors[1].set('Conservative')
            actions['Replace cutout'].invoke()
            self.wait(root, lambda: app.original is not first and not app.activity, 'Did not replace the cutout')
            expected = remove_background(saved, mode='Light background', strength='Conservative')
            with expected.image:
                self.assertEqual(app.original.tobytes(), expected.image.tobytes())
                self.assertNotEqual(first.tobytes(), expected.image.tobytes())
            self.assertIs(app.background_removal_original, saved)

            app.ui_mode.set('Advanced')
            app.workspace_layout.select('Setup')
            root.update()
            advanced = next(widget for widget in descendants(root)
                            if isinstance(widget, KeyboardButton) and widget.cget('text') == 'Adjust…'
                            and widget.winfo_ismapped())
            selectors, actions = open_adjustment(advanced)
            self.assertEqual([field.get() for field in selectors], ['Light background', 'Conservative'])
            self.assertIn('Replace cutout', actions)
            actions['Cancel'].invoke()
            app.ui_mode.set('Simple')
            root.update()
            app.guided_undo_background_button.invoke()
            self.wait(root, lambda: app.guided_undo_background_button.cget('state') == 'disabled',
                      'Undo did not reset after restoring the source')
            self.assertEqual(app.original.tobytes(), source)
            self.assertEqual(app.drawing_style.get(), 'Pixel Art')

    def test_setting_labels_selectors_and_disclosures_fit_the_real_scaled_workspace(self):
        if self.isolated():
            return
        import customtkinter as ctk
        from tkinter import font as tkfont
        with self.workspace() as (root, app, _backend, _data):
            import StudioUI
            with self.subTest(behavior='opaque root uses the Studio background'):
                self.assertEqual(root.cget('fg_color'), StudioUI.BG)
            app.ui_mode.set('Advanced')
            preset = next(widget for widget in descendants(root)
                          if isinstance(widget, ctk.CTkOptionMenu)
                          and getattr(widget, '_variable', None) is app.render_preset)
            preset.set('Masterpiece')
            row = preset._setting_row
            labels = [widget for widget in descendants(row) if isinstance(widget, ctk.CTkLabel)]
            self.assertGreaterEqual(len(labels), 2)
            hint = max(labels, key=lambda widget: len(widget.cget('text')))
            for scale in (1, 1.25, 1.5, 1.75, 2):
                with self.subTest(scale=scale):
                    self.resize(root, app, scale)
                    app.workspace_layout.select('Setup')
                    root.update()
                    self.assertTrue(preset.winfo_ismapped())
                    self.assertGreaterEqual(preset.winfo_rooty(),
                        max(label.winfo_rooty() + label.winfo_height() for label in labels))
                    self.assertLessEqual(abs(preset.winfo_rootx() - row.winfo_rootx()), 1)
                    self.assertLessEqual(abs(preset.winfo_width() - row.winfo_width()), 1)
                    native = preset._text_label
                    self.assertEqual(native.cget('text'), 'Masterpiece')
                    measured = tkfont.Font(root=root, font=native.cget('font')).measure('Masterpiece')
                    self.assertGreaterEqual(native.winfo_width(), measured)
                    self.assertLessEqual(abs(hint.winfo_width() - row.winfo_width()), 1)
                    for label in (hint, *(group.caption for group in app._compact_ui_layout.groups)):
                        if label.winfo_ismapped():
                            physical_wrap = int(label._label.cget('wraplength'))
                            self.assertGreater(physical_wrap, 0)
                            self.assertLessEqual(physical_wrap, label.winfo_width() + 1,
                                                 f'Help text wraps beyond its actual label: {label.cget("text")}')

    def test_mode_and_profile_round_trip_preserves_widgets_variables_and_scopes(self):
        if self.isolated():
            return
        import customtkinter as ctk
        import tkinter as tk
        with self.workspace() as (root, app, backend, data):
            variables = {name: value for name, value in vars(app).items() if isinstance(value, tk.Variable)}
            controls = tuple(widget for widget, _scope, _options in app._scoped_profile_controls)
            quality = next(widget for widget in descendants(root)
                           if isinstance(widget, ctk.CTkButton) and '🎨  Quality' in widget.cget('text'))
            developer = next(widget for widget in descendants(root)
                             if isinstance(widget, ctk.CTkButton) and 'Developer tools' in widget.cget('text'))
            for mode in ('Simple', 'Advanced', 'Developer', 'Simple'):
                with self.subTest(mode=mode):
                    app.ui_mode.set(mode)
                    root.update()
                    self.assertEqual(bool(quality.winfo_ismapped()), mode != 'Simple')
                    self.assertEqual(bool(developer.winfo_ismapped()), mode == 'Developer')
                    self.assertTrue(all(getattr(app, name) is value for name, value in variables.items()))
                    self.assertEqual(tuple(widget for widget, _scope, _options in app._scoped_profile_controls), controls)
            app.ui_mode.set('Developer')
            app.brush_px.set('7')
            for name, mode, brush in (('Gartic Phone', 'Advanced', '4'), ('Skribbl.io', 'Simple', '2')):
                self.select_profile(root, app, name)
                self.assertEqual(app.ui_mode.get(), 'Simple')
                self.assertFalse(app.paint_tool_menu.winfo_ismapped())
                self.assertFalse(app.gartic_opacity_row.winfo_ismapped())
                self.assertTrue(app.guided_profile_selector.winfo_ismapped())
                app.ui_mode.set(mode)
                app.brush_px.set(brush)
            for name, mode, brush in (('Microsoft Paint', 'Developer', '7'), ('Gartic Phone', 'Advanced', '4')):
                with self.subTest(restored_profile=name):
                    self.select_profile(root, app, name)
                    self.assertEqual(app.ui_mode.get(), mode)
                    self.assertEqual(app.brush_px.get(), brush)
                    self.assertEqual(bool(app.paint_tool_menu.winfo_ismapped()), name == 'Microsoft Paint')
                    self.assertEqual(bool(app.gartic_opacity_row.winfo_ismapped()), name == 'Gartic Phone')
                    self.assertTrue(all(getattr(app, key) is value for key, value in variables.items()))
                    self.assertEqual(tuple(widget for widget, _scope, _options in app._scoped_profile_controls), controls)
                    self.assertEqual(app.preview_mode.get(), 'Manual')
                    self.assertIsNone(app.activity)
                    self.assertIsNone(app.worker)
                    self.assertEqual(app.full_draw_armed_until, 0)
            saved = json.loads((data / 'settings-microsoft-paint.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['brush_px'], '7')
            self.assertEqual(saved['profile_extras']['ui_mode'], 'Developer')
            self.assertEqual(backend.attempts, [])

    def test_real_error_actions_keep_their_requested_width_inside_the_readiness_panel(self):
        if self.isolated():
            return
        import customtkinter as ctk
        with self.workspace() as (root, app, _backend, _data):
            rows = []
            for widget in descendants(root):
                if isinstance(widget, ctk.CTkButton) and 'Diagnostics' in widget.cget('text'):
                    siblings = [item for item in widget.master.winfo_children() if isinstance(item, ctk.CTkButton)]
                    if any('Logs' in item.cget('text') for item in siblings) and any('Help' in item.cget('text') for item in siblings):
                        rows.append((widget.master, siblings))
            self.assertEqual(len(rows), 1)
            row, actions = rows[0]
            app.status.set('Error: Unable to load image')
            for scale in (1, 2):
                with self.subTest(scale=scale):
                    self.resize(root, app, scale)
                    app.workspace_layout.select('Readiness')
                    root.update()
                    self.assertTrue(row.winfo_ismapped())
                    left, top = row.winfo_rootx(), row.winfo_rooty()
                    right, bottom = left + row.winfo_width(), top + row.winfo_height()
                    for action in actions:
                        self.assertTrue(action.winfo_ismapped())
                        self.assertGreaterEqual(action.winfo_width(), action.winfo_reqwidth() - 1,
                                                f'{action.cget("text")} shrank below its requested width')
                        self.assertGreaterEqual(action.winfo_rootx(), left)
                        self.assertGreaterEqual(action.winfo_rooty(), top)
                        self.assertLessEqual(action.winfo_rootx() + action.winfo_width(), right + 1)
                        self.assertLessEqual(action.winfo_rooty() + action.winfo_height(), bottom + 1)


if __name__ == '__main__':
    unittest.main()
