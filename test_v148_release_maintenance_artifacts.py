"""Source archives omit completed integration jobs while retaining current tooling."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from ReleasePackage import (
    REQUIRED_RELEASE_FILES,
    create_source_archive,
    is_forbidden_path,
    is_nonfatal_excluded_path,
    validate_release_tree,
)


class HistoricalIntegrationArchiveTests(unittest.TestCase):
    def test_archive_excludes_old_jobs_and_verifier_log_but_keeps_live_files(self):
        completed_releases = (4, 5, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)
        historical = [
            path
            for rc in completed_releases
            for path in (f".github/workflows/implement-rc{rc}.yml", f".github/implement-rc{rc}-trigger")
        ]
        historical += [f".github/scripts/implement_rc{rc}.py" for rc in completed_releases if rc != 4]
        historical += [
            ".github/scripts/fix_rc19_class_indent.py",
            ".github/scripts/fix_rc20_test.py",
            ".github/scripts/migrate_rc16_tests.py",
            ".github/scripts/migrate_rc17_tests.py",
            ".github/scripts/run_rc21_retry.py",
        ]
        excluded = [*historical, "verification.txt"]
        retained = [
            ".github/workflows/build-windows.yml", ".github/workflows/ci.yml",
            ".github/workflows/publish-wiki.yml", ".github/release-build-trigger",
            ".github/scripts/active_release_check.py", "ReleasePackage.py",
            "PictureCustomPaletteLegacy.py", "HybridCostModel.py", "SourceStartup.py",
            "AutoGpuSetup.py", "ExecutionTelemetry.py",
            ".github/workflows/implement-rc24.yml", ".github/scripts/implement_rc24.py",
            ".github/implement-rc24-trigger", "docs/examples/.github/scripts/implement_rc23.py",
            "docs/examples/verification.txt",
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            for relative in (*REQUIRED_RELEASE_FILES, *excluded, *retained):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("archive fixture", encoding="utf-8")

            report = validate_release_tree(root)
            self.assertTrue(report.ok, report.to_dict())
            archive_path = Path(temp) / "source.zip"
            create_source_archive(root, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                archived = set(archive.namelist())
            for relative in excluded:
                with self.subTest(excluded=relative):
                    self.assertNotIn("Image-Draw-Bot/" + relative, archived)
            for relative in retained:
                with self.subTest(retained=relative):
                    self.assertIn("Image-Draw-Bot/" + relative, archived)

    def test_known_maintenance_paths_use_same_case_insensitive_nonfatal_policy(self):
        for relative in (
            ".GITHUB/WORKFLOWS/IMPLEMENT-RC23.YML",
            ".github/scripts/implement_RC5.py",
            ".github/IMPLEMENT-RC13-TRIGGER",
            ".github/scripts/RUN_RC21_RETRY.PY",
        ):
            with self.subTest(path=relative):
                self.assertTrue(is_forbidden_path(relative))
                self.assertTrue(is_nonfatal_excluded_path(relative))


if __name__ == "__main__":
    unittest.main()
