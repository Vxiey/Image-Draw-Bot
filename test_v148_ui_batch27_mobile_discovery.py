"""Actual Mobile Preview lookup, session adoption and native Tk responsiveness."""
from contextlib import ExitStack
import gc
import os
from pathlib import Path
import queue
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import weakref

from DrawBot import DrawBotApp
from MobilePreview import MobilePreviewServer
from MobilePreviewDiscovery import MobilePreviewDiscovery
import test_v148_ui_batch18_mobile_dialog as mobile_fixtures

show_mobile_preview_ready = mobile_fixtures.show_mobile_preview_ready


class ControlledResolver:
    """Replace only the OS discovery outcome; its worker and controller are real."""
    def __init__(self, *results):
        self.results = results
        self.entered = [threading.Event() for _ in results]
        self.release = [threading.Event() for _ in results]
        self.lock = threading.Lock()
        self.calls = self.active = self.maximum_active = 0
        self.threads = []

    def __call__(self):
        with self.lock:
            index = self.calls
            self.calls += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.threads.append(threading.get_ident())
        try:
            self.entered[index].set()
            if not self.release[index].wait(5):
                raise TimeoutError('The test did not release its resolver boundary')
            result = self.results[index]
            if isinstance(result, BaseException):
                raise result
            return result
        finally:
            with self.lock:
                self.active -= 1

    def close(self):
        for event in self.release:
            event.set()


class MobileDiscoveryControllerTests(unittest.TestCase):
    # Reuse the existing actual Tcl/controller/native-allocation boundary, not
    # its test methods. Its creator-thread cleanup remains the sole Tcl owner.
    photo = mobile_fixtures.MobileDialogWorkflowTests.photo
    app = mobile_fixtures.MobileDialogWorkflowTests.app
    release_apps = mobile_fixtures.MobileDialogWorkflowTests.release_apps
    windows = staticmethod(mobile_fixtures.MobileDialogWorkflowTests.windows)
    controls = staticmethod(mobile_fixtures.MobileDialogWorkflowTests.controls)
    assert_current_panel = mobile_fixtures.MobileDialogWorkflowTests.assert_current_panel

    def setUp(self):
        mobile_fixtures.MobileDialogWorkflowTests.setUp(self)
        self.resolvers = []
        self.addCleanup(self.close_resolvers)
        self.stack.enter_context(patch.object(socket, 'getfqdn',
            side_effect=AssertionError('The numeric HTTP listener must not perform reverse DNS')))

    def close_resolvers(self):
        for resolver in self.resolvers:
            resolver.close()
        for app in self.apps:
            discovery = getattr(app, 'mobile_preview_discovery', None)
            if discovery is not None:
                discovery.retire()
                if discovery.thread is not None:
                    discovery.thread.join(2)
                    self.assertFalse(discovery.thread.is_alive())

    def configured_app(self):
        app = self.app()
        app.stop, app.paused = threading.Event(), threading.Event()
        app.worker = None
        app.events = queue.Queue()
        app.needs_plan = False
        app.set_busy = lambda value: setattr(app, 'activity', value)
        return app

    def controlled(self, app, *results):
        resolver = ControlledResolver(*results)
        self.resolvers.append(resolver)
        self.addresses.side_effect = resolver
        return resolver

    def until(self, predicate, app=None):
        deadline = time.monotonic() + 3
        while not predicate():
            if app is not None:
                DrawBotApp._poll_mobile_preview_discovery(app)
            if time.monotonic() >= deadline:
                self.fail('Actual lookup/controller did not reach the expected boundary')
            time.sleep(.001)

    def ready(self, app):
        self.until(lambda: getattr(app, 'mobile_preview_request', None) is None, app)
        return getattr(app, '_mobile_preview_dialog', None)

    def test_stop_between_request_publication_and_submit_prevents_even_thread_start(self):
        app = self.configured_app()
        real_submit = MobilePreviewDiscovery.submit
        def stop_before_submit(owner, ticket):
            self.assertIs(app.mobile_preview_request['cancel'], ticket)
            app._request_stop()
            return real_submit(owner, ticket)
        with patch.object(MobilePreviewDiscovery, 'submit', stop_before_submit):
            app.show_mobile_preview()
        self.assertTrue(app.stop.is_set())
        self.assertIsNone(app.mobile_preview_discovery.thread)
        self.assertFalse(app.mobile_preview_server.running)
        self.ready(app)
        self.addresses.assert_not_called()
        # A new explicit Show has its own permission. It neither reuses the
        # cancelled intent nor clears an unrelated, latched drawing Stop.
        window = show_mobile_preview_ready(app)
        self.assertIsNotNone(window)
        self.assertTrue(app.stop.is_set())
        self.assertIsNone(app.activity)
        self.assertIsNone(app.worker)
        self.assert_current_panel(app, window)

    def test_repeated_show_stop_real_worker_clear_and_restart_keep_one_resolver(self):
        app = self.configured_app()
        resolver = self.controlled(app, ['127.0.0.1'], ['127.0.0.2'])
        app.show_mobile_preview()
        self.assertTrue(resolver.entered[0].wait(1))
        original_thread = app.mobile_preview_discovery.thread
        tickets = [app.mobile_preview_request['cancel']]
        for _ in range(8):
            app.show_mobile_preview()
            tickets.append(app.mobile_preview_request['cancel'])
            self.assertIs(app.mobile_preview_discovery.thread, original_thread)
        self.assertTrue(all(ticket.is_set() for ticket in tickets[:-1]))
        self.assertEqual(resolver.calls, 1)
        app._request_stop()
        self.assertTrue(tickets[-1].is_set())
        ran = threading.Event()
        self.assertTrue(app.begin_worker('copy', ran.set))
        app.worker.join(2)
        self.assertFalse(app.worker.is_alive())
        self.assertTrue(ran.is_set())
        self.assertFalse(app.stop.is_set())
        app.activity = None
        app.show_mobile_preview()
        newest = app.mobile_preview_request['cancel']
        self.assertIs(app.mobile_preview_discovery.thread, original_thread)
        self.assertFalse(newest.is_set())
        self.assertFalse(app.mobile_preview_server.running)
        resolver.release[0].set()
        self.until(resolver.entered[1].is_set, app)
        self.assertFalse(app.mobile_preview_server.running)
        self.assertEqual(resolver.calls, 2)
        self.assertEqual(resolver.maximum_active, 1)
        resolver.release[1].set()
        owner = self.ready(app)
        self.assertIsNotNone(owner)
        self.assertIn('127.0.0.2', self.assert_current_panel(app, owner.window))
        self.assertTrue(all(ticket.is_set() for ticket in tickets))

    def test_discovery_keeps_busy_worker_browser_intent_and_global_stop_untouched(self):
        app = self.configured_app()
        app.activity = 'draw'
        app.worker = worker = object()
        app.stop.set(); app.paused.set()
        app.browser_one_click_request = browser = dict(cancelled=threading.Event())
        app.status.set('Drawing the current plan')
        with patch.object(DrawBotApp, 'begin_worker', side_effect=AssertionError('No borrowed worker')):
            app.show_mobile_preview()
            owner = self.ready(app)
        self.assertIsNotNone(owner)
        self.assertEqual(app.activity, 'draw')
        self.assertIs(app.worker, worker)
        self.assertTrue(app.stop.is_set())
        self.assertTrue(app.paused.is_set())
        self.assertIs(app.browser_one_click_request, browser)
        self.assertFalse(browser['cancelled'].is_set())
        self.assertEqual(app.status.get(), 'Drawing the current plan')
        self.assertTrue(app.events.empty())

    def test_changed_server_generation_rejects_a_late_lookup_without_creating_a_session(self):
        app = self.configured_app()
        resolver = self.controlled(app, ['127.0.0.1'], ['127.0.0.2'])
        app.show_mobile_preview()
        self.assertTrue(resolver.entered[0].wait(1))
        server = app.mobile_preview_server
        old_identity = server.session_identity()
        server.stop()
        self.assertNotEqual(server.session_identity(), old_identity)
        resolver.release[0].set()
        self.ready(app)
        self.assertFalse(server.running)
        self.assertEqual(app.mobile_preview_url.get(), '')
        self.assertEqual(self.windows(app), [])
        resolver.release[1].set()
        self.assertIsNotNone(show_mobile_preview_ready(app))
        self.assertIs(app.mobile_preview_server, server)

    def test_closed_panel_stays_closed_until_explicit_reopen_queued_behind_old_lookup(self):
        app = self.configured_app()
        show_mobile_preview_ready(app)
        old = app._mobile_preview_dialog
        session = app.mobile_preview_server.session_identity()
        resolver = self.controlled(app, ['127.0.0.2'], ['127.0.0.3'])
        app.show_mobile_preview()
        self.assertTrue(resolver.entered[0].wait(1))
        old.close()
        DrawBotApp._poll_mobile_preview_discovery(app)
        self.assertIsNone(app.mobile_preview_request)
        self.assertIsNone(app._mobile_preview_dialog)
        self.assertTrue(app.mobile_preview_server.running)
        self.assertFalse(old.stop())
        self.assertFalse(old.open_local())
        self.assertFalse(old.copy_address())
        app.show_mobile_preview()
        self.assertIsNone(app._mobile_preview_dialog)
        self.assertEqual(resolver.calls, 1)
        resolver.release[0].set()
        self.until(resolver.entered[1].is_set, app)
        self.assertIsNone(app._mobile_preview_dialog)
        resolver.release[1].set()
        owner = self.ready(app)
        self.assertIsNot(owner, old)
        self.assertEqual(app.mobile_preview_server.session_identity(), session)
        self.assertIn('127.0.0.3', self.assert_current_panel(app, owner.window))
        self.assertFalse(old.stop())
        self.assertTrue(app.mobile_preview_server.running)

    def test_current_resolver_error_preserves_sharing_and_late_error_cannot_stop_restart(self):
        app = self.configured_app()
        show_mobile_preview_ready(app)
        first = app._mobile_preview_dialog
        original_url = app.mobile_preview_url.get()
        old_session = app.mobile_preview_server.session_identity()
        self.addresses.side_effect = RuntimeError('current discovery failure')
        app.show_mobile_preview(); self.ready(app)
        self.assertIs(app._mobile_preview_dialog, first)
        self.assertEqual(app.mobile_preview_server.session_identity(), old_session)
        self.assertEqual(app.mobile_preview_url.get(), original_url)
        self.assertIn('current discovery failure', app.mobile_preview_status.get())
        resolver = self.controlled(app, RuntimeError('obsolete failure'), ['127.0.0.2'])
        app.show_mobile_preview()
        self.assertTrue(resolver.entered[0].wait(1))
        app.stop_mobile_preview()
        app.show_mobile_preview()
        resolver.release[0].set()
        self.until(resolver.entered[1].is_set, app)
        self.assertFalse(app.mobile_preview_server.running)
        resolver.release[1].set()
        owner = self.ready(app)
        self.assertIsNotNone(owner)
        self.assertNotEqual(app.mobile_preview_server.session_identity(), old_session)
        self.assertNotIn('obsolete failure', app.status.get())
        self.assertIn('127.0.0.2', self.assert_current_panel(app, owner.window))

    def test_thread_start_failures_are_visible_and_retryable_at_both_queue_boundaries(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                app = self.configured_app()
                self.addresses.side_effect = None
                resolver = None
                if pending:
                    resolver = self.controlled(app, ['127.0.0.1'], ['127.0.0.2'])
                    app.show_mobile_preview()
                    self.assertTrue(resolver.entered[0].wait(1))
                    app.show_mobile_preview()
                    resolver.release[0].set()
                    self.until(lambda: not app.mobile_preview_discovery.thread.is_alive())
                with patch('MobilePreviewDiscovery.threading.Thread', side_effect=RuntimeError('thread start failure')):
                    if not pending:
                        app.show_mobile_preview()
                    DrawBotApp._poll_mobile_preview_discovery(app)
                self.assertIsNone(app.mobile_preview_request)
                self.assertFalse(app.mobile_preview_server.running)
                self.assertEqual(self.windows(app), [])
                self.assertIn('thread start failure', app.mobile_preview_status.get())
                if resolver is not None:
                    resolver.release[1].set()
                self.assertIsNotNone(show_mobile_preview_ready(app))
                app.stop_mobile_preview()

    def test_sync_api_and_prepared_adoption_keep_real_tcp_security_without_reverse_dns(self):
        server = MobilePreviewServer()
        self.addCleanup(server.stop)
        first = server.start()
        self.assertTrue(first.running)
        self.assertEqual(server._server.server_name, '0.0.0.0')
        self.assertEqual(server._server.server_port, server.port)
        self.assertEqual(self.addresses.call_count, 1)
        session = server.session_identity()
        self.addresses.return_value = ['127.0.0.2']
        second = server.refresh_addresses()
        self.assertEqual(self.addresses.call_count, 2)
        self.assertEqual(server.session_identity(), session)
        self.assertIn('127.0.0.2', second.urls[0])
        for invalid in (['8.8.8.8'], ['https://127.0.0.1'], ['::1'], '127.0.0.1', [object()]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    server.refresh_addresses(addresses=invalid)
                self.assertEqual(server.state(), second)
        third = server.refresh_addresses(addresses=('127.0.0.3', '127.0.0.3'))
        self.assertEqual(self.addresses.call_count, 2)
        self.assertEqual(len(third.urls), 1)
        self.assertIn('127.0.0.3', third.urls[0])
        server.stop()
        fourth = server.start(addresses=())
        self.assertEqual(self.addresses.call_count, 2)
        self.assertIn('127.0.0.1', fourth.urls[0])
        self.assertNotEqual(fourth.token, first.token)


class MobileDiscoveryOwnershipTests(unittest.TestCase):
    def test_retirement_keeps_the_blocked_slot_but_no_late_outcome_or_resolver_owner(self):
        class Resolver:
            def __call__(self):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError('test release missing')
                raise RuntimeError('late resolver failure')
        entered, release = threading.Event(), threading.Event()
        resolver = Resolver()
        reference = weakref.ref(resolver)
        owner = MobilePreviewDiscovery(resolver)
        token = threading.Event()
        try:
            owner.submit(token)
            self.assertTrue(entered.wait(1))
            thread = owner.thread
            owner.retire()
            self.assertTrue(token.is_set())
            self.assertTrue(thread.is_alive())
            self.assertIsNone(owner._resolve)
            self.assertIsNone(owner.take())
            with self.assertRaises(RuntimeError):
                owner.submit(threading.Event())
            del resolver
            release.set(); thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertIsNone(owner.take())
            self.assertIsNone(owner._outcome)
            self.assertIsNone(reference())
        finally:
            release.set()
            if owner.thread is not None:owner.thread.join(2)


@unittest.skipUnless(sys.platform == 'win32' or bool(os.environ.get('DISPLAY')),
                     'Native Mobile discovery requires a Tk display')
class NativeMobileDiscoveryTests(unittest.TestCase):
    def setUp(self):
        import CrashDiagnostics
        import DrawBot
        import RuntimePaths
        import SessionRecovery
        self.stack = self.enterContext(ExitStack())
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name, path in (('RECOVERY_DIR', self.directory),
                ('STATE_FILE', self.directory / 'recovery.json'),
                ('IMAGE_FILE', self.directory / 'last.png'),
                ('RENDER_FILE', self.directory / 'render.json')):
            self.stack.enter_context(patch.object(SessionRecovery, name, path))
        self.stack.enter_context(patch.object(RuntimePaths, 'data_dir', return_value=self.directory))
        self.stack.enter_context(patch.object(CrashDiagnostics, 'RUN_MARKER', self.directory / 'running.marker'))
        self.stack.enter_context(patch.object(CrashDiagnostics, 'RUN_MARKER_OWNED', False))
        self.stack.enter_context(patch.object(DrawBot, 'log_event'))
        self.errors = []
        self.stack.enter_context(patch.object(DrawBot, 'log_error',
            side_effect=lambda message, **_kwargs: self.errors.append(str(message))))
        self.browser = self.stack.enter_context(patch('webbrowser.open', return_value=True))
        self.root = DrawBot.create_root()
        self.root.geometry('400x220')
        self.root.report_callback_exception = lambda typ, error, _trace: self.errors.append(
            typ.__name__ + ': ' + str(error))
        self.root.tk.createcommand('bgerror', lambda error: self.errors.append('Tcl bgerror: ' + str(error)))
        self.app = app = DrawBotApp.__new__(DrawBotApp)
        app.root, app.closing, app.shutdown_complete, app.activity = self.root, False, False, None
        app.worker = None
        app.stop, app.paused = threading.Event(), threading.Event()
        app.events = queue.Queue()
        app.mobile_preview_server = app.mobile_preview_after = app.mobile_preview_ticket = None
        app.original = app.plan = None
        app.needs_plan = False
        app.pending_clear_drawing = None
        app.smart_drop_generation = app.preview_generation = 0
        app._recovery_image_job = None
        app._recovery_save_pending = False
        app.recovery_checkpoint_after = app.recovery_shutdown_after = app.poll_after = None
        app.hotkeys_removed, app.hotkeys, app.keyboard = False, [], None
        app.set_busy = lambda value: setattr(app, 'activity', value)
        app.save_settings = lambda: RuntimePaths.atomic_write_text(self.directory / 'settings.json', '{}\n')
        for name in ('mobile_preview_url', 'mobile_preview_status', 'status'):
            setattr(app, name, tk.StringVar(self.root, value=''))
        app.game = tk.StringVar(self.root, value='Other drawing app')
        self.root.protocol('WM_DELETE_WINDOW', app.close)
        SessionRecovery.save_snapshot(profile='Other drawing app', options={})
        self.resolver = None
        self.addCleanup(self.close_native)
        self.root.update()
        app.poll()
        self.creator = threading.get_ident()
        self.photo_threads, self.qr_urls = [], []
        import qrcode
        from PIL import ImageTk
        real_photo, real_add = ImageTk.PhotoImage, qrcode.QRCode.add_data
        def photo(*args, **kwargs):
            self.photo_threads.append(threading.get_ident())
            return real_photo(*args, **kwargs)
        def qr_data(qr, value, *args, **kwargs):
            self.qr_urls.append(value)
            return real_add(qr, value, *args, **kwargs)
        self.stack.enter_context(patch.object(ImageTk, 'PhotoImage', photo))
        self.stack.enter_context(patch.object(qrcode.QRCode, 'add_data', qr_data))

    def close_native(self):
        if self.resolver is not None:self.resolver.close()
        app, root = self.app, self.root
        discovery = getattr(app, 'mobile_preview_discovery', None)
        if discovery is not None:discovery.retire()
        try:
            if not app.shutdown_complete:app.close()
            if discovery is not None and discovery.thread is not None:
                discovery.thread.join(2)
                self.assertFalse(discovery.thread.is_alive())
            self.assertEqual(self.errors, [])
        finally:
            try:root.destroy()
            except tk.TclError:pass
            try:root.tk.deletecommand('bgerror')
            except tk.TclError:pass
            vars(app).clear()
            self.app = self.root = None

    def network_boundary(self, *outcomes):
        self.resolver = resolver = ControlledResolver(*outcomes)
        original_socket = socket.socket
        class LocalSocket(original_socket):
            def bind(self, address):
                if self.family == socket.AF_INET and address[0] == '0.0.0.0':
                    address = ('127.0.0.1', address[1])
                return super().bind(address)
        def socket_boundary(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0, fileno=None):
            if family == socket.AF_INET and type == socket.SOCK_DGRAM:
                raise OSError('The isolated fixture has no routed UDP interface')
            return LocalSocket(family, type, proto, fileno=fileno)
        self.stack.enter_context(patch.object(socket, 'socket', socket_boundary))
        self.stack.enter_context(patch.object(socket, 'gethostbyname_ex',
            side_effect=lambda _host: ('fixture.invalid', [], resolver())))
        self.reverse = self.stack.enter_context(patch.object(socket, 'getfqdn',
            side_effect=AssertionError('The actual HTTP listener must not enter reverse DNS')))
        self.stack.enter_context(patch.object(socket, 'gethostbyaddr',
            side_effect=AssertionError('No reverse DNS is allowed at the OS boundary')))
        return resolver

    def until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate():
            self.root.update()
            if time.monotonic() >= deadline:
                self.fail('The real Tk event loop did not reach the expected state')
            time.sleep(.002)
        self.assertEqual(self.errors, [])

    def assert_panel(self):
        app = self.app
        owner = app._mobile_preview_dialog
        url = app.mobile_preview_url.get()
        self.assertTrue(owner.current())
        self.assertEqual(owner.url, url)
        self.assertEqual(owner.address.get('1.0', 'end').strip(), url)
        self.assertEqual(self.qr_urls[-1], url)
        self.assertIsNotNone(owner.photo)
        self.assertTrue(all(thread == self.creator for thread in self.photo_threads))
        owner.copy_address()
        self.assertEqual(self.root.clipboard_get(), url)
        self.browser.reset_mock(); owner.open_local()
        self.browser.assert_called_once_with(url)
        self.reverse.assert_not_called()
        return owner

    def test_actual_buttons_heartbeat_stop_reopen_and_app_close_while_dns_stays_blocked(self):
        from UiKeyboardNavigation import KeyboardButton
        app = self.app
        resolver = self.network_boundary(['192.168.50.8'], ['192.168.50.9'], ['192.168.50.10'])
        show = KeyboardButton(self.root, text='Mobile Preview', command=app.show_mobile_preview)
        stop = KeyboardButton(self.root, text='Stop', command=app.cancel)
        show.pack(); stop.pack(); self.root.update()
        show.invoke()
        self.assertTrue(resolver.entered[0].wait(1))
        first_request = app.mobile_preview_request
        first_thread = app.mobile_preview_discovery.thread
        heartbeat = []
        self.root.after(5, stop.invoke)
        self.root.after(10, lambda: heartbeat.append(threading.get_ident()))
        self.until(lambda: bool(heartbeat))
        self.assertEqual(heartbeat, [self.creator])
        self.assertTrue(first_request['cancel'].is_set())
        self.assertTrue(first_thread.is_alive())
        self.assertFalse(app.mobile_preview_server.running)
        self.assertTrue(app.stop.is_set())
        self.assertEqual(show.cget('state'), 'normal')
        self.assertEqual(stop.cget('state'), 'normal')
        self.assertIsNone(app.activity)
        self.assertIsNone(app.worker)
        app.browser_one_click_request = browser = dict(cancelled=threading.Event())
        for _ in range(6):show.invoke()
        self.assertIs(app.mobile_preview_discovery.thread, first_thread)
        self.assertEqual(resolver.calls, 1)
        self.assertIs(app.browser_one_click_request, browser)
        self.assertFalse(browser['cancelled'].is_set())
        resolver.release[0].set()
        self.until(resolver.entered[1].is_set)
        self.assertFalse(app.mobile_preview_server.running)
        resolver.release[1].set()
        self.until(lambda: getattr(app, '_mobile_preview_dialog', None) is not None)
        owner = self.assert_panel()
        self.assertIn('192.168.50.9', owner.url)
        self.assertTrue(app.stop.is_set())
        self.assertEqual(resolver.maximum_active, 1)
        self.assertTrue(all(thread != self.creator for thread in resolver.threads))
        show.invoke()
        self.until(resolver.entered[2].is_set)
        pending_thread = app.mobile_preview_discovery.thread
        close_heartbeat = []
        self.root.after(5, lambda: close_heartbeat.append(True))
        self.until(lambda: bool(close_heartbeat))
        self.root.tk.call(self.root.protocol('WM_DELETE_WINDOW'))
        self.assertTrue(app.shutdown_complete)
        self.assertTrue(pending_thread.is_alive())
        self.assertFalse(app.mobile_preview_server.running)
        self.assertIsNone(app.mobile_preview_request)
        self.assertIsNone(app._mobile_preview_dialog)
        self.assertFalse((self.directory / 'recovery.json').exists())
        photos = len(self.photo_threads)
        resolver.release[2].set(); pending_thread.join(2)
        self.assertFalse(pending_thread.is_alive())
        self.assertEqual(len(self.photo_threads), photos)
        self.assertIsNone(app.mobile_preview_discovery.take())
        self.assertFalse(owner.stop())
        self.assertIsNone(app.show_mobile_preview())
        self.assertEqual(resolver.calls, 3)
        self.assertEqual(self.errors, [])

    def test_actual_panel_close_late_refresh_stop_and_new_session_keep_displayed_identity(self):
        app = self.app
        resolver = self.network_boundary(['192.168.50.8'], ['192.168.50.9'],
                                         ['192.168.50.10'], ['192.168.50.11'])
        resolver.release[0].set()
        app.show_mobile_preview()
        self.until(lambda: getattr(app, '_mobile_preview_dialog', None) is not None)
        old = self.assert_panel()
        server = app.mobile_preview_server
        first_session = server.session_identity()
        first_url = app.mobile_preview_url.get()
        app.show_mobile_preview()
        self.until(resolver.entered[1].is_set)
        self.assertEqual(app.mobile_preview_url.get(), first_url)
        self.root.tk.call(old.window.protocol('WM_DELETE_WINDOW'))
        self.until(lambda: app.mobile_preview_request is None)
        self.assertIsNone(app._mobile_preview_dialog)
        self.assertTrue(server.running)
        resolver.release[1].set()
        self.until(lambda: app.mobile_preview_discovery.thread is None
                   or not app.mobile_preview_discovery.thread.is_alive())
        done = []
        self.root.after(80, lambda: done.append(True))
        self.until(lambda: bool(done))
        self.assertIsNone(app._mobile_preview_dialog)
        self.assertEqual(server.session_identity(), first_session)
        self.assertEqual(app.mobile_preview_url.get(), first_url)
        app.show_mobile_preview()
        self.until(resolver.entered[2].is_set)
        previous_thread = app.mobile_preview_discovery.thread
        app.stop_mobile_preview()
        self.assertTrue(previous_thread.is_alive())
        self.assertFalse(server.running)
        self.assertEqual(app.mobile_preview_url.get(), '')
        app.show_mobile_preview()
        self.assertIs(app.mobile_preview_discovery.thread, previous_thread)
        self.assertFalse(old.stop())
        self.assertFalse(old.copy_address())
        self.assertFalse(old.open_local())
        resolver.release[2].set()
        self.until(resolver.entered[3].is_set)
        self.assertFalse(server.running)
        resolver.release[3].set()
        self.until(lambda: getattr(app, '_mobile_preview_dialog', None) is not None)
        current = self.assert_panel()
        self.assertIs(app.mobile_preview_server, server)
        self.assertIsNot(current, old)
        self.assertIn('192.168.50.11', current.url)
        self.assertNotEqual(server.token, first_session[2])
        self.assertFalse(old.stop())
        self.assertTrue(server.running)
        self.assertEqual(resolver.maximum_active, 1)


if __name__ == '__main__':
    unittest.main()
