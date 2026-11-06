import ast
import json
import unittest
from unittest.mock import patch

from LocalSanitization import sanitize_text


class SerializedPathPrivacyTests(unittest.TestCase):
    def test_unterminated_escaped_quote_line_remains_unchanged(self):
        value = '"' + '\\"' * 10000
        self.assertEqual(sanitize_text(value), value)

    def test_bare_home_literal_preserves_its_closing_quote_and_following_arguments(self):
        for username in ('SyntheticUser', "Private'Person", 'Privat\u00e9\u0416'):
            for prefix in ('C:\\Users\\', '/home/', '/Users/'):
                home = prefix + username
                with self.subTest(home=home):
                    self.assertEqual(ast.literal_eval(sanitize_text(repr(home))), prefix + '<user>')
                    values = [home, '--target-probe', 'untouched argument']
                    self.assertEqual(ast.literal_eval(sanitize_text(repr(values))),
                                     [prefix + '<user>', '--target-probe', 'untouched argument'])
                    self.assertEqual(json.loads(sanitize_text(json.dumps({'home': home, 'ok': True}))),
                                     {'home': prefix + '<user>', 'ok': True})

    def test_quoted_message_with_a_bare_home_keeps_its_literal_boundary(self):
        value = [r'Cannot read C:\Users\SyntheticUser', '--target-probe']
        self.assertEqual(ast.literal_eval(sanitize_text(repr(value))),
                         [r'Cannot read C:\Users\<user>', '--target-probe'])

    def test_serialized_windows_paths_do_not_expose_the_profile_name(self):
        for username in ('PRIVATE_WINDOWS_USER', 'Privat\u00e9\u0416\U0001f600', "Private'Person"):
            path = 'C:\\Users\\' + username + '\\Documents\\picture.png'
            for value in (path, repr(path), repr([path, '--target-probe']),
                          json.dumps({'path': path}), json.dumps({'path': path}, ensure_ascii=False)):
                with self.subTest(value=value):
                    clean = sanitize_text(value)
                    self.assertNotIn(username, clean)
                    self.assertNotIn(json.dumps(username)[1:-1], clean)
                    self.assertIn('Documents', clean)
                    if value.startswith('{'):
                        self.assertEqual(json.loads(clean), {'path': 'C:\\Users\\<user>\\Documents\\picture.png'})

    def test_serialized_custom_home_is_redacted_without_corrupting_json(self):
        home = 'D:\\Private Profiles\\Privat\u00e9'
        with patch('LocalSanitization.Path.home', return_value=home):
            for path in (home + '\\image.png', home.replace('\\', '/') + '/image.png'):
                for ascii_only in (False, True):
                    source = json.dumps({'path': path, 'status': 'failed'}, ensure_ascii=ascii_only)
                    clean = sanitize_text(source)
                    parsed = json.loads(clean)
                    self.assertEqual(parsed['status'], 'failed')
                    self.assertTrue(parsed['path'].startswith('<USER_HOME>'))
                    self.assertNotIn('Privat', clean)


if __name__ == '__main__':
    unittest.main()
