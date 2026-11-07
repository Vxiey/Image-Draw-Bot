"""Mobile panel actions follow the real local server's current session."""
from contextlib import ExitStack
import http.client
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

import qrcode

from DrawBot import DrawBotApp
from test_v148_ui_workflow_batch05_runtime import Widget


class NativeSurface(Widget):
    """Replace native allocation only; retain real controller and server calls."""
    def __init__(self, master=None, *, kind='widget', **options):
        super().__init__(master, **options)
        self.kind = kind
        self.contents = ''
        self.clipboard = ''

    def insert(self, _index, text):
        self.contents += text

    def delete(self, *_args):
        self.contents = ''

    def clipboard_clear(self):
        self.clipboard = ''

    def clipboard_append(self, text):
        self.clipboard += text

    def update_idletasks(self):
        pass

    def invoke(self):
        if self.options.get('state') != 'disabled':
            return self.options['command']()


class PhotoBoundary:
    def __init__(self, pixels, encoded_url):
        self.pixels, self.encoded_url = pixels, encoded_url
        self.deleted = False
        self.tk = SimpleNamespace(call=self.delete)

    def delete(self, command, operation, name):
        if (command, operation, name) != ('image', 'delete', str(self)):
            raise AssertionError('Expected deletion of this owned native image')
        self.deleted = True
        self.pixels.close()


def descendants(widget):
    for child in tuple(widget.children):
        yield child
        yield from descendants(child)


class MobileDialogWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tcl = tk.Tcl()
        for name, kind in (('CTkToplevel', 'window'), ('CTkFrame', 'frame'),
                           ('CTkLabel', 'label'), ('CTkTextbox', 'text'),
                           ('CTkButton', 'button')):
            class Surface(NativeSurface):
                def __init__(self, *args, _kind=kind, **kwargs):
                    super().__init__(*args, kind=_kind, **kwargs)

            self.stack.enter_context(patch('customtkinter.' + name,
                                          Surface))
        self.stack.enter_context(patch('WorkspaceLayout.fit_window', return_value=(620, 610)))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.addresses = self.stack.enter_context(patch('MobilePreview.local_ipv4_addresses',
                                                       return_value=['127.0.0.1']))
        self.browser = self.stack.enter_context(patch('webbrowser.open', return_value=True))
        self.qr_payloads = []
        original_add_data = qrcode.QRCode.add_data

        def record_data(qr, data, *args, **kwargs):
            self.qr_payloads.append(data)
            return original_add_data(qr, data, *args, **kwargs)

        self.stack.enter_context(patch.object(qrcode.QRCode, 'add_data', record_data))
        self.stack.enter_context(patch('PIL.ImageTk.PhotoImage', self.photo))

    def photo(self, pixels, **_kwargs):
        snapshot = pixels.copy()
        self.addCleanup(snapshot.close)
        return PhotoBoundary(snapshot, self.qr_payloads[-1])

    def app(self):
        app = DrawBotApp.__new__(DrawBotApp)
        app.root = NativeSurface(kind='root')
        self.addCleanup(app.root.destroy)
        app.closing = False
        app.activity = None
        app.mobile_preview_server = None
        app.mobile_preview_after = None
        app.mobile_preview_ticket = None
        app.original = None
        app.plan = None
        for name in ('mobile_preview_url', 'mobile_preview_status', 'status'):
            setattr(app, name, tk.StringVar(self.tcl, value=''))
        self.addCleanup(app.stop_mobile_preview, quiet=True)
        return app

    @staticmethod
    def windows(app):
        return [child for child in app.root.children if child.kind == 'window']

    @staticmethod
    def controls(window):
        widgets = tuple(descendants(window))
        buttons = {widget.options['text']: widget for widget in widgets
                   if widget.kind == 'button'}
        text = next(widget for widget in widgets if widget.kind == 'text')
        qr = next(widget for widget in widgets if widget.kind == 'label'
                  and widget.options.get('image') is not None)
        return buttons, text, qr

    def assert_current_panel(self, app, window):
        buttons, text, qr = self.controls(window)
        url = app.mobile_preview_url.get()
        self.assertEqual(text.contents, url)
        self.assertEqual(qr.options['image'].encoded_url, url)
        self.assertGreater(qr.options['image'].pixels.width, 0)
        buttons['Copy address'].invoke()
        self.assertEqual(app.root.clipboard, url)
        self.browser.reset_mock()
        buttons['Open on this PC'].invoke()
        self.browser.assert_called_once_with(url)
        return url

    def test_reopening_refreshes_the_existing_panel_instead_of_forking_its_address(self):
        app = self.app()
        app.show_mobile_preview()
        first = self.windows(app)[0]
        token = app.mobile_preview_server.token
        self.assert_current_panel(app, first)
        self.addresses.return_value = ['127.0.0.2']
        app.show_mobile_preview()
        with self.subTest(behavior='one live panel'):
            self.assertEqual(self.windows(app), [first])
        with self.subTest(behavior='original visible panel follows refresh'):
            self.assert_current_panel(app, first)
        self.assertEqual(app.mobile_preview_server.token, token)

    def test_stop_closes_the_current_panel_and_restart_rotates_its_real_token(self):
        app = self.app()
        app.show_mobile_preview()
        first = self.windows(app)[0]
        old_token = app.mobile_preview_server.token
        server = app.mobile_preview_server
        app.stop_mobile_preview()
        with self.subTest(phase='stop'):
            self.assertFalse(first.winfo_exists())
            self.assertEqual(self.windows(app), [])
        app.show_mobile_preview()
        self.assertIs(app.mobile_preview_server, server)
        self.assertNotEqual(server.token, old_token)
        self.assert_current_panel(app, self.windows(app)[-1])
        connection = http.client.HTTPConnection('127.0.0.1', server.port, timeout=3)
        self.addCleanup(connection.close)
        for token, expected in ((server.token, 200), (old_token, 404)):
            connection.request('GET', f'/{token}/status.json')
            response = connection.getresponse()
            self.assertEqual(response.status, expected)
            response.read()

    def test_callbacks_retained_from_an_old_panel_cannot_open_copy_or_stop_a_restart(self):
        for action in ('Open on this PC', 'Copy address', 'Stop Mobile Preview'):
            with self.subTest(action=action):
                app = self.app()
                app.show_mobile_preview()
                old = self.controls(self.windows(app)[0])[0][action].options['command']
                app.stop_mobile_preview()
                app.show_mobile_preview()
                server = app.mobile_preview_server
                session = (server.port, server.token)
                app.root.clipboard = 'keep the existing clipboard'
                self.browser.reset_mock()
                old()
                self.browser.assert_not_called()
                self.assertEqual(app.root.clipboard, 'keep the existing clipboard')
                self.assertTrue(server.running)
                self.assertEqual((server.port, server.token), session)

    def test_closing_only_the_panel_keeps_sharing_and_a_later_panel_owns_its_callbacks(self):
        app = self.app()
        app.show_mobile_preview()
        first = self.windows(app)[0]
        session = (app.mobile_preview_server.port, app.mobile_preview_server.token)
        first.protocols['WM_DELETE_WINDOW']()
        self.assertEqual(self.windows(app), [])
        self.assertTrue(app.mobile_preview_server.running)
        app.show_mobile_preview()
        second = self.windows(app)[0]
        self.assertIsNot(second, first)
        first.destroy()
        self.assertTrue(second.winfo_exists())
        self.assertEqual((app.mobile_preview_server.port, app.mobile_preview_server.token), session)
        self.assert_current_panel(app, second)

    def test_failed_construction_or_refresh_releases_the_panel_and_stops_sharing(self):
        for stage in ('construction', 'refresh'):
            with self.subTest(stage=stage):
                app = self.app()
                if stage == 'construction':
                    failure = patch('WorkspaceLayout.fit_window', side_effect=ValueError('geometry failure'))
                else:
                    app.show_mobile_preview()
                    _buttons, address, _qr = self.controls(self.windows(app)[0])
                    failure = patch.object(address, 'insert', side_effect=tk.TclError('widget failure'))
                with failure:
                    app.show_mobile_preview()
                self.assertEqual(self.windows(app), [])
                self.assertIsNone(getattr(app, '_mobile_preview_dialog', None))
                self.assertFalse(app.mobile_preview_server.running)
                self.assertFalse(app.root.jobs)
                self.assertEqual(app.mobile_preview_url.get(), '')
                self.assertIn('Could not start Mobile Preview', app.status.get())
                app.show_mobile_preview()
                self.assert_current_panel(app, self.windows(app)[0])

    def test_failed_qr_refresh_does_not_leave_the_old_session_address_in_an_image(self):
        app = self.app()
        app.show_mobile_preview()
        window = self.windows(app)[0]
        buttons, address, qr = self.controls(window)
        old_url = app.mobile_preview_url.get()
        self.addresses.return_value = ['127.0.0.2']
        with patch('qrcode.QRCode.make', side_effect=ValueError('QR unavailable')):
            app.show_mobile_preview()
        current_url = app.mobile_preview_url.get()
        self.assertNotEqual(current_url, old_url)
        self.assertEqual(self.windows(app), [window])
        self.assertEqual(address.contents, current_url)
        self.assertIsNone(qr.options['image'])
        self.assertIsNone(qr.image)
        self.assertIn('QR code unavailable', qr.options['text'])
        buttons['Copy address'].invoke()
        self.assertEqual(app.root.clipboard, current_url)
        buttons['Open on this PC'].invoke()
        self.browser.assert_called_once_with(current_url)
        self.assertTrue(app.mobile_preview_server.running)

    def test_external_window_destruction_and_late_old_destroy_do_not_clear_the_new_owner(self):
        app = self.app()
        app.show_mobile_preview()
        old_window = self.windows(app)[0]
        late_destroy = old_window.bindings['<Destroy>']
        old_callbacks = [control.options['command']
                         for control in self.controls(old_window)[0].values()]
        old_window.destroy()
        self.assertIsNone(app._mobile_preview_dialog)
        self.assertTrue(app.mobile_preview_server.running)
        app.show_mobile_preview()
        new_owner = app._mobile_preview_dialog
        late_destroy(SimpleNamespace(widget=old_window))
        for callback in old_callbacks:
            self.assertFalse(callback())
        self.assertIs(app._mobile_preview_dialog, new_owner)
        self.assert_current_panel(app, new_owner.window)
        self.assertFalse(new_owner.window.jobs)


@unittest.skipUnless(sys.platform == 'win32', 'Native Tk lifecycle is exercised on Windows CI')
class NativeMobileDialogLifecycleTests(unittest.TestCase):
    def test_first_scaling_poll_survives_when_mobile_is_the_first_widget_window(self):
        child_flag = 'IMAGEDRAWBOT_MOBILE_SCALING_TEST_CHILD'
        if os.environ.get(child_flag) != '1':
            # A fresh process gives CTk its genuine startup state. Do not clear
            # process-wide tracker registries or modify its loop-running flag.
            code = '''import unittest
from test_v148_ui_batch18_mobile_dialog import NativeMobileDialogLifecycleTests
NativeMobileDialogLifecycleTests.__unittest_skip__ = False
case = NativeMobileDialogLifecycleTests('test_first_scaling_poll_survives_when_mobile_is_the_first_widget_window')
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([case]))
raise SystemExit(not result.wasSuccessful())
'''
            result = subprocess.run([sys.executable, '-c', code],
                cwd=Path(__file__).resolve().parent,
                env={**os.environ, child_flag: '1'}, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return

        import customtkinter as ctk
        from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker

        root = ctk.CTk()
        self.addCleanup(root.destroy)
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        root.tk.createcommand('bgerror', lambda message: errors.append(('Tcl bgerror', message)))
        app = DrawBotApp.__new__(DrawBotApp)
        app.root, app.closing, app.activity = root, False, None
        app.mobile_preview_server = app.mobile_preview_after = app.mobile_preview_ticket = None
        app.original = app.plan = None
        for name in ('mobile_preview_url', 'mobile_preview_status', 'status'):
            setattr(app, name, tk.StringVar(root, value=''))
        self.addCleanup(app.stop_mobile_preview, quiet=True)
        self.assertFalse(root.winfo_children())
        self.assertFalse(ScalingTracker.update_loop_running)
        original_binding = root.bind_all('<Button-1>')
        with patch('MobilePreview.local_ipv4_addresses', return_value=['127.0.0.1']), \
                patch('DrawBot.log_event'):
            panel = app.show_mobile_preview()
            self.assertIsNotNone(panel)
            self.assertTrue(ScalingTracker.update_loop_running)
            survivors = []
            other_window = tk.Toplevel(root)
            other_window.withdraw()
            other_window.after(30, lambda: survivors.append('other window'))
            root.after(30, lambda: survivors.append('root'))
            # Close before allowing the first timer tick to run. The real
            # controller still leaves the sharing server and app root alive.
            panel.destroy()
            self.assertIsNone(app._mobile_preview_dialog)
            self.assertTrue(app.mobile_preview_server.running)
            self.assertEqual(root.bind_all('<Button-1>').strip(), original_binding.strip())
            remaining = ctk.CTkLabel(root, text='The app still needs DPI polling')
            remaining.pack()
            with patch.object(ScalingTracker, 'get_window_dpi_scaling',
                              wraps=ScalingTracker.get_window_dpi_scaling) as observed_dpi:
                root.after(250, root.quit)
                root.mainloop()
            self.assertGreaterEqual(sum(call.args == (root,) for call in observed_dpi.call_args_list), 1,
                'Closing the first widget window must not stop the remaining app DPI poll')
            self.assertTrue(remaining.winfo_exists())
            self.assertTrue(other_window.winfo_exists())
            self.assertCountEqual(survivors, ['root', 'other window'])
            self.assertTrue(ScalingTracker.update_loop_running)
            self.assertEqual(errors, [])

    def test_real_panel_refresh_close_restart_has_one_owner_and_releases_tcl_resources(self):
        import customtkinter as ctk
        from PIL import ImageTk

        root = ctk.CTk()
        self.addCleanup(root.destroy)
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        root.tk.createcommand('bgerror', lambda message: errors.append(('Tcl bgerror', message)))
        app = DrawBotApp.__new__(DrawBotApp)
        app.root, app.closing, app.activity = root, False, None
        app.mobile_preview_server = app.mobile_preview_after = app.mobile_preview_ticket = None
        app.original = app.plan = None
        for name in ('mobile_preview_url', 'mobile_preview_status', 'status'):
            setattr(app, name, tk.StringVar(root, value=''))
        self.addCleanup(app.stop_mobile_preview, quiet=True)
        with patch('MobilePreview.local_ipv4_addresses', return_value=['127.0.0.1']) as addresses, \
                patch('DrawBot.log_event'), patch('webbrowser.open', return_value=True) as browser:
            original_click_binding = root.bind_all('<Button-1>')
            first = app.show_mobile_preview()
            root.update()
            owner = app._mobile_preview_dialog
            old_photo = str(owner.photo)
            with ImageTk.getimage(owner.photo) as old_pixels:
                old_bytes = old_pixels.tobytes()
            old_commands = set()

            def record_commands(widget):
                old_commands.update(widget._tclCommands or ())
                for child in widget.winfo_children():
                    record_commands(child)

            addresses.return_value = ['127.0.0.2']
            self.assertIs(app.show_mobile_preview(), first)
            root.update()
            self.assertIs(app._mobile_preview_dialog, owner)
            url = app.mobile_preview_url.get()
            self.assertEqual(owner.address.get('1.0', 'end').strip(), url)
            self.assertNotIn(old_photo, root.tk.call('image', 'names'))
            with ImageTk.getimage(owner.photo) as new_pixels:
                self.assertNotEqual(new_pixels.tobytes(), old_bytes)
            owner.copy_address()
            self.assertEqual(root.clipboard_get(), url)
            owner.open_local()
            browser.assert_called_once_with(url)
            record_commands(first)
            old_commands.update(token for _root, _sequence, token in first._panel_bindings)
            future_job = first.after(60_000, lambda: errors.append('Closed panel callback ran'))
            current_photo = str(owner.photo)
            first.destroy()
            root.update()
            self.assertIsNone(app._mobile_preview_dialog)
            self.assertIsNone(owner.photo)
            self.assertTrue(app.mobile_preview_server.running)
            self.assertFalse(old_commands.intersection(root.tk.call('info', 'commands')))
            self.assertNotIn(current_photo, root.tk.call('image', 'names'))
            self.assertEqual(root.bind_all('<Button-1>').strip(), original_click_binding.strip())
            self.assertNotIn(future_job, root.tk.call('after', 'info'))
            second = app.show_mobile_preview()
            root.update()
            self.assertIsNot(second, first)
            current_owner = app._mobile_preview_dialog
            owner.stop()
            self.assertIs(app._mobile_preview_dialog, current_owner)
            self.assertTrue(app.mobile_preview_server.running)
            with patch.object(current_owner.address, 'insert',
                              side_effect=tk.TclError('native refresh failure')):
                self.assertIsNone(app.show_mobile_preview())
            self.assertFalse(second.winfo_exists())
            self.assertFalse(app.mobile_preview_server.running)
            self.assertIsNone(app._mobile_preview_dialog)
            self.assertIn('Could not start Mobile Preview', app.status.get())
            third = app.show_mobile_preview()
            root.update()
            stop_button = next(widget for widget in self._widgets(third)
                if isinstance(widget, ctk.CTkButton) and widget.cget('text') == 'Stop Mobile Preview')
            # The real CTk click handler queues its animation before invoking
            # Stop. Destruction must cancel that child's timer as well.
            stop_button._on_enter()
            stop_button._on_release()
            self.assertFalse(third.winfo_exists())
            self.assertFalse(app.mobile_preview_server.running)
            self.assertIsNone(app._mobile_preview_dialog)
            root.after(250, root.quit)
            root.mainloop()
            self.assertEqual(root.bind_all('<Button-1>').strip(), original_click_binding.strip())
        self.assertEqual(errors, [])

    @staticmethod
    def _widgets(widget):
        for child in widget.winfo_children():
            yield child
            yield from NativeMobileDialogLifecycleTests._widgets(child)


if __name__ == '__main__':
    unittest.main()
