import unittest
from pathlib import Path
from Version import APP_VERSION,FILE_VERSION


EXPECTED_APP_VERSION = '1.0.149'
EXPECTED_FILE_VERSION = EXPECTED_APP_VERSION.split('-', 1)[0]


class VersionMetadataTests(unittest.TestCase):
    def test_runtime_report_version_has_single_source(self):
        self.assertTrue(APP_VERSION.startswith(FILE_VERSION))

    def test_windows_version_resource_matches(self):
        text=(Path(__file__).resolve().parent/'version_info.txt').read_text(encoding='utf-8')
        self.assertIn(f"FileVersion', '{FILE_VERSION}'",text)
        self.assertIn(f"ProductVersion', '{FILE_VERSION}'",text)
        numbers=tuple(map(int,FILE_VERSION.split('.'))) + (0,)
        compact='('+','.join(map(str,numbers))+')'
        self.assertIn(f"filevers={compact}, prodvers={compact}",text)


if __name__=='__main__':unittest.main()
