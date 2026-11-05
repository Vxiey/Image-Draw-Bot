"""Source archives must not contain state left behind by running the app."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from ReleasePackage import REQUIRED_RELEASE_FILES, create_source_archive, validate_release_tree


class SourceArchivePrivacyTests(unittest.TestCase):
    def test_source_archive_excludes_runtime_state_and_keeps_shipped_fixtures(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            for relative in REQUIRED_RELEASE_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("release fixture", encoding="utf-8")
            private_files = (
                "completed-drawings/microsoft-paint/history.json",
                "recovery/private-source.png",
                "picture-palettes/private.json",
                "updates/partial-download.bin",
                "settings-microsoft-paint.json",
                "calibration.json",
                "exact-colors-generic.json",
                "app-tools-generic.json",
                "paint-tools.json",
                "draw-time-calibration.json",
                "auto-tuner-feedback-generic.json",
                "correction-history-generic.json",
                "layout-fingerprints-v2.json",
                "profiles.json",
                "release-state.json",
                "session-recovery.png",
            )
            public_files = (
                "palette-index-maps.json", "verified-colors-microsoft-paint.json",
                "resource-scheduler-v2.json", "golden-regression/manifest.json",
                "docs/settings-example.json",
            )
            for relative in (*private_files, *public_files):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")

            self.assertTrue(validate_release_tree(root).ok)
            archive_path = Path(temp) / "source.zip"
            create_source_archive(root, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
            for relative in private_files:
                with self.subTest(private=relative):
                    self.assertNotIn("Image-Draw-Bot/" + relative, names)
            for relative in public_files:
                with self.subTest(public=relative):
                    self.assertIn("Image-Draw-Bot/" + relative, names)


if __name__ == "__main__":
    unittest.main()
