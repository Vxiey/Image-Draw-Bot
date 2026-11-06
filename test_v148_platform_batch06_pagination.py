"""Actual updater calls over bounded synthetic paginated GitHub responses."""
import json
import threading
import unittest
from unittest.mock import patch

import UpdateCenter as update
from test_update_security import RecordingAdapter
import requests


def release(version, *, prerelease=False):
    return {'tag_name': 'v' + version, 'draft': False, 'prerelease': prerelease}


class ReleasePaginationTests(unittest.TestCase):
    def transport(self, pages):
        session = requests.Session()
        session.trust_env = False
        adapter = RecordingAdapter(pages)
        session.mount('https://', adapter)
        self.addCleanup(session.close)
        return session.get, adapter

    def payload(self, entries, next_url=None):
        headers = {'Link': f'<{next_url}>; rel="next"'} if next_url else {}
        return (200, headers, json.dumps(entries).encode())

    def test_stable_release_after_one_hundred_prereleases_is_found(self):
        first = update.GITHUB_RELEASES_API
        second = first + '&page=2'
        get, adapter = self.transport({
            first: self.payload([release(f'99.0.0-rc{i}', prerelease=True) for i in range(1, 101)], second),
            second: self.payload([release('98.0.0')]),
        })
        with patch.object(update, 'BUILD_CHANNEL', 'stable'):
            result = update.check_for_updates(request_get=get)
        self.assertEqual(result['latest_version'], '98.0.0')
        self.assertTrue(result['update_available'])
        self.assertEqual(adapter.calls, [first, second])
        self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_semantic_best_is_selected_across_all_pages_not_first_matching_page(self):
        first = update.GITHUB_RELEASES_API
        second = first + '&page=2'
        third = first + '&page=3'
        get, adapter = self.transport({
            first: self.payload([release('90.0.0')], second),
            second: self.payload([release('99.0.0')], third),
            third: self.payload([release('91.0.0')]),
        })
        self.assertEqual(update.check_for_updates(request_get=get)['latest_version'], '99.0.0')
        self.assertEqual(len(adapter.calls), 3)

    def test_numeric_github_links_use_only_the_next_page_on_the_fixed_repository(self):
        first = update.GITHUB_RELEASES_API
        second = first + '&page=2'
        get, adapter = self.transport({
            first: self.payload([], 'https://api.github.com/repositories/123/releases?per_page=100&page=2'),
            second: self.payload([release('99.0.0')]),
        })
        self.assertEqual(update.check_for_updates(request_get=get)['latest_version'], '99.0.0')
        self.assertEqual(adapter.calls, [first, second])

    def test_untrusted_repeated_skipped_or_ambiguous_page_is_never_requested(self):
        first = update.GITHUB_RELEASES_API
        urls = ['https://example.test/private?page=2',
                'http://api.github.com/repos/Vxiey/Image-Draw-Bot/releases?page=2',
                'https://api.github.com/repos/other/project/releases?page=2',
                first + '&page=1', first + '&page=3', first + '&page=2&page=3',
                first + '&page=2&access_token=SYNTHETIC',
                first.replace('100', '1') + '&page=2']
        for url in urls:
            get, adapter = self.transport({first: self.payload([], url)})
            with self.subTest(url=url), self.assertRaises(update.UpdateCheckError):
                update.check_for_updates(request_get=get)
            self.assertEqual(adapter.calls, [first])
            self.assertTrue(adapter.streams[0].closed)

    def test_incomplete_history_never_reports_the_current_release_as_latest(self):
        first = update.GITHUB_RELEASES_API
        second = first + '&page=2'
        get, adapter = self.transport({first: self.payload([release(update.APP_VERSION)], second)})
        with patch.object(update, '_MAX_RELEASE_PAGES', 1), self.assertRaisesRegex(update.UpdateCheckError, 'history exceeds'):
            update.check_for_updates(request_get=get)
        self.assertEqual(adapter.calls, [first])
        self.assertTrue(adapter.streams[0].closed)

    def test_metadata_budget_is_shared_by_pages(self):
        first = update.GITHUB_RELEASES_API
        second = first + '&page=2'
        content = [release('99.0.0')]
        size = len(json.dumps(content).encode())
        get, adapter = self.transport({first: self.payload(content, second), second: self.payload(content)})
        with patch.object(update, '_MAX_RELEASE_RESPONSE_BYTES', size + 1):
            with self.assertRaisesRegex(update.UpdateCheckError, 'allowed size'):
                update.check_for_updates(request_get=get)
        self.assertEqual(len(adapter.calls), 2)
        self.assertTrue(all(stream.closed for stream in adapter.streams))

    def test_stop_or_deadline_between_pages_closes_response_and_sends_no_next_request(self):
        first = update.GITHUB_RELEASES_API
        for cancel in (False, True):
            stop = threading.Event()
            clock = [0.0]
            get, adapter = self.transport({first: self.payload([], first + '&page=2')})
            close = update._close_response
            def on_close(response):
                close(response)
                if cancel:
                    stop.set()
                else:
                    clock[0] = update._MAX_RELEASE_CHECK_SECONDS + 1
            with self.subTest(cancel=cancel), patch.object(update.time, 'monotonic', side_effect=lambda: clock[0]), \
                 patch.object(update, '_close_response', side_effect=on_close):
                with self.assertRaises(InterruptedError if cancel else update.UpdateCheckError):
                    update.check_for_updates(request_get=get, cancelled=stop.is_set)
            self.assertEqual(adapter.calls, [first])
            self.assertTrue(adapter.streams[0].closed)


if __name__ == '__main__':
    unittest.main()
