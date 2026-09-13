import unittest

from UpdateCenter import (check_for_updates, is_newer_version, normalize_tag,
                          parse_version, select_best_release)
from Version import APP_VERSION, FILE_VERSION


class _Response:
    def __init__(self, payload, status=200):
        self.payload=payload; self.status=status
    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f'HTTP {self.status}')
    def json(self):
        return self.payload


class UpdateCenterTests(unittest.TestCase):
    def test_version_metadata(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_version_parser_orders_beta_and_stable(self):
        self.assertTrue(is_newer_version('1.0.59', '1.0.59-beta'))
        self.assertTrue(is_newer_version('1.0.89-beta', '1.0.59'))
        self.assertFalse(is_newer_version('1.0.59-beta', '1.0.59-beta'))
        self.assertEqual(normalize_tag('v1.2.3-beta'), '1.2.3-beta')
        self.assertIsNone(parse_version('nightly'))

    def test_select_best_release_ignores_drafts(self):
        releases=[
            {'tag_name':'v1.0.60-beta','draft':True,'prerelease':True},
            {'tag_name':'v1.0.59-beta','draft':False,'prerelease':True},
            {'tag_name':'v1.0.59','draft':False,'prerelease':False},
        ]
        self.assertEqual(select_best_release(releases)['tag_name'],'v1.0.59')

    def test_manual_check_returns_release_without_downloading(self):
        calls=[]
        def get(url, **kwargs):
            calls.append((url,kwargs))
            return _Response([{
                'tag_name':'v1.0.90','draft':False,'prerelease':False,
                'html_url':'https://github.com/yesverynice12/Image-Draw-Bot/releases/tag/v1.0.90',
                'name':'Image Draw Bot v1.0.90',
            }])
        from unittest.mock import patch
        with patch('UpdateCenter.APP_VERSION','1.0.89-beta'):
            result=check_for_updates(request_get=get)
        self.assertTrue(result['update_available'])
        self.assertEqual(result['latest_version'],'1.0.90')
        self.assertEqual(len(calls),1)
        self.assertIn('/releases?',calls[0][0])


    def test_published_rc3_detects_v10140_rc1_as_update(self):
        release={
            'tag_name':'v1.0.142-rc1','draft':False,'prerelease':True,
            'html_url':'https://github.com/Vxiey/Image-Draw-Bot/releases/tag/v1.0.142-rc1',
            'name':'Image Draw Bot v1.0.142-rc1','assets':[],
        }
        from unittest.mock import patch
        with patch('UpdateCenter.APP_VERSION','1.0.133-rc3'), patch('UpdateCenter.BUILD_CHANNEL','rc'):
            result=check_for_updates(request_get=lambda *a,**k:_Response([release]))
        self.assertTrue(result['update_available'])
        self.assertEqual(result['latest_version'],'1.0.142-rc1')


if __name__=='__main__':
    unittest.main()
