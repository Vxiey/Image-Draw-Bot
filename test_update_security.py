"""Exercise update trust boundaries using Requests' real redirect handling."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from UpdateCenter import (
    GITHUB_RELEASES_API, UpdateCheckError, check_for_updates, download_installer,
    installer_asset, parse_version, select_best_release,
)


DATA = b'MZ' + b'verified-installer' * 32
TAG = 'v99.0.0'
NAME = 'ImageDrawBot-99.0.0-Windows-x64-Setup.exe'
DOWNLOAD = f'https://github.com/Vxiey/Image-Draw-Bot/releases/download/{TAG}/{NAME}'
CDN = 'https://release-assets.githubusercontent.com/release/file?sig=a%2Fb%3D&expires=123'


def release():
    return {
        'tag_name': TAG,
        'assets': [{
            'name': NAME, 'browser_download_url': DOWNLOAD, 'size': len(DATA),
            'digest': 'sha256:' + hashlib.sha256(DATA).hexdigest(),
        }],
    }


class ResponseStream(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.bytes_read = 0

    def read(self, size=-1):
        content = super().read(size)
        self.bytes_read += len(content)
        return content

    def release_conn(self):
        self.close()


class RecordingAdapter(requests.adapters.BaseAdapter):
    """No network: record all Requests transport calls, including auto-redirects."""
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.streams = []

    def send(self, request, **kwargs):
        self.calls.append(request.url)
        status, headers, content = self.routes[request.url]
        response = requests.Response()
        response.status_code = status
        response.url = request.url
        response.request = request
        response.headers.update(headers)
        response.raw = ResponseStream(content)
        self.streams.append(response.raw)
        return response

    def close(self):
        pass


class UpdateSecurityTests(unittest.TestCase):
    def transport(self, routes):
        session = requests.Session()
        session.trust_env = False
        adapter = RecordingAdapter(routes)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        self.addCleanup(session.close)
        return session.get, adapter

    def default_transport(self, routes):
        adapter = RecordingAdapter(routes)
        class LocalSession(requests.Session):
            def __init__(self):
                super().__init__()
                self.trust_env = False

            def get_adapter(self, url):
                return adapter
        return patch('requests.Session', LocalSession), adapter

    def test_default_transport_does_not_drain_redirect_body(self):
        transport, adapter = self.default_transport({
            GITHUB_RELEASES_API: (302, {'Location': 'http://127.0.0.1/admin'}, b'x' * 1024),
        })
        with transport:
            with self.assertRaises(UpdateCheckError):
                check_for_updates()
        self.assertEqual(adapter.calls, [GITHUB_RELEASES_API])
        self.assertEqual(adapter.streams[0].bytes_read, 0)
        self.assertTrue(adapter.streams[0].closed)

    def test_default_transport_streams_verified_asset_after_redirect(self):
        transport, adapter = self.default_transport({
            DOWNLOAD: (302, {'Location': CDN}, b'unused redirect body'),
            CDN: (200, {}, DATA),
        })
        with transport, tempfile.TemporaryDirectory() as tmp:
            path = download_installer(installer_asset(release()), directory=tmp)
            self.assertEqual(Path(path).read_bytes(), DATA)
        self.assertEqual(adapter.calls, [DOWNLOAD, CDN])
        self.assertEqual(adapter.streams[0].bytes_read, 0)
        self.assertEqual(adapter.streams[1].bytes_read, len(DATA))
        self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_installer_rejects_intermediate_private_host_before_contact(self):
        private = 'http://127.0.0.1/admin/action'
        get, adapter = self.transport({
            DOWNLOAD: (302, {'Location': private}, b''),
            private: (302, {'Location': CDN}, b''),
            CDN: (200, {}, DATA),
        })
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UpdateCheckError):
                download_installer(installer_asset(release()), directory=tmp, request_get=get)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(adapter.calls, [DOWNLOAD])
        self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_installer_allows_signed_cdn_redirect_and_verifies_content(self):
        get, adapter = self.transport({
            DOWNLOAD: (302, {'Location': CDN}, b''),
            CDN: (200, {}, DATA),
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = download_installer(installer_asset(release()), directory=tmp, request_get=get)
            self.assertEqual(Path(path).read_bytes(), DATA)
        self.assertEqual(adapter.calls, [DOWNLOAD, CDN])
        self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_unsafe_redirect_forms_are_rejected_before_request(self):
        destinations = (
            'http://github.com/file', 'https://127.0.0.1/file',
            'https://github.com:8443/file', 'https://user@github.com/file',
            '//example.com/file', 'file:///tmp/file', 'https://[invalid/file',
        )
        for destination in destinations:
            with self.subTest(destination=destination), tempfile.TemporaryDirectory() as tmp:
                get, adapter = self.transport({DOWNLOAD: (302, {'Location': destination}, b'')})
                with self.assertRaises(UpdateCheckError):
                    download_installer(installer_asset(release()), directory=tmp, request_get=get)
                self.assertEqual(adapter.calls, [DOWNLOAD])
                self.assertEqual(list(Path(tmp).iterdir()), [])
                self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_redirect_loop_is_bounded_and_staging_is_removed(self):
        get, adapter = self.transport({DOWNLOAD: (302, {'Location': DOWNLOAD}, b'')})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(UpdateCheckError, 'Too many redirects'):
                download_installer(installer_asset(release()), directory=tmp, request_get=get)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(len(adapter.calls), 6)
        self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_api_rejects_off_host_redirect_before_contact(self):
        outside = 'https://example.com/releases'
        get, adapter = self.transport({
            GITHUB_RELEASES_API: (302, {'Location': outside}, b''),
            outside: (200, {}, b'[]'),
        })
        with self.assertRaises(UpdateCheckError):
            check_for_updates(request_get=get)
        self.assertEqual(adapter.calls, [GITHUB_RELEASES_API])
        self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_api_allows_relative_same_host_redirect(self):
        moved = 'https://api.github.com/repositories/123/releases?per_page=100'
        get, adapter = self.transport({
            GITHUB_RELEASES_API: (301, {'Location': '/repositories/123/releases?per_page=100'}, b''),
            moved: (200, {}, b'[]'),
        })
        result = check_for_updates(request_get=get)
        self.assertFalse(result['update_available'])
        self.assertEqual(adapter.calls, [GITHUB_RELEASES_API, moved])
        self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_metadata_size_limit_does_not_depend_on_content_length(self):
        get, adapter = self.transport({
            GITHUB_RELEASES_API: (200, {'Content-Length': '2'}, b'[' + b' ' * 128 + b']'),
        })
        with patch('UpdateCenter._MAX_RELEASE_RESPONSE_BYTES', 64):
            with self.assertRaisesRegex(UpdateCheckError, 'metadata exceeds'):
                check_for_updates(request_get=get)
        self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_invalid_metadata_is_closed_and_reported_as_check_failure(self):
        for content in (b'not-json', b'{"unexpected":"object"}'):
            with self.subTest(content=content):
                get, adapter = self.transport({GITHUB_RELEASES_API: (200, {}, content)})
                with self.assertRaises(UpdateCheckError):
                    check_for_updates(request_get=get)
                self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_malformed_asset_lists_do_not_break_release_checks(self):
        for assets in (123, True, 'invalid', {'name': NAME}):
            with self.subTest(assets=assets):
                item = release()
                item['assets'] = assets
                get, _ = self.transport({GITHUB_RELEASES_API: (200, {}, json.dumps([item]).encode())})
                self.assertIsNone(check_for_updates(request_get=get)['installer'])
        self.assertIsNone(installer_asset(None))
        item = release()
        item['assets'][0]['browser_download_url'] = 'https://[invalid'
        self.assertIsNone(installer_asset(item))

    def test_extreme_version_tag_is_ignored_without_integer_conversion_failure(self):
        tag = 'v' + '9' * 5000 + '.0.0'
        self.assertIsNone(parse_version(tag))
        self.assertEqual(select_best_release([{'tag_name': tag}, release()])['tag_name'], TAG)

    def test_invalid_download_metadata_fails_before_network_or_staging(self):
        for asset in (None, [], {}, {'url': 'https://[invalid'}):
            with self.subTest(asset=asset), tempfile.TemporaryDirectory() as tmp:
                staging = Path(tmp) / 'updates'
                with self.assertRaises(UpdateCheckError):
                    download_installer(
                        asset, directory=staging,
                        request_get=lambda *a, **kw: self.fail('Invalid metadata must not trigger a request'),
                    )
                self.assertFalse(staging.exists())


if __name__ == '__main__':
    unittest.main()
