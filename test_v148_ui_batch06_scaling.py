"""Replay real CTk pack calls after a disclosure/profile hides their anchor."""
from types import SimpleNamespace
import sys
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import customtkinter as ctk
from customtkinter.windows.widgets.scaling import CTkScalingBaseClass

import ProfileIsolation
from UICompactLayout import pack_in_order


class PackInterpreter:
    """Model Tk's packed-sibling requirement at the native command boundary."""
    def __init__(self):
        self.order = []
        self.options = {}
        self.calls = []

    def call(self, *args):
        if len(args) == 1 and isinstance(args[0], tuple):
            args = args[0]
        self.calls.append(args)
        if args[:2] == ('winfo', 'manager'):
            return 'pack' if args[2] in self.order else ''
        if args[:2] == ('pack', 'forget'):
            if args[2] in self.order:
                self.order.remove(args[2])
            return ''
        if args[:2] != ('pack', 'configure'):
            return ''  # The frame's dimension configure is independent.
        name = args[2]
        options = dict(zip(args[3::2], args[4::2]))
        anchor = options.get('-before', options.get('-after'))
        if anchor is not None and str(anchor) not in self.order:
            raise tk.TclError(f'window "{anchor}" isn\'t packed')
        if anchor is not None:
            if name in self.order:
                self.order.remove(name)
            index = self.order.index(str(anchor)) + ('-after' in options)
            self.order.insert(index, name)
        elif name not in self.order:
            self.order.append(name)
        self.options.setdefault(name, {}).update(options)
        return ''


def frame(engine, name):
    # Use CTk's actual pack/cache/scaling implementation, without constructing
    # a window or running its process-global DPI tracker.
    widget = object.__new__(ctk.CTkFrame)
    widget._w = name
    widget.tk = engine
    widget._last_geometry_manager_call = None
    widget._desired_width = 100
    widget._desired_height = 30
    widget._apply_widget_scaling = lambda value: value * 1.5
    widget._apply_argument_scaling = lambda options: {
        key: value * 1.5 if key in ('padx', 'pady') else value
        for key, value in options.items()
    }
    return widget


class ScalingReplayTests(unittest.TestCase):
    def rescale(self, widget):
        with patch.object(CTkScalingBaseClass, '_set_scaling'):
            ctk.CTkBaseClass._set_scaling(widget, 1.5, 1)

    def test_baseline_ctk_replay_reproduces_the_reported_hidden_anchor_error(self):
        engine = PackInterpreter()
        anchor, child = frame(engine, '.anchor'), frame(engine, '.child')
        anchor.pack()
        child.pack(after=anchor, padx=6)
        anchor.pack_forget()
        with self.assertRaisesRegex(tk.TclError, "isn't packed"):
            self.rescale(child)

    def test_successful_ordering_keeps_its_position_and_logical_padding_on_replay(self):
        for position in ('before', 'after'):
            with self.subTest(position=position):
                engine = PackInterpreter()
                first, anchor, last, child = [frame(engine, '.' + name)
                                             for name in ('first', 'anchor', 'last', 'child')]
                for widget in (first, anchor, last):
                    widget.pack()
                pack_in_order(child, **{position: anchor, 'fill': 'x', 'padx': 6})
                index = engine.order.index('.anchor') + (position == 'after')
                self.assertEqual(engine.order.index('.child'), index if position == 'after' else index - 1)
                self.assertEqual(child._last_geometry_manager_call['kwargs'], {'fill': 'x', 'padx': 6})
                anchor.pack_forget()
                expected = list(engine.order)
                self.rescale(child)
                self.assertEqual(engine.order, expected)
                self.assertEqual(engine.options['.child']['-padx'], 9)
                self.assertEqual(child._last_geometry_manager_call['kwargs']['padx'], 6)

    def test_profile_visibility_also_removes_temporary_order_dependencies(self):
        engine = PackInterpreter()
        child, anchor = frame(engine, '.profile'), frame(engine, '.anchor')
        child.master = SimpleNamespace(winfo_children=lambda: [child, anchor])
        anchor.pack()
        app = SimpleNamespace(_scoped_profile_controls=[(child, 'paint', {'padx': 6})])
        ProfileIsolation.update_visibility(app, 'microsoft-paint')
        self.assertEqual(engine.order, ['.profile', '.anchor'])
        self.assertNotIn('before', child._last_geometry_manager_call['kwargs'])
        anchor.pack_forget()
        self.rescale(child)
        self.assertEqual(engine.order, ['.profile'])

    def test_initial_pack_failure_is_not_suppressed(self):
        widget = Mock()
        error = tk.TclError('invalid sibling')
        widget.pack.side_effect = error
        with self.assertRaises(tk.TclError) as raised:
            pack_in_order(widget, before=object())
        self.assertIs(raised.exception, error)


@unittest.skipUnless(sys.platform == 'win32', 'Actual Windows CTk DPI replay')
class WindowsScalingReplayTests(unittest.TestCase):
    def test_native_pack_order_survives_hiding_its_anchor_and_repeated_scaling(self):
        root = ctk.CTk()
        try:
            first, anchor, last, child = [ctk.CTkFrame(root, height=25) for _ in range(4)]
            for widget in (first, anchor, last):
                widget.pack(fill='x')
            pack_in_order(child, after=anchor, fill='x', padx=6)
            root.update()
            self.assertEqual(root.pack_slaves(), [first, anchor, child, last])
            anchor.pack_forget()
            for scale in (1.5, 1.0, 1.5):
                ctk.set_widget_scaling(scale)
                root.update()
                self.assertEqual(root.pack_slaves(), [first, child, last])
                self.assertTrue(child.winfo_ismapped())
                self.assertEqual(child._last_geometry_manager_call['kwargs']['padx'], 6)
                self.assertEqual(child.pack_info()['padx'], round(6 * child._get_widget_scaling()))
        finally:
            root.destroy()
            ctk.set_widget_scaling(1.0)


if __name__ == '__main__':
    unittest.main()
