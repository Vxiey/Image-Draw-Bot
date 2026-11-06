from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest import mock

import AppBranding as branding


class DestroyRetryTests(unittest.TestCase):
    def install(self, root):
        with mock.patch.object(branding.sys, "platform", "win32"):
            branding._install_destroy_guard(root)

    def test_real_tcl_failure_does_not_mark_live_window_destroyed_or_block_retry(self):
        original = mock.Mock(side_effect=[tk.TclError('bad window path name ".child"'), None])
        root = SimpleNamespace(destroy=original)
        self.install(root)
        with mock.patch("TaskbarIdentity.clear_window_identity"):
            with self.assertRaises(tk.TclError):
                root.destroy()
            self.assertFalse(getattr(root, "_image_draw_bot_destroyed", False))
            self.assertFalse(root._image_draw_bot_destroying)
            root.destroy()
            root.destroy()
        self.assertEqual(original.call_count, 2)
        self.assertTrue(root._image_draw_bot_destroyed)

    def test_reentrant_destroy_and_already_destroyed_tcl_state_remain_idempotent(self):
        root = SimpleNamespace()
        original = mock.Mock(side_effect=lambda: root.destroy())
        root.destroy = original
        self.install(root)
        with mock.patch("TaskbarIdentity.clear_window_identity"):
            root.destroy()
            root.destroy()
        original.assert_called_once()
        root = SimpleNamespace(destroy=mock.Mock(side_effect=tk.TclError('application has been destroyed')))
        original = root.destroy
        self.install(root)
        with mock.patch("TaskbarIdentity.clear_window_identity"):
            root.destroy()
            root.destroy()
        original.assert_called_once()
        self.assertTrue(root._image_draw_bot_destroyed)


if __name__ == "__main__":
    unittest.main()
