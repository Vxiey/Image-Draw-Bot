import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from ReleasePackage import (
    REQUIRED_RELEASE_FILES,
    create_source_archive,
    is_forbidden_path,
    validate_release_tree,
    write_release_manifest,
)
from Version import APP_VERSION


class Step21ReleaseCleanupTests(unittest.TestCase):
    def setUp(self):
        # Other integration tests may create runtime logs while importing DrawBot.
        # Release-hygiene tests always start from a clean publishable tree.
        root = Path(__file__).resolve().parent
        for name in ("logs", "safety-reports", "diagnostics", "crash-dumps"):
            shutil.rmtree(root / name, ignore_errors=True)

    @property
    def root(self):
        return Path(__file__).resolve().parent

    def test_required_release_files_are_present(self):
        report = validate_release_tree(self.root)
        self.assertEqual((), report.missing_required)
        self.assertEqual((), report.forbidden_paths)
        self.assertTrue(report.ok)
        self.assertGreaterEqual(report.files, len(REQUIRED_RELEASE_FILES))

    def test_source_archive_is_clean_and_deterministic_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / f"Image-Draw-Bot-{APP_VERSION}-Source.zip"
            meta = create_source_archive(self.root, zip_path)
            self.assertTrue(zip_path.is_file())
            self.assertEqual(zip_path.name, meta["name"])
            self.assertEqual(64, len(meta["sha256"]))
            with zipfile.ZipFile(zip_path) as archive:
                names = archive.namelist()
            self.assertTrue(names)
            self.assertTrue(all(name.startswith("Image-Draw-Bot/") for name in names))
            self.assertIn("Image-Draw-Bot/README.md", names)
            self.assertIn("Image-Draw-Bot/ReleasePackage.py", names)
            forbidden = [name for name in names if is_forbidden_path(name.replace("Image-Draw-Bot/", "", 1))]
            self.assertEqual([], forbidden)
            self.assertFalse(any("/logs/" in name or "/safety-reports/" in name for name in names))

    def test_manifest_records_artifact_hashes_without_image_or_runtime_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / f"Image-Draw-Bot-{APP_VERSION}-Source.zip"
            manifest_path = Path(tmp) / "manifest.json"
            meta = create_source_archive(self.root, zip_path)
            write_release_manifest(self.root, manifest_path, artifacts=[zip_path])
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(APP_VERSION, payload["app_version"])
            self.assertEqual(meta["sha256"], payload["artifacts"][0]["sha256"])
            self.assertNotIn("screenshots", json.dumps(payload).lower())
            self.assertNotIn("pixels", json.dumps(payload).lower())

    def test_readme_and_release_docs_are_current(self):
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"v{APP_VERSION}", readme)
        self.assertIn("Prepare Paint & draw", readme)
        self.assertIn("python ReleasePackage.py --check", readme)
        self.assertIn("Check updates / install", readme)
        self.assertIn("ReleaseCandidateHardening.py --source-gate", readme)
        notes = (self.root / "RELEASE-NOTES-Step21-Build-Publisher-GitHub-Release.md").read_text(encoding="utf-8")
        self.assertIn("ReleasePackage.py", notes)
        self.assertIn("Not changed", notes)

    def test_github_workflow_uses_release_hygiene_and_artifacts(self):
        workflow = (self.root / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
        self.assertIn("actions/checkout@v7", workflow)
        self.assertIn("actions/setup-python@v7", workflow)
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertIn("python ReleasePackage.py --check", workflow)
        self.assertIn("ReleaseCandidateHardening.py --source-gate", workflow)
        self.assertIn("ImageDrawBot-*-Windows-x64.zip", workflow)
        self.assertIn("ImageDrawBot-*-manifest.json", workflow)
        self.assertIn("--notes-file", workflow)

    def test_step22_roadmap_rolls_forward_after_implementation(self):
        roadmap = (self.root / "ROADMAP-STEP22-PLUS.md").read_text(encoding="utf-8")
        self.assertIn("Step 22 is now implemented", roadmap)
        self.assertIn("Universal Hardware Auto Benchmark", roadmap)
        self.assertIn("Step 23", roadmap)
        self.assertIn("Export / Import Profiles", roadmap)


if __name__ == "__main__":
    unittest.main()
