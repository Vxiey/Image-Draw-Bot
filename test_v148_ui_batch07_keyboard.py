"""Local button key gestures preserve controller gates and widget lifetimes."""
from types import SimpleNamespace
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk

from UiKeyboardNavigation import KeyboardButton
import StudioUI


class Scheduler:
    def __init__(self):
        self.pending = {}
        self.serial = 0

    def after_idle(self, callback):
        self.serial += 1
        self.pending[self.serial] = callback
        return self.serial

    def after_cancel(self, token):
        self.pending.pop(token, None)

    def flush(self):
        callbacks = tuple(self.pending.values())
        self.pending.clear()
        for callback in callbacks:
            callback()


def key(symbol='Return', state=0):
    return SimpleNamespace(keysym=symbol, state=state)


def button_without_window():
    button = object.__new__(KeyboardButton)
    button._state = 'normal'
    button._command = Mock()
    button._keyboard_closed = False
    button._keyboard_pressed = None
    button._keyboard_job = None
    button.winfo_exists = Mock(return_value=True)
    button.winfo_ismapped = Mock(return_value=True)
    button.focus_get = Mock(return_value=button)
    button._keyboard_draw_focus = Mock()
    schedule = Scheduler()
    button.after_idle = schedule.after_idle
    button.after_cancel = schedule.after_cancel
    return button, schedule


class ScrollCanvas:
    def __init__(self, rootx=100, rooty=100, width=200, height=200):
        self.rootx, self.rooty = rootx, rooty
        self.width, self.height = width, height
        self.left = self.top = 0
        self.extent = 1400
        self.scrolls = []

    def winfo_rootx(self):
        return self.rootx() if callable(self.rootx) else self.rootx

    def winfo_rooty(self):
        return self.rooty() if callable(self.rooty) else self.rooty

    def winfo_width(self): return self.width
    def winfo_height(self): return self.height
    def bbox(self, _item): return (0, 0, self.extent, self.extent)
    def canvasx(self, value): return self.left + value
    def canvasy(self, value): return self.top + value

    def xview_moveto(self, fraction):
        self.left = max(0, min(self.extent - self.width, fraction * self.extent))
        self.scrolls.append(('x', self.left))

    def yview_moveto(self, fraction):
        self.top = max(0, min(self.extent - self.height, fraction * self.extent))
        self.scrolls.append(('y', self.top))


def scroll_frame(canvas, master=None, orientation='vertical'):
    frame = object.__new__(ctk.CTkScrollableFrame)
    frame.master = master
    frame._parent_canvas = canvas
    frame._orientation = orientation
    frame._create_window_id = 1
    return frame


class ButtonKeyboardTests(unittest.TestCase):
    def test_return_keypad_enter_and_space_use_the_existing_ctk_invoke(self):
        for symbol in ('Return', 'KP_Enter', 'space'):
            with self.subTest(symbol=symbol):
                button, schedule = button_without_window()
                self.assertEqual(button._keyboard_key_press(key(symbol)), 'break')
                button._command.assert_not_called()
                self.assertEqual(button._keyboard_key_release(key(symbol)), 'break')
                schedule.flush()
                button._command.assert_called_once_with()
                button._keyboard_key_release(key(symbol))
                schedule.flush()
                button._command.assert_called_once_with()

    def test_repeated_presses_and_x11_release_press_pairs_activate_once(self):
        button, schedule = button_without_window()
        for _ in range(20):
            button._keyboard_key_press(key())
        button._keyboard_key_release(key())
        button._keyboard_key_press(key())
        self.assertFalse(schedule.pending)
        button._command.assert_not_called()
        button._keyboard_key_release(key())
        schedule.flush()
        button._command.assert_called_once_with()

    def test_disabled_hidden_destroyed_and_unfocused_buttons_cannot_activate(self):
        for changed in ('disabled', 'hidden', 'destroyed', 'focus', 'closed'):
            with self.subTest(changed=changed):
                button, schedule = button_without_window()
                button._keyboard_key_press(key())
                button._keyboard_key_release(key())
                if changed == 'disabled':
                    button._state = 'disabled'
                elif changed == 'hidden':
                    button.winfo_ismapped.return_value = False
                elif changed == 'destroyed':
                    button.winfo_exists.return_value = False
                elif changed == 'focus':
                    button.focus_get.return_value = None
                else:
                    button._keyboard_closed = True
                schedule.flush()
                button._command.assert_not_called()

    def test_focus_loss_or_pointer_press_cancels_pending_keyboard_activation(self):
        for action in ('_keyboard_focus_out', '_keyboard_pointer_focus'):
            with self.subTest(action=action):
                button, schedule = button_without_window()
                button.focus_set = Mock()
                button._keyboard_key_press(key())
                button._keyboard_key_release(key())
                getattr(button, action)()
                self.assertFalse(schedule.pending)
                schedule.flush()
                button._command.assert_not_called()

    def test_modified_shortcuts_and_unmatched_releases_are_not_activation(self):
        button, schedule = button_without_window()
        for symbol, state in (('Return', 4), ('space', 8), ('Return', 0x20000), ('Escape', 0)):
            self.assertIsNone(button._keyboard_key_press(key(symbol, state)))
            button._keyboard_key_release(key(symbol, state))
        schedule.flush()
        button._command.assert_not_called()

    def test_disabled_or_unmapped_button_is_not_a_tab_stop(self):
        button, _ = button_without_window()
        self.assertTrue(button._keyboard_focusable('.button'))
        button._state = 'disabled'
        self.assertFalse(button._keyboard_focusable('.button'))
        button._state = 'normal'
        button.winfo_ismapped.return_value = False
        self.assertFalse(button._keyboard_focusable('.button'))
        button.winfo_ismapped.return_value = True
        button._command = None
        self.assertFalse(button._keyboard_focusable('.button'))

    def test_destroy_cancels_an_idle_release_before_the_underlying_widget_dies(self):
        button, schedule = button_without_window()
        button._keyboard_key_press(key())
        button._keyboard_key_release(key())
        with patch.object(ctk.CTkButton, 'destroy') as destroy:
            button.destroy()
        destroy.assert_called_once_with()
        self.assertTrue(button._keyboard_closed)
        self.assertFalse(schedule.pending)
        schedule.flush()
        button._command.assert_not_called()

    def test_programmatic_focus_targets_the_logical_button(self):
        button, _ = button_without_window()
        with patch.object(tk.Misc, 'focus_set') as focus:
            button.focus_set()
        focus.assert_called_once_with(button)
        with patch.object(tk.Misc, 'focus_force') as force:
            button.focus_force()
        force.assert_called_once_with(button)

    def test_existing_tooltip_uses_logical_focus_and_preserves_pointer_bindings(self):
        button, schedule = button_without_window()
        button._canvas = Mock()
        button._text_label = button._image_label = None
        button.after = Mock(side_effect=lambda _delay, callback: schedule.after_idle(callback))
        bound = {}
        def bind(widget, sequence, callback, **kwargs):
            self.assertIs(widget, button)
            self.assertEqual(kwargs, {'add': '+'})
            bound[sequence] = callback
        with patch.object(tk.Misc, 'bind', side_effect=bind):
            tip = StudioUI.ToolTip(button, 'Keyboard help')
        self.assertEqual(set(bound), {'<FocusIn>', '<FocusOut>'})
        self.assertEqual([call.args[0] for call in button._canvas.bind.call_args_list],
                         ['<Enter>', '<Leave>', '<ButtonPress>', '<Destroy>'])
        bound['<FocusIn>']()
        button.after.assert_called_once_with(450, tip._show)
        self.assertEqual(len(schedule.pending), 1)
        window = Mock(); tip.window = window
        bound['<FocusOut>']()
        self.assertFalse(schedule.pending)
        window.destroy.assert_called_once_with()
        self.assertIsNone(tip.window)

    def test_focus_reveals_vertical_and_horizontal_canvas_children_before_activation(self):
        for orientation in ('vertical', 'horizontal'):
            with self.subTest(orientation=orientation):
                button, schedule = button_without_window()
                canvas = ScrollCanvas()
                button.master = scroll_frame(canvas, orientation=orientation)
                button.winfo_rootx = lambda: canvas.winfo_rootx() + (900 if orientation == 'horizontal' else 20) - canvas.left
                button.winfo_rooty = lambda: canvas.winfo_rooty() + (900 if orientation == 'vertical' else 20) - canvas.top
                button.winfo_width = lambda: 80
                button.winfo_height = lambda: 35
                self.assertFalse(button._keyboard_in_view())
                button._keyboard_focus_in()
                self.assertEqual(len(canvas.scrolls), 1)
                self.assertTrue(button._keyboard_in_view())
                button._keyboard_key_press(key()); button._keyboard_key_release(key()); schedule.flush()
                button._command.assert_called_once_with()
                # Scrolling away while it retains focus must not activate an
                # invisible action merely because Tk still says it is mapped.
                canvas.left = canvas.top = 0
                button._keyboard_key_press(key()); button._keyboard_key_release(key()); schedule.flush()
                button._command.assert_called_once_with()

    def test_nested_scrollframes_reveal_from_inside_out(self):
        button, schedule = button_without_window()
        outer_canvas = ScrollCanvas()
        outer = scroll_frame(outer_canvas)
        inner_canvas = ScrollCanvas(rooty=lambda: outer_canvas.winfo_rooty() + 800 - outer_canvas.top,
                                   height=150)
        button.master = scroll_frame(inner_canvas, master=outer)
        button.winfo_rootx = lambda: 120
        button.winfo_rooty = lambda: inner_canvas.winfo_rooty() + 900 - inner_canvas.top
        button.winfo_width = lambda: 80
        button.winfo_height = lambda: 35
        button._keyboard_focus_in()
        self.assertEqual(len(inner_canvas.scrolls), 1)
        self.assertEqual(len(outer_canvas.scrolls), 1)
        self.assertTrue(button._keyboard_in_view())
        button._keyboard_key_press(key()); button._keyboard_key_release(key()); schedule.flush()
        button._command.assert_called_once_with()

    def test_failed_reveal_does_not_authorize_a_clipped_button(self):
        button, schedule = button_without_window()
        canvas = ScrollCanvas()
        canvas.yview_moveto = Mock(side_effect=tk.TclError('viewport destroyed'))
        button.master = scroll_frame(canvas)
        button.winfo_rootx = lambda: 120
        button.winfo_rooty = lambda: 1000
        button.winfo_width = lambda: 80
        button.winfo_height = lambda: 35
        button._keyboard_focus_in()
        button._keyboard_key_press(key()); button._keyboard_key_release(key()); schedule.flush()
        button._command.assert_not_called()


@unittest.skipUnless(sys.platform == 'win32', 'Actual Windows Tk button key delivery')
class WindowsButtonKeyboardTests(unittest.TestCase):
    def setUp(self):
        from UiCompatibility import scoped_window_class
        self.root = scoped_window_class(ctk.CTk)()
        self.root.geometry('480x360')
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.addCleanup(self.root.destroy)

    def press(self, button, symbol='Return', repeats=1):
        for _ in range(repeats):
            button.event_generate('<KeyPress-' + symbol + '>', when='now')
        button.event_generate('<KeyRelease-' + symbol + '>', when='now')
        self.root.update()

    def test_native_tab_order_keys_focus_indicator_and_teardown(self):
        before = {name: self.root.bind_all(name) for name in ('<Return>', '<space>', '<Tab>')}
        entry = ttk.Entry(self.root)
        entry.pack()
        first_call, disabled_call, last_call = Mock(), Mock(), Mock()
        first = StudioUI.button(self.root, 'First action', first_call)
        disabled = StudioUI.button(self.root, 'Disabled action', disabled_call, state='disabled')
        last = StudioUI.button(self.root, 'Last action', last_call)
        for button in (first, disabled, last):
            button.pack(pady=5)
        StudioUI.tooltip(first, 'A setting action')
        tip = first._image_draw_bot_tooltip
        tip.delay = 0
        self.root.update()
        self.assertIs(entry.tk_focusNext(), first)
        self.assertIs(first.tk_focusNext(), last)
        self.assertIs(last.tk_focusPrev(), first)
        first.focus_force()
        self.root.update()
        self.assertIs(self.root.focus_get(), first)
        self.assertEqual(len(first._canvas.find_withtag(first._focus_tag)), 1)
        self.assertIsNotNone(tip.window)
        entry.focus_force(); self.root.update()
        self.assertIsNone(tip.window)
        first.focus_force(); self.root.update()
        self.press(first, repeats=8)
        first_call.assert_called_once_with()
        self.press(first, 'space')
        self.assertEqual(first_call.call_count, 2)
        disabled.focus_force()
        self.root.update()
        self.press(disabled)
        disabled_call.assert_not_called()

        # Recreated CTk labels and tooltip focus bindings must not add stops.
        first.configure(text='')
        first.configure(text='Recreated label')
        StudioUI.tooltip(first, 'Updated help')
        self.root.update()
        self.assertIs(first.tk_focusNext(), last)
        first.focus_force()
        self.root.update()
        first.event_generate('<KeyPress-Return>', when='now')
        first.event_generate('<KeyRelease-Return>', when='now')
        tokens = tuple(token for token in first._tclCommands if '_keyboard_' in token)
        first.destroy()
        self.root.update()
        self.assertEqual(first_call.call_count, 2)
        for token in tokens:
            self.assertFalse(self.root.tk.call('info', 'commands', token))
        self.assertEqual({name: self.root.bind_all(name) for name in before}, before)
        self.assertFalse(self.errors, self.errors)

    def test_tab_to_a_scrolled_out_action_reveals_it_before_key_activation(self):
        panel = ctk.CTkScrollableFrame(self.root, width=400, height=130)
        panel.pack(fill='x', padx=10, pady=10)
        first = StudioUI.button(panel, 'First action', Mock())
        first.pack(pady=5)
        ctk.CTkFrame(panel, width=10, height=900).pack()
        action = Mock()
        last = StudioUI.button(panel, 'Last action', action)
        last.pack(pady=5)
        self.root.update()
        self.assertTrue(last.winfo_ismapped())
        self.assertFalse(last._keyboard_in_view())
        first.focus_force(); self.root.update()
        first.event_generate('<Tab>', when='now'); self.root.update()
        self.assertIs(self.root.focus_get(), last)
        self.assertTrue(last._keyboard_in_view())
        canvas = panel._parent_canvas
        self.assertGreaterEqual(last.winfo_rooty(), canvas.winfo_rooty())
        self.assertLessEqual(last.winfo_rooty() + last.winfo_height(),
                             canvas.winfo_rooty() + canvas.winfo_height())
        self.press(last)
        action.assert_called_once_with()
        canvas.yview_moveto(0); self.root.update()
        self.assertTrue(last.winfo_ismapped())
        self.assertFalse(last._keyboard_in_view())
        self.press(last)
        action.assert_called_once_with()
        self.assertFalse(self.errors, self.errors)

    def test_native_keyboard_start_uses_the_actual_controller_setup_guard(self):
        from DrawBot import DrawBotApp
        app = SimpleNamespace(activity=None, closing=False, game=SimpleNamespace(get=lambda: 'Other drawing app'),
            _start_guard_ready=Mock(return_value=(False, 'Load an image first.')),
            _disarm_full_draw=Mock(), status=Mock(), summary=Mock())
        button = StudioUI.button(self.root, 'Start Drawing', lambda: DrawBotApp.start_full_drawing(app))
        button.pack()
        self.root.update()
        button.focus_force()
        self.root.update()
        with patch.object(DrawBotApp, 'draw') as draw, patch('DrawBot.log_event'):
            self.press(button, 'space')
        app._start_guard_ready.assert_called_once_with(require_image=True)
        app.status.set.assert_called_once_with('Load an image first.')
        draw.assert_not_called()
        self.assertFalse(self.errors, self.errors)


if __name__ == '__main__':
    unittest.main()
