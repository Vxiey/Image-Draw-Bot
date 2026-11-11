"""Custom-profile actions belong to their existing disclosure and profile scope."""
import os
import sys
import unittest

import test_v148_ui_batch36_profile_load as profile_tests


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native Tk display required')
class NativeProfileGroupTests(unittest.TestCase):
    isolated = profile_tests.NativeProfileLoadTests.isolated
    wait = profile_tests.NativeProfileLoadTests.wait
    workspace = profile_tests.NativeProfileLoadTests.workspace
    resize = profile_tests.NativeProfileLoadTests.resize
    select_profile = profile_tests.NativeProfileLoadTests.select_profile

    def test_rename_and_remove_follow_disclosure_keyboard_and_profile_scope(self):
        if self.isolated():
            return
        with self.workspace() as (root, app, _backend, data):
            import customtkinter as ctk
            from GameProfiles import PROFILES, add_custom_profile
            name = 'Review brushes'
            add_custom_profile(name, data / 'profiles.json')
            app.profile_selector.configure(values=list(PROFILES))
            self.select_profile(root, app, name)
            group = next(group for group in app._compact_ui_layout.groups
                         if group.title == 'Profile & ink options')
            row = next(widget for widget, scope, _options in app._scoped_profile_controls
                       if scope == 'custom')
            actions = tuple(widget for widget in row.winfo_children()
                            if isinstance(widget, ctk.CTkButton))
            self.assertEqual([widget.cget('text') for widget in actions], ['Rename…', 'Remove…'])
            self.assertTrue(all(widget.winfo_ismapped() for widget in actions))
            original_padding = row._last_geometry_manager_call['kwargs'].get('pady')

            group.set_open(False)
            root.update()
            self.assertFalse(row.winfo_manager())
            self.assertTrue(all(not widget.winfo_ismapped() for widget in actions))
            # The existing keyboard action opens the same widgets and callback
            # owners; adding grouping must not introduce another tab stop.
            group.toggle.focus_force()
            root.update()
            group.toggle.event_generate('<KeyPress-space>')
            group.toggle.event_generate('<KeyRelease-space>')
            self.wait(root, lambda: group.open, 'Keyboard disclosure did not open')
            self.assertTrue(all(widget.winfo_ismapped() for widget in actions))
            self.assertEqual(tuple(widget for widget in row.winfo_children()
                                   if isinstance(widget, ctk.CTkButton)), actions)

            reset = next(widget for widget in row.master.winfo_children()
                         if isinstance(widget, ctk.CTkButton)
                         and widget.cget('text').endswith('Reset profile to defaults'))
            for scale in (1, 1.5, 2):
                with self.subTest(scale=scale):
                    self.resize(root, app, scale)
                    group.set_open(False)
                    group.set_open(True)
                    root.update()
                    order = row.master.pack_slaves()
                    self.assertGreater(order.index(row), order.index(reset))
                    self.assertEqual(row._last_geometry_manager_call['kwargs'].get('pady'), original_padding)
                    self.assertTrue(all(widget.winfo_ismapped() for widget in actions))

            self.select_profile(root, app, 'Microsoft Paint')
            self.assertFalse(row.winfo_manager())
            group.set_open(False)
            self.select_profile(root, app, name)
            self.assertFalse(row.winfo_manager(), 'Profile refresh reopened a collapsed group member')
            group.set_open(True)
            root.update()
            self.assertTrue(all(widget.winfo_ismapped() for widget in actions))
            self.assertIsNone(app._compact_ui_layout_error)


if __name__ == '__main__':
    unittest.main()
