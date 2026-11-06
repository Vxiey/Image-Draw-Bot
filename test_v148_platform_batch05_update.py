from contextlib import contextmanager
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests
from urllib3.response import HTTPResponse

import UpdateCenter as update


@contextmanager
def trickling_response(body, on_byte):
    state = SimpleNamespace(sent=0, read1_calls=0, response=None)
    reading, finish = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if not reading.wait(3):
                return
            for byte in body:
                if finish.wait(.003):
                    break
                try:
                    state.sent += 1
                    on_byte(state.sent)
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                except OSError:
                    break

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()

    def get(url, **kwargs):
        # This explicitly injected test transport talks only to its loopback
        # server; production HTTPS URL/redirect validation is left intact.
        response = requests.get(f'http://127.0.0.1:{server.server_port}/', stream=True, timeout=(1, .5))
        response.url = url
        original_read1, original_close = response.raw.read1, response.close
        def read1(*args, **options):
            state.read1_calls += 1
            reading.set()
            return original_read1(*args, **options)
        response.raw.read1 = read1
        response.close = Mock(wraps=original_close)
        state.response = response
        return response

    try:
        yield get, state
    finally:
        finish.set()
        reading.set()
        if state.response is not None:
            state.response.close()
        server.shutdown()
        server.server_close()
        thread.join(2)


class AvailableUpdateBodyTests(unittest.TestCase):
    def test_stop_during_a_trickling_release_body_does_not_wait_for_the_complete_chunk(self):
        stop = threading.Event()
        body = b' ' * 126 + b'[]'
        def on_byte(number):
            if number == 3:
                stop.set()
        with trickling_response(body, on_byte) as (get, state):
            with self.assertRaises(InterruptedError):
                update.check_for_updates(request_get=get, cancelled=stop.is_set)
            self.assertGreater(state.read1_calls, 0)
            self.assertLess(state.sent, len(body))
            state.response.close.assert_called_once()

    def test_elapsed_budget_is_checked_while_small_body_chunks_continue_arriving(self):
        clock = [0.0]
        body = b' ' * 126 + b'[]'
        def on_byte(number):
            if number == 3:
                clock[0] = update._MAX_RELEASE_CHECK_SECONDS + 1
        with trickling_response(body, on_byte) as (get, state), \
             patch.object(update, 'time', SimpleNamespace(monotonic=lambda: clock[0])):
            with self.assertRaisesRegex(update.UpdateCheckError, 'timed out'):
                update.check_for_updates(request_get=get)
            self.assertGreater(state.read1_calls, 0)
            self.assertLess(state.sent, len(body))
            state.response.close.assert_called_once()

    def test_installer_stop_removes_partial_data_before_the_remaining_body_arrives(self):
        body = b'MZ' + b'x' * 126
        name = 'ImageDrawBot-1.0.148-Windows-x64-Setup.exe'
        asset = {'name': name, 'version': '1.0.148', 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                 'url': f'https://github.com/{update.GITHUB_REPOSITORY}/releases/download/v1.0.148/{name}'}
        stop = threading.Event()
        def on_byte(number):
            if number == 3:
                stop.set()
        with tempfile.TemporaryDirectory() as temporary, trickling_response(body, on_byte) as (get, state):
            with self.assertRaises(InterruptedError):
                update.download_installer(asset, directory=temporary, request_get=get, cancelled=stop.is_set)
            self.assertGreater(state.read1_calls, 0)
            self.assertLess(state.sent, len(body))
            self.assertEqual(list(Path(temporary).iterdir()), [])
            state.response.close.assert_called_once()

    def test_available_reads_still_decode_compressed_metadata_and_enforce_decoded_size(self):
        for limit, succeeds in ((100, True), (1, False)):
            response = requests.Response()
            response.status_code = 200
            response.url = update.GITHUB_RELEASES_API
            response.raw = HTTPResponse(body=BytesIO(gzip.compress(b'[]')),
                                        headers={'Content-Encoding': 'gzip'}, preload_content=False)
            with self.subTest(limit=limit), patch.object(update, '_MAX_RELEASE_RESPONSE_BYTES', limit):
                if succeeds:
                    self.assertFalse(update.check_for_updates(request_get=lambda *a, **kw: response)['update_available'])
                else:
                    with self.assertRaisesRegex(update.UpdateCheckError, 'allowed size'):
                        update.check_for_updates(request_get=lambda *a, **kw: response)


if __name__ == '__main__':
    unittest.main()
