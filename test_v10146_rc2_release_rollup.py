import unittest
from pathlib import Path

from Version import APP_VERSION, FILE_VERSION


class V10146Rc2ReleaseRollupTests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(APP_VERSION, "1.0.146-rc2")
        self.assertEqual(FILE_VERSION, "1.0.146")

    def test_installer_metadata_matches_rc_line(self):
        text=Path("installer/ImageDrawBot.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "1.0.146-rc2"', text)
        self.assertIn('VersionInfoVersion=1.0.146.0', text)

    def test_release_notes_and_public_index(self):
        self.assertTrue(Path("RELEASE-NOTES-v1.0.146-rc2.md").is_file())
        readme=Path("README.md").read_text(encoding="utf-8")
        index=Path("README-INDEX.md").read_text(encoding="utf-8")
        self.assertIn("v1.0.146-rc2", readme)
        self.assertIn("Current release: v1.0.146-rc2", index)

    def test_rc2_rolls_up_both_validated_fixes(self):
        self.assertTrue(Path("BackgroundRemoval.py").is_file())
        self.assertTrue(Path("ExtraFastProfilePolicy.py").is_file())
        auto=Path("AutoDrawing.py").read_text(encoding="utf-8")
        self.assertIn("apply_extra_fast_profile_policy", auto)


if __name__ == "__main__":
    unittest.main()
