import unittest
from pathlib import Path

from Version import APP_VERSION, FILE_VERSION
import VersionHistory


class VersionHistoryIndexTests(unittest.TestCase):
    def test_release_metadata(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_version_history_files_exist(self):
        root = Path(__file__).resolve().parent
        self.assertTrue((root / 'VERSION-HISTORY.md').is_file())
        self.assertTrue((root / 'README-INDEX.md').is_file())
        self.assertTrue((root / 'docs' / 'README.md').is_file())
        self.assertTrue((root / 'docs' / 'history' / 'README.md').is_file())
        text = (root / 'VERSION-HISTORY.md').read_text(encoding='utf-8')
        self.assertIn('1.0.89-beta', text)
        self.assertIn('1.0.67-beta', text)
        self.assertIn('Gartic Engine v2', text)
        self.assertIn('Skribbl Turbo Renderer', text)

    def test_about_window_has_version_history_button(self):
        text = (Path(__file__).resolve().parent / 'DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('def show_version_history', text)
        self.assertIn('Version history', text)
        self.assertIn('read_version_history', text)

    def test_pyinstaller_includes_docs(self):
        text = (Path(__file__).resolve().parent / 'build_exe.py').read_text(encoding='utf-8')
        self.assertIn("'VERSION-HISTORY.md'", text)
        self.assertIn("'README-INDEX.md'", text)
        self.assertIn("'docs'", text)
        self.assertIn("'VersionHistory'", text)

    def test_local_version_history_reader(self):
        text = VersionHistory.read_version_history()
        self.assertIn('Image Draw Bot Version History', text)
        self.assertIn(APP_VERSION, text)


if __name__ == '__main__':
    unittest.main()
