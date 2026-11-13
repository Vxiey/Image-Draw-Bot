"""Destroyed previews release application callback owners before worker GC."""
import tkinter as tk
import unittest
from unittest.mock import patch
import weakref

from UiKeyboardNavigation import KeyboardPreviewCanvas


class PreviewCallbackRetirementTests(unittest.TestCase):
    def test_destroy_releases_every_callback_owner_without_cyclic_collection(self):
        class Owner:
            def callback(self, *args):
                raise AssertionError('A destroyed preview invoked its old owner')

        canvas = object.__new__(KeyboardPreviewCanvas)
        names = ('_get_preview_zoom', '_set_preview_zoom', '_step_preview_zoom',
                 '_preview_pan_changed', '_preview_available')
        owners = []
        for name in names:
            owner = Owner()
            owner.canvas = canvas
            owners.append(weakref.ref(owner))
            setattr(canvas, name, owner.callback)
        del owner
        with patch.object(tk.Canvas, 'destroy') as native_destroy:
            canvas.destroy()
            native_destroy.assert_called_once_with()
        self.assertTrue(canvas._keyboard_closed)
        self.assertTrue(all(reference() is None for reference in owners))
        self.assertFalse(canvas._keyboard_focusable())

    def test_native_destroy_handlers_can_still_inspect_callbacks(self):
        canvas = object.__new__(KeyboardPreviewCanvas)
        canvas._get_preview_zoom = lambda: 1.25
        observed = []
        def native_destroy():
            observed.append(canvas._get_preview_zoom())
            self.assertTrue(canvas._keyboard_closed)
            self.assertFalse(canvas._keyboard_focusable())
        with patch.object(tk.Canvas, 'destroy', side_effect=native_destroy):
            canvas.destroy()
        self.assertEqual(observed, [1.25])
        self.assertIsNone(canvas._get_preview_zoom)

    def test_native_destroy_failure_does_not_retain_callbacks_and_can_be_retried(self):
        canvas = object.__new__(KeyboardPreviewCanvas)
        with patch.object(tk.Canvas, 'destroy', side_effect=[tk.TclError('closing'), None]) as native:
            with self.assertRaises(tk.TclError):
                canvas.destroy()
            canvas.destroy()
        self.assertEqual(native.call_count, 2)
        self.assertTrue(canvas._keyboard_closed)
        self.assertIsNone(canvas._preview_available)


if __name__ == '__main__':
    unittest.main()
