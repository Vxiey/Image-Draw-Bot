"""Actual profile/worker/modal methods retain one coherent application context."""
from types import SimpleNamespace
import threading
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from DrawBot import DrawBotApp
from test_v148_application_batch04_settings import Value
from test_v148_application_batch07_mobile import IdleQueue


class ProfileTransactionTests(unittest.TestCase):
    def app(self):
        app = SimpleNamespace(activity=None, closing=False, profile_change_in_progress=False,
            profile_change_after=None, profile_change_ticket=None, root=IdleQueue(),
            game=Value('Other drawing app'), _active_profile_name='Other drawing app',
            plan=object(), corners=[(10, 20), (110, 120)], render_resume=object(),
            calibration_path='active-palette.json', settings_path='active-settings.json',
            status=Mock(), save_settings=Mock(return_value=True), mouse=Mock(),
            set_busy=Mock(), stop=threading.Event(), profile_selector=Mock())
        app._apply_profile_change = lambda selected, **kwargs: DrawBotApp._apply_profile_change(app, selected, **kwargs)
        app.change_profile = lambda: DrawBotApp.change_profile(app)
        return app

    def test_selecting_active_profile_preserves_geometry_plan_resume_and_settings(self):
        app = self.app()
        state = (app.plan, app.render_resume, list(app.corners), app.settings_path, app.calibration_path)
        with patch.object(DrawBotApp, '_clear_render_resume') as clear, \
                patch.object(DrawBotApp, '_disarm_manual_drop_in') as disarm:
            DrawBotApp.change_profile(app)
        self.assertEqual((app.plan, app.render_resume, app.corners, app.settings_path, app.calibration_path), state)
        app.save_settings.assert_not_called(); app.mouse.disarm_input.assert_not_called()
        clear.assert_not_called(); disarm.assert_not_called()
        self.assertFalse(app.root.jobs)

    def test_return_to_active_selection_cancels_queued_change_and_old_callback(self):
        app = self.app(); app.game.set('Microsoft Paint')
        with patch.object(DrawBotApp, '_clear_render_resume'), \
                patch.object(DrawBotApp, '_disarm_manual_drop_in'):
            DrawBotApp.change_profile(app)
        old_callback = next(iter(app.root.jobs.values()))
        app.game.set(app._active_profile_name)
        DrawBotApp.change_profile(app)
        old_callback()
        self.assertIsNone(app.profile_change_after)
        self.assertFalse(app.root.jobs)
        self.assertEqual(app.game.get(), app._active_profile_name)
        self.assertEqual(app.settings_path, 'active-settings.json')

    def test_stale_callback_cannot_clear_a_newer_profile_request(self):
        app = self.app()
        with patch.object(DrawBotApp, '_clear_render_resume'), \
                patch.object(DrawBotApp, '_disarm_manual_drop_in'):
            app.game.set('Microsoft Paint'); DrawBotApp.change_profile(app)
            old_callback = next(iter(app.root.jobs.values()))
            app.game.set('Gartic Phone'); DrawBotApp.change_profile(app)
        new_ticket, new_job = app.profile_change_ticket, app.profile_change_after
        old_callback()
        self.assertIs(app.profile_change_ticket, new_ticket)
        self.assertEqual(app.profile_change_after, new_job)
        self.assertEqual(app.game.get(), 'Gartic Phone')

    def test_pending_selection_cannot_start_a_worker_with_old_profile_paths(self):
        app = self.app(); app.game.set('Microsoft Paint')
        with patch.object(DrawBotApp, '_clear_render_resume'), \
                patch.object(DrawBotApp, '_disarm_manual_drop_in'):
            DrawBotApp.change_profile(app)
        app.stop.set(); task = Mock()
        with patch('DrawBot.threading.Thread') as thread:
            self.assertFalse(DrawBotApp.begin_worker(app, 'load', task))
        thread.assert_not_called(); task.assert_not_called(); app.set_busy.assert_not_called()
        self.assertTrue(app.stop.is_set())
        self.assertIsNotNone(app.profile_change_after)
        self.assertEqual(app.settings_path, 'active-settings.json')

    def test_busy_callback_restores_active_name_without_touching_profile_files(self):
        app = self.app(); app.game.set('Microsoft Paint'); app.activity = 'draw'
        app.profile_change_after = 123
        DrawBotApp._apply_profile_change(app, 'Microsoft Paint')
        self.assertEqual(app.game.get(), app._active_profile_name)
        self.assertIsNone(app.profile_change_after)
        self.assertEqual(app.settings_path, 'active-settings.json')
        self.assertEqual(app.calibration_path, 'active-palette.json')

    def test_internal_same_profile_reload_still_reaches_reset_for_import_and_reset(self):
        app = self.app()
        with patch.object(DrawBotApp, '_close_smart_drop_overlay'), \
                patch('ProfileIsolation.reset_settings', side_effect=RuntimeError('reached reset')) as reset:
            with self.assertRaisesRegex(RuntimeError, 'reached reset'):
                DrawBotApp._apply_profile_change(app, app._active_profile_name)
        reset.assert_called_once_with(app)
        self.assertFalse(app.profile_change_in_progress)

    def test_shutdown_callbacks_do_not_touch_destroyed_tk_profile_variables(self):
        app = self.app(); app.closing = True
        app.game = Mock()
        app.game.get.side_effect = tk.TclError('application destroyed')
        app.game.set.side_effect = tk.TclError('application destroyed')
        DrawBotApp.change_profile(app)
        DrawBotApp._apply_profile_change(app, 'Microsoft Paint')
        app.game.get.assert_not_called(); app.game.set.assert_not_called()

    def test_pending_profile_and_shutdown_block_all_direct_calibration_entry_points(self):
        names = ('set_boundary', 'calibrate_paint_tools', 'calibrate_app_tools',
                 'calibrate_exact_colors', 'calibrate', 'add_profile')
        for state in ('pending', 'in-progress', 'closing'):
            for name in names:
                app = self.app()
                if state == 'pending': app.profile_change_after = 1
                elif state == 'in-progress': app.profile_change_in_progress = True
                else: app.closing = True
                with self.subTest(state=state, method=name), \
                        patch('tkinter.simpledialog.askstring') as ask:
                    getattr(DrawBotApp, name)(app)
                ask.assert_not_called(); app.set_busy.assert_not_called()
                app.profile_selector.configure.assert_not_called()

    def test_modal_profile_creation_rechecks_worker_profile_and_shutdown_before_write(self):
        for state in ('draw', 'pending', 'closing'):
            app = self.app()
            def answer(*args, **kwargs):
                if state == 'draw': app.activity = 'draw'
                elif state == 'pending': app.profile_change_after = 7
                else: app.closing = True
                return 'New fixture target'
            with self.subTest(state=state), patch('tkinter.simpledialog.askstring', side_effect=answer), \
                    patch('GameProfiles.add_custom_profile') as write:
                self.assertFalse(DrawBotApp.add_profile(app))
            write.assert_not_called()
            self.assertEqual(app.game.get(), app._active_profile_name)


class ReadonlyPasteTests(unittest.TestCase):
    def test_readonly_combobox_imports_but_editable_and_disabled_controls_retain_native_paste(self):
        for state in ('readonly', 'normal', 'disabled'):
            widget = object.__new__(ttk.Combobox)
            widget.instate = Mock(side_effect=lambda states: states == [state])
            app = SimpleNamespace(root=Mock(), paste_image=Mock())
            result = DrawBotApp.paste_shortcut(app, SimpleNamespace(widget=widget))
            if state == 'readonly':
                self.assertEqual(result, 'break'); app.paste_image.assert_called_once()
            else:
                self.assertIsNone(result); app.paste_image.assert_not_called()
        for kind in (tk.Entry, ttk.Entry, tk.Text, tk.Spinbox, ttk.Spinbox):
            widget = object.__new__(kind)
            app = SimpleNamespace(root=Mock(), paste_image=Mock())
            self.assertIsNone(DrawBotApp.paste_shortcut(app, SimpleNamespace(widget=widget)))
            app.paste_image.assert_not_called()

    def test_disappearing_widget_name_does_not_redirect_text_paste_to_image_import(self):
        app = SimpleNamespace(root=Mock(), paste_image=Mock())
        app.root.nametowidget.side_effect = tk.TclError('gone')
        self.assertIsNone(DrawBotApp.paste_shortcut(app, SimpleNamespace(widget='.gone')))
        app.paste_image.assert_not_called()


if __name__ == '__main__':
    unittest.main()
