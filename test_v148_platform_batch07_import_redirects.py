"""Public image import through real Requests redirect machinery, no network."""
from contextlib import closing, contextmanager
from email.message import Message
from io import BytesIO
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

import ImageImport as imports


class CountingRaw:
    def __init__(self, data, headers, *, on_close=None, fail_close=False):
        self.data = BytesIO(data)
        self.read_bytes = 0
        self.closed = False
        self.on_close = on_close
        self.fail_close = fail_close
        message = Message()
        for name, value in headers.items():
            message[name] = value
        self._original_response = SimpleNamespace(msg=message)

    def read(self, size=-1, **_kwargs):
        data = self.data.read(size)
        self.read_bytes += len(data)
        return data

    def read1(self, size=-1, **kwargs):
        return self.read(size, **kwargs)

    def stream(self, size, **kwargs):
        while True:
            data = self.read(size, **kwargs)
            if not data:
                return
            yield data

    def close(self):
        self.closed = True
        self.data.close()
        if self.on_close is not None:
            self.on_close()
        if self.fail_close:
            raise OSError('injected close failure')

    def release_conn(self):
        pass


class RecordingAdapter(BaseAdapter):
    def __init__(self, route, *, on_response=None, on_close=None, fail_close=False):
        self.route = route
        self.on_response = on_response
        self.on_close = on_close
        self.fail_close = fail_close
        self.requests = []
        self.options = []
        self.responses = []
        self.closed = False

    def send(self, request, **options):
        self.requests.append(request)
        self.options.append(options)
        status, headers, body = self.route(len(self.requests)-1, request)
        headers = CaseInsensitiveDict(headers)
        headers.setdefault('Content-Length', str(len(body)))
        response = requests.Response()
        response.status_code, response.headers = status, headers
        response.url, response.request = request.url, request
        response.raw = CountingRaw(body, headers, on_close=self.on_close, fail_close=self.fail_close)
        self.responses.append(response)
        if self.on_response is not None:
            self.on_response(response)
        return response

    def close(self):
        self.closed = True
        if self.fail_close:
            raise OSError('injected adapter close failure')


class ImageRedirectTests(unittest.TestCase):
    def setUp(self):
        output = BytesIO()
        image = Image.new('RGB', (2, 2), 'red')
        try:
            image.save(output, format='PNG')
            self.png = output.getvalue()
        finally:
            image.close()
            output.close()

    @contextmanager
    def transport(self, adapter):
        initialize = requests.Session.__init__

        def initialize_with_adapter(session):
            initialize(session)
            session.mount('https://', adapter)
            session.mount('http://', adapter)

        # Keep actual Session.send, hooks, auth, cookies and redirect resolution.
        with patch.object(requests.Session, '__init__', initialize_with_adapter):
            yield adapter

    def read(self, url='https://images.invalid/start', **kwargs):
        with closing(imports.read_image(url, **kwargs)) as image:
            return image.size, image.getpixel((0, 0))

    def one_redirect(self, *, location='/final', status=302, body=None):
        body = b'x' * (1024*1024) if body is None else body
        return lambda index, _request: ((status, {'Location': location, 'Content-Type': 'text/html'}, body)
                                       if index == 0 else (200, {'Content-Type': 'image/png'}, self.png))

    def test_huge_intermediate_body_is_never_read_or_retained_before_bounded_png(self):
        adapter = RecordingAdapter(self.one_redirect())
        with self.transport(adapter):
            self.assertEqual(self.read(max_download_bytes=128), ((2, 2), (255, 0, 0, 255)))
        self.assertEqual(adapter.responses[0].raw.read_bytes, 0)
        self.assertEqual(adapter.responses[0].content, b'')
        self.assertEqual(adapter.responses[1].raw.read_bytes, len(self.png))
        self.assertTrue(all(response.raw.closed for response in adapter.responses))
        self.assertTrue(adapter.closed)

    def test_all_standard_redirect_statuses_preserve_relative_url_quoting_and_fragments(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                adapter = RecordingAdapter(self.one_redirect(location='../assets/image name.png', status=status))
                with self.transport(adapter):
                    self.read('https://images.invalid/folder/start#selection')
                self.assertEqual(adapter.requests[1].url, 'https://images.invalid/assets/image%20name.png#selection')
                self.assertEqual(adapter.responses[0].raw.read_bytes, 0)

    def test_standard_same_origin_auth_cookies_and_cross_origin_stripping_are_preserved(self):
        def route(index, _request):
            if index == 0:
                return 302, {'Location': 'https://images.invalid/second', 'Set-Cookie': 'image_access=one; Path=/'}, b'redirect'
            if index == 1:
                return 307, {'Location': '//other.invalid/final'}, b'redirect'
            return 200, {'Content-Type': 'image/png'}, self.png

        # Requests' existing cookie matching treats a userinfo URL differently;
        # exercise ordinary cookie URLs and explicit URL credentials separately.
        for credentials in (False, True):
            with self.subTest(credentials=credentials):
                adapter = RecordingAdapter(route)
                prefix = 'fixture-user:fixture-password@' if credentials else ''
                with self.transport(adapter):
                    self.read(f'https://{prefix}images.invalid/start')
                first, same_origin, other_origin = adapter.requests
                if credentials:
                    self.assertIn('Authorization', first.headers)
                    self.assertEqual(same_origin.headers.get('Authorization'), first.headers['Authorization'])
                else:
                    self.assertEqual(same_origin.headers.get('Cookie'), 'image_access=one')
                self.assertNotIn('Authorization', other_origin.headers)
                self.assertNotIn('Cookie', other_origin.headers)
                self.assertTrue(all(response.raw.closed for response in adapter.responses))

    def test_proxy_tls_timeouts_and_legitimate_local_http_redirect_remain_supported(self):
        adapter = RecordingAdapter(self.one_redirect(location='http://127.0.0.1/final'))
        environment = {'HTTPS_PROXY': 'http://proxy.invalid:8080', 'HTTP_PROXY': 'http://proxy.invalid:8080',
                       'NO_PROXY': '', 'https_proxy': '', 'http_proxy': '', 'no_proxy': ''}
        # Lowercase nonempty values win on some platforms, so give both cases
        # the same controlled proxy instead of relying on the runner's settings.
        environment['https_proxy'] = environment['http_proxy'] = 'http://proxy.invalid:8080'
        with patch.dict(os.environ, environment), self.transport(adapter):
            self.read()
        self.assertEqual(adapter.requests[1].url, 'http://127.0.0.1/final')
        for options in adapter.options:
            self.assertEqual(options['timeout'], (10, 15))
            self.assertTrue(options['verify'])
            self.assertTrue(options['stream'])
            self.assertIn('http://proxy.invalid:8080', options['proxies'].values())

    def test_invalid_scheme_or_oversized_redirect_is_rejected_before_adapter_send(self):
        destinations = ('file:///not-an-image.png', 'ftp://images.invalid/final',
                        'https://images.invalid/' + 'x'*imports._MAX_URL_CHARACTERS)
        for destination in destinations:
            with self.subTest(destination=destination[:40]):
                adapter = RecordingAdapter(self.one_redirect(location=destination))
                with self.transport(adapter), self.assertRaises(ValueError):
                    self.read()
                self.assertEqual(len(adapter.requests), 1)
                self.assertEqual(adapter.responses[0].raw.read_bytes, 0)
                self.assertTrue(adapter.responses[0].raw.closed)

    def test_loop_keeps_requests_existing_hop_limit_without_reading_redirect_bodies(self):
        adapter = RecordingAdapter(lambda *_: (302, {'Location': '/start'}, b'ignored'))
        with self.transport(adapter), self.assertRaises(ValueError):
            self.read()
        self.assertEqual(len(adapter.requests), requests.models.DEFAULT_REDIRECT_LIMIT + 1)
        self.assertTrue(all(response.raw.read_bytes == 0 and response.raw.closed for response in adapter.responses))

    def test_stop_between_redirect_hops_prevents_next_request(self):
        stopped = [False]
        adapter = RecordingAdapter(self.one_redirect(), on_close=lambda: stopped.__setitem__(0, True))
        with self.transport(adapter), self.assertRaises(InterruptedError):
            self.read(cancelled=lambda: stopped[0])
        self.assertEqual(len(adapter.requests), 1)
        self.assertEqual(adapter.responses[0].raw.read_bytes, 0)
        self.assertTrue(adapter.responses[0].raw.closed)

    def test_deadline_between_hops_prevents_next_request_without_draining_body(self):
        clock = [10.0]
        adapter = RecordingAdapter(self.one_redirect(), on_close=lambda: clock.__setitem__(0, 100.0))
        with self.transport(adapter), patch.object(imports.time, 'monotonic', side_effect=lambda: clock[0]), \
             self.assertRaisesRegex(ValueError, 'took too long'):
            self.read()
        self.assertEqual(len(adapter.requests), 1)
        self.assertEqual(adapter.responses[0].raw.read_bytes, 0)

    def test_stop_on_redirect_or_final_headers_closes_response_and_preserves_primary_error(self):
        for redirect in (True, False):
            with self.subTest(redirect=redirect):
                stopped = [False]
                route = self.one_redirect() if redirect else lambda *_: (200, {'Content-Type': 'image/png'}, self.png)
                adapter = RecordingAdapter(route, on_response=lambda _: stopped.__setitem__(0, True), fail_close=True)
                with self.transport(adapter), self.assertRaises(InterruptedError):
                    self.read(cancelled=lambda: stopped[0])
                self.assertEqual(len(adapter.requests), 1)
                self.assertEqual(adapter.responses[0].raw.read_bytes, 0)
                self.assertTrue(adapter.responses[0].raw.closed)
                self.assertTrue(adapter.closed)

    def test_final_body_limit_and_content_length_checks_still_apply_after_redirect(self):
        def route(index, _request):
            if index == 0:
                return 302, {'Location': '/final'}, b'ignored'
            return 200, {'Content-Type': 'image/png', 'Content-Length': '500'}, self.png

        adapter = RecordingAdapter(route)
        with self.transport(adapter), self.assertRaisesRegex(ValueError, 'file-size limit'):
            self.read(max_download_bytes=128)
        self.assertTrue(all(response.raw.read_bytes == 0 and response.raw.closed for response in adapter.responses))


if __name__ == '__main__':
    unittest.main()
