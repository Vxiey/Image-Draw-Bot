"""Supported clipboard text follows the actual bounded asynchronous importer."""
import base64
from contextlib import ExitStack, closing
from io import BytesIO
from pathlib import Path
import queue
import tempfile
import threading
from types import MethodType
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from ClipboardImport import parse_text_source
from DrawBot import DrawBotApp
from DropInStart import DROP_IN_ACTION
from test_v148_application_batch04_settings import Value
from test_v148_application_batch14_browser_start import ScheduledRoot
from test_v148_ui_lifecycle_batch02 import ui_app
import test_v148_platform_batch07_import_redirects as http_fixtures


PIXELS = [(12, 34, 56, 78), (210, 45, 7, 255), (0, 250, 100, 0),
          (6, 9, 12, 255), (40, 80, 120, 160), (1, 2, 3, 4)]


def pixels(image):
    return [image.getpixel((x, y)) for y in range(image.height) for x in range(image.width)]


class ClipboardTextImportTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.path = self.directory / 'Copy as path å # 50% image.png'
        with closing(Image.new('RGBA', (3, 2))) as source:
            source.putdata(PIXELS)
            source.save(self.path)
        self.png = self.path.read_bytes()
        self.uri = 'data:image/png;base64,' + base64.b64encode(self.png).decode('ascii')
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawBot.log_error'))
        self.stack.enter_context(patch('SessionRecovery.clear_render_progress'))

    def app(self, text='', *, armed=False, automatic=False):
        app = ui_app()
        self.addCleanup(app.original.close)
        app.events = queue.Queue()
        app.root = ScheduledRoot()
        app.root.clipboard_get = Mock(return_value=text)
        app.set_busy = lambda activity: setattr(app, 'activity', activity)
        app.game = Value('Gartic Phone')
        app.browser_one_click_enabled = Value(automatic)
        app.browser_one_click_request = None
        app.manual_drop_in_start = Value(armed)
        app.manual_drop_in_armed_until = 10**12 if armed else 0
        app.drop_action_pending = None
        app.drop_in_start_context = None
        app.preview_mode = Value('Manual')
        app.needs_plan = False
        app.paused = threading.Event()
        app.mouse = Mock()
        app.plan = {'old': 'plan'}
        app.subject_region = (0, 0, 1, 1)
        app.pending_render_resume = {'old': 'resume'}
        app.background_removal_original = object()
        app.upscale_original = object()
        app.update_plan = Mock()
        for name in ('status', 'summary', 'url', 'file_label', 'browser_one_click_text'):
            setattr(app, name, Value(''))
        for name in ('begin_worker', 'load_source', 'fetch_url', '_mark_plan_stale',
                     '_maybe_auto_preview', '_auto_preview_enabled', '_sync_mobile_preview',
                     '_run_pending_drop_in_start'):
            setattr(app, name, MethodType(getattr(DrawBotApp, name), app))
        return app

    def paste(self, app, *, native=None):
        old = app.original
        with patch('PIL.ImageGrab.grabclipboard', return_value=native):
            result = DrawBotApp.paste_image(app)
        self.assertIsNotNone(getattr(app, 'worker', None), app.status.get())
        worker = app.worker
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertIs(app.original, old, 'Only the UI result consumer may adopt the image')
        self.assertEqual(app.activity, 'load')
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait())
        return result, events

    def adopt(self, app, events):
        for kind, payload in events:
            if kind in ('loaded', 'pasted'):
                self.addCleanup(payload[0].close)
            DrawBotApp._handle_event(app, kind, payload)

    def test_direct_text_sources_use_real_loader_and_preserve_exact_alpha_pixels(self):
        for text in ('  "' + str(self.path) + '"\r\n', str(self.path),
                     self.path.as_uri(), self.uri):
            with self.subTest(kind=text[:35]):
                app = self.app(text)
                _, events = self.paste(app)
                self.assertEqual([kind for kind, payload in events], ['loaded', 'done'])
                self.assertEqual(events[0][1][2:], (None, False))
                self.adopt(app, events)
                self.assertEqual(app.original.size, (3, 2))
                self.assertEqual(pixels(app.original), PIXELS)
                self.assertIsNone(app.activity)
                self.assertIsNone(app.plan)
                self.assertIsNone(app.subject_region)
                self.assertIsNone(app.pending_render_resume)
                self.assertIsNone(app.background_removal_original)
                self.assertIsNone(app.upscale_original)
                self.assertEqual(app.root.jobs, {})
                self.assertIsNone(app.browser_one_click_request)
                app.update_plan.assert_not_called()

    def test_bitmap_and_file_list_have_priority_over_clipboard_text(self):
        unsupported = self.directory / 'notes.txt'
        unsupported.write_text('not an image', encoding='utf-8')
        with closing(Image.new('RGBA', (2, 1), (3, 4, 5, 6))) as bitmap:
            for native, expected in ((bitmap, [(3, 4, 5, 6)] * 2),
                                     ([str(unsupported), str(self.path)], PIXELS)):
                with self.subTest(kind=type(native).__name__):
                    app = self.app(self.uri)
                    app.root.clipboard_get.side_effect = AssertionError('lower-priority text was read')
                    with patch('ClipboardImport.parse_text_source', side_effect=AssertionError('text parser was called')):
                        _, events = self.paste(app, native=native)
                    self.adopt(app, events)
                    self.assertEqual(pixels(app.original), expected)
                    app.root.clipboard_get.assert_not_called()
            self.assertEqual(bitmap.getpixel((0, 0)), (3, 4, 5, 6))

    def test_direct_http_text_keeps_signed_bytes_and_fetches_only_via_existing_transport(self):
        for suffix in ('?token=a%2Fb&copy=raw;',
                       '?fallback=data:image/png;base64,AAA=',
                       '?imgurl=https%3A%2F%2Fimages.invalid%2Fnested.png'):
            with self.subTest(query=suffix):
                text = 'HTTPS://images.invalid/source.png' + suffix
                app = self.app(text)
                adapter = http_fixtures.RecordingAdapter(
                    lambda index, request: (200, {'Content-Type': 'image/png'}, self.png))
                with http_fixtures.ImageRedirectTests().transport(adapter):
                    _, events = self.paste(app)
                self.adopt(app, events)
                self.assertEqual(app.url.get(), text)
                self.assertEqual(len(adapter.requests), 1)
                self.assertEqual(adapter.requests[0].url, 'https://images.invalid/source.png' + suffix)
                self.assertEqual(pixels(app.original), PIXELS)
                self.assertIsNone(app.browser_one_click_request)

    def test_explicit_drop_in_retains_its_action_and_waits_for_loader_done(self):
        app = self.app(self.uri, armed=True)
        _, events = self.paste(app)
        kind, payload = events[0]
        self.assertEqual(payload[2:], (DROP_IN_ACTION, False))
        self.addCleanup(payload[0].close)
        DrawBotApp._handle_event(app, kind, payload)
        self.assertEqual(app.activity, 'load')
        self.assertEqual(app.drop_action_pending, DROP_IN_ACTION)
        self.assertEqual(app.root.jobs, {})
        self.assertIsNone(app.browser_one_click_request)
        DrawBotApp._handle_event(app, *events[1])
        self.assertIsNone(app.activity)
        self.assertEqual(len(app.root.jobs), 1)
        self.assertTrue(DrawBotApp._manual_drop_in_armed(app))
        self.assertEqual(pixels(app.original), PIXELS)

    def test_pasted_text_replaces_old_browser_request_without_inheriting_force(self):
        app = self.app(self.uri, automatic=True)
        old = DrawBotApp._new_browser_one_click_request(app, force=True)
        old['phase'] = 'finish'
        self.assertTrue(DrawBotApp._schedule_browser_one_click(app, old, finish=True))
        old_callback = app.root.history[app.browser_one_click_after]
        _, events = self.paste(app)
        self.assertTrue(old['cancelled'].is_set())
        self.assertFalse(app.browser_one_click_force)
        self.adopt(app, events)
        new = app.browser_one_click_request
        new_token = app.browser_one_click_after
        self.assertIsNot(new, old)
        self.assertIs(new['image'], app.original)
        self.assertFalse(new['force'])
        self.assertEqual(new['phase'], 'queued')
        self.assertFalse(old_callback())
        self.assertIs(app.browser_one_click_request, new)
        self.assertEqual(app.browser_one_click_after, new_token)
        DrawBotApp._cancel_browser_one_click(app, 'test cleanup')

    def test_stop_before_ui_adoption_closes_candidate_and_keeps_original(self):
        for text in (self.path.as_uri(), self.uri):
            app = self.app(text, automatic=True)
            old = app.original
            _, events = self.paste(app)
            candidate = events[0][1][0]
            DrawBotApp.cancel(app)
            self.adopt(app, events)
            self.assertIs(app.original, old)
            with self.assertRaises(ValueError): candidate.getpixel((0, 0))
            self.assertIsNone(app.browser_one_click_request)
            self.assertEqual(app.root.jobs, {})

    def test_existing_decoder_and_budget_failures_preserve_previous_source(self):
        unsupported = 'data:image/png;base64,' + base64.b64encode(b'%!PS-Adobe-3.0 EPSF-3.0\n').decode('ascii')
        for text, budget, message in (
                (self.uri, ('MAX_DOWNLOAD_BYTES', 8), 'too large'),
                (self.path.as_uri(), ('MAX_SOURCE_BYTES', 8), 'file-size limit'),
                (self.uri, ('MAX_SOURCE_PIXELS', 5), 'megapixels'),
                (unsupported, None, 'raster formats'),
                ('data:image/png;base64,AAA', None, 'decoded')):
            with self.subTest(budget=budget, source=text[:24]), ExitStack() as local:
                app = self.app(text)
                old = app.original
                if budget is not None: local.enter_context(patch('DrawBot.' + budget[0], budget[1]))
                _, events = self.paste(app)
                self.assertNotIn('loaded', [kind for kind, payload in events])
                self.adopt(app, events)
                self.assertIs(app.original, old)
                self.assertIn(message, app.status.get())
                self.assertIsNone(app.browser_one_click_request)

    def test_invalid_or_non_source_text_never_starts_a_loader_or_expands_schemes(self):
        for text in ('', 'ordinary clipboard text', 'ftp://images.invalid/source.png',
                     'javascript:https://images.invalid/source.png',
                     '<img src="https://images.invalid/source.png">',
                     'Read https://images.invalid/source.png first',
                     'https://images.invalid/source.png trailing words',
                     'https://[invalid', 'https:///missing-host',
                     'https://images.invalid:99999/source.png',
                     'data:image/svg+xml;base64,PHN2Zz4=', self.uri + ' trailing text',
                     '"' + str(self.directory / 'missing.png') + '"'):
            with self.subTest(source=text[:50]), patch('PIL.ImageGrab.grabclipboard', return_value=None):
                app = self.app(text)
                old = app.original
                self.assertFalse(DrawBotApp.paste_image(app))
                self.assertFalse(hasattr(app, 'worker'))
                self.assertIs(app.original, old)
                self.assertTrue(app.events.empty())
                self.assertIn('Could not paste', app.status.get())

    def test_text_limit_is_checked_before_parser_work_or_whitespace_trimming(self):
        with patch('ClipboardImport.MAX_DROP_CHARACTERS', 80), \
                patch('ClipboardImport.parse_canvas_drop', side_effect=AssertionError('parser ran')):
            for text in (' ' * 81, 'https://images.invalid/' + 'x' * 80):
                with self.assertRaisesRegex(ValueError, 'too large'):
                    parse_text_source(text)

    def test_live_profile_guards_prevent_clipboard_acquisition(self):
        for field, value in (('activity', 'draw'), ('closing', True),
                             ('pending_clear_drawing', object()),
                             ('profile_change_after', 'job'), ('profile_change_in_progress', True)):
            with self.subTest(field=field), patch('PIL.ImageGrab.grabclipboard') as grab:
                app = self.app(self.uri)
                setattr(app, field, value)
                DrawBotApp.paste_image(app)
                grab.assert_not_called()
                app.root.clipboard_get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
