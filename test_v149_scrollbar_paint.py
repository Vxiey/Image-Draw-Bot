"""A Canvas scrollbar report must never paint inside another Tk idle flush."""
import gc
import os
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
import weakref

import customtkinter as ctk

from UiCompatibility import _ScrollbarPaint, scoped_window_class


class ScrollbarSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.tcl = tk.Tcl()
        self.draws = []
        self.depth = 0
        self.maximum_depth = 0
        self.inject = None
        # Use the real CTk scrollbar set/get path and the interpreter's native
        # idle/timer queues. The drawing surface is the one controlled boundary.
        self.bar = object.__new__(ctk.CTkScrollbar)
        self.bar._start_value, self.bar._end_value = 0., 1.
        self.bar._current_width = 12
        self.bar._draw = self.draw
        self.bar.after = self.tcl.after
        self.bar.after_idle = self.tcl.after_idle
        self.bar.after_cancel = self.tcl.after_cancel
        self.canvas = Mock()
        frame = SimpleNamespace(_scrollbar=self.bar, _orientation='vertical', _parent_canvas=self.canvas)
        with patch.object(tk.Misc, 'bind'):
            self.owner = _ScrollbarPaint(frame)
        self.viewport = self.canvas.configure.call_args.kwargs['yscrollcommand']
        self.addCleanup(self.cleanup_paint)

    def cleanup_paint(self):
        self.owner.dispose(SimpleNamespace(widget=self.bar))
        # Release references to this actual Tcl interpreter on its creator thread.
        self.bar.__dict__.clear()
        self.canvas.reset_mock()
        self.viewport = self.owner = self.tcl = self.bar = None

    def draw(self, no_color_updates=False):
        self.depth += 1
        self.maximum_depth = max(self.maximum_depth, self.depth)
        try:
            self.draws.append((self.bar.get(), self.bar._current_width, no_color_updates))
            if self.inject is not None:
                callback, self.inject = self.inject, None
                self.tcl.after_idle(callback)
            # CTkScrollbar._draw in the shipped version ends with this call.
            self.tcl.update_idletasks()
        finally:
            self.depth -= 1

    def test_position_and_resize_inside_paint_use_latest_state_without_reentry(self):
        def while_drawing():
            self.viewport('.1', '.6')
            self.viewport('.2', '.7')
            self.bar._current_width = 31
            self.bar._draw(no_color_updates=True)

        self.inject = while_drawing
        self.viewport('0', '1')
        self.assertIsNone(self.owner.job)
        self.viewport('.03', '.4')
        self.viewport('.05', '.5')
        self.bar._draw(no_color_updates=True)
        self.tcl.update_idletasks()
        self.assertEqual(self.draws, [], 'An idle layout callback re-entered scrollbar painting')
        self.tcl.update()
        self.assertEqual(self.maximum_depth, 1)
        self.assertEqual(self.draws, [((.05, .5), 12, False), ((.2, .7), 31, False)])
        self.viewport('0.2', '0.7')
        self.assertIsNone(self.owner.job)

    def test_destroy_cancels_idle_before_it_creates_a_timer(self):
        self.viewport('.1', '.3')
        idle = self.owner.job
        self.owner.dispose(SimpleNamespace(widget=self.bar))
        self.tcl.update()
        self.assertNotIn(idle, self.tcl.tk.call('after', 'info'))
        self.assertFalse(self.draws)

    def test_destroy_cancels_timer_and_ignores_stale_viewport(self):
        self.viewport('.1', '.3')
        self.assertIn(self.owner.job, self.tcl.tk.call('after', 'info'))
        self.owner.dispose(SimpleNamespace(widget=object()))
        self.tcl.update_idletasks()
        timer = self.owner.job
        self.assertIn(timer, self.tcl.tk.call('after', 'info'))
        self.owner.dispose(SimpleNamespace(widget=self.bar))
        self.viewport('.3', '.7')
        self.tcl.update()
        self.assertFalse(self.draws)
        self.assertNotIn(timer, self.tcl.tk.call('after', 'info'))


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Native Tk display required')
class NativeScrollbarPaintTests(unittest.TestCase):
    def test_real_ctk_painter_does_not_reenter_from_its_native_canvas(self):
        root = scoped_window_class(ctk.CTk)()
        root_ref = weakref.ref(root)
        def retire_owner():
            gc.collect()
            self.assertIsNone(root_ref(), 'A later worker could release the native test interpreter')
        self.addCleanup(retire_owner)
        self.addCleanup(root.destroy)
        root.geometry('250x240')
        bar = ctk.CTkScrollbar(root, orientation='vertical', width=17)
        bar.pack(side='right', fill='y')
        canvas = tk.Canvas(root, scrollregion=(0, 0, 600, 1200))
        canvas.pack(fill='both', expand=True)
        root.update()

        original_draw = bar._draw
        recorded = []
        depth = 0
        inject = False

        def observed(no_color_updates=False):
            nonlocal depth, inject
            depth += 1
            try:
                recorded.append((depth, bar.get(), bar._current_width))
                if inject:
                    inject = False
                    # This is delivered by CTkScrollbar._draw itself, not by a
                    # separate test pump, reproducing the hosted Windows stack.
                    canvas.after_idle(lambda: canvas.yview_moveto(.4))
                    canvas.after_idle(lambda: bar.configure(width=27))
                original_draw(no_color_updates=no_color_updates)
            finally:
                depth -= 1

        bar._draw = observed
        _ScrollbarPaint(SimpleNamespace(_scrollbar=bar, _orientation='vertical', _parent_canvas=canvas))
        root.update()
        recorded.clear()
        inject = True
        bar.set(.1, .3)
        root.update_idletasks()
        self.assertFalse(recorded)
        root.update()
        self.assertTrue(recorded)
        self.assertTrue(all(call[0] == 1 for call in recorded), recorded)
        self.assertAlmostEqual(canvas.yview()[0], .4, delta=.002)
        self.assertEqual(recorded[-1][1:], (canvas.yview(), 27))
        self.assertTrue(bar._canvas.find_withtag('scrollbar_parts'))


if __name__ == '__main__':
    unittest.main()
