import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from GettingStarted import guide_pages, show_guide


class GettingStartedTests(unittest.TestCase):
    def test_profile_instructions_match_paint_and_browser_workflows(self):
        paint = str(guide_pages('Microsoft Paint'))
        browser = str(guide_pages('Gartic Phone'))
        self.assertIn('Prepare Paint & draw', paint)
        self.assertIn('optional', paint)
        self.assertIn('Turn Browser One-Click Mode off', browser)
        self.assertIn('Unlock full drawing and Start drawing', browser)
        for text in (paint, browser):
            self.assertIn('Esc', text)
            self.assertIn('F6', text)
            self.assertIn('erase existing artwork', text)

    @unittest.skipUnless(sys.platform == 'win32', 'Native guide navigation')
    def test_guide_navigation_profile_change_and_close_are_read_only(self):
        import tkinter as tk
        import customtkinter as ctk
        from UiCompatibility import scoped_window_class
        root = scoped_window_class(ctk.CTk)()
        app = SimpleNamespace(root=root, game=tk.StringVar(root, 'Microsoft Paint'))
        try:
            with patch('ReleaseState.mark_welcome_seen') as seen:
                window = show_guide(app)
                self.assertIs(show_guide(app), window)
                window.geometry('540x460')
                root.update()
                nav = next(w for w in window.winfo_children() if isinstance(w, ctk.CTkOptionMenu))
                for title, cards in guide_pages('Microsoft Paint'):
                    nav._dropdown_callback(title)
                    root.update()
                    self.assertEqual(nav.get(), title)
                app.game.set('Gartic Phone')
                nav._dropdown_callback('Start, pause and stop')
                root.update()
                # No action callbacks exist on the stub: guide only reads state.
                self.assertIsNone(window.grab_current())
                window.tk.call(window.protocol('WM_DELETE_WINDOW'))
                self.assertFalse(window.winfo_exists())
                self.assertIsNone(app._getting_started_window)
                seen.assert_called_once()
        finally:
            root.destroy()

    @unittest.skipUnless(sys.platform == 'win32', 'Native tooltip lifecycle')
    def test_tooltip_closes_when_its_control_is_destroyed(self):
        import customtkinter as ctk
        from StudioUI import ToolTip
        from UiCompatibility import scoped_window_class
        root = scoped_window_class(ctk.CTk)()
        try:
            button = ctk.CTkButton(root, text='Setting')
            button.pack()
            root.update()
            tip = ToolTip(button, 'Practical setting explanation.')
            tip._show()
            root.update()
            self.assertIsNotNone(tip.window)
            button.destroy()
            root.update()
            self.assertIsNone(tip.window)
            self.assertIsNone(tip.job)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
