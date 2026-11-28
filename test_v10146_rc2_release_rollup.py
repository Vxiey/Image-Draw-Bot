import unittest
from pathlib import Path

from Version import APP_VERSION, FILE_VERSION
from test_version_metadata import EXPECTED_APP_VERSION, EXPECTED_FILE_VERSION


class V10146Rc2ReleaseRollupTests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(APP_VERSION, EXPECTED_APP_VERSION)
        self.assertEqual(FILE_VERSION, EXPECTED_FILE_VERSION)

    def test_installer_metadata_matches_current_release(self):
        text=Path("installer/ImageDrawBot.iss").read_text(encoding="utf-8")
        self.assertIn(f'#define MyAppVersion "{APP_VERSION}"', text)
        self.assertIn(f'VersionInfoVersion={FILE_VERSION}.0', text)

    def test_release_notes_and_public_index(self):
        self.assertTrue(Path(f"RELEASE-NOTES-v{APP_VERSION}.md").is_file())
        readme=Path("README.md").read_text(encoding="utf-8")
        index=Path("README-INDEX.md").read_text(encoding="utf-8")
        self.assertIn(f"v{APP_VERSION}", readme)
        self.assertIn(f"(RELEASE-NOTES-v{APP_VERSION}.md)", index)

    def test_rc2_rolls_up_both_validated_fixes(self):
        self.assertTrue(Path("BackgroundRemoval.py").is_file())
        self.assertTrue(Path("ExtraFastProfilePolicy.py").is_file())
        auto=Path("AutoDrawing.py").read_text(encoding="utf-8")
        self.assertIn("apply_extra_fast_profile_policy", auto)


if __name__ == "__main__":
    unittest.main()
