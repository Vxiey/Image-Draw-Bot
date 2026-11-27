"""Source archives must not contain state left behind by running the app."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from ReleaseCandidateHardening import ReleaseGateError, validate_windows_zip
from ReleasePackage import REQUIRED_RELEASE_FILES, create_source_archive, iter_release_files, validate_release_tree


class SourceArchivePrivacyTests(unittest.TestCase):
    def test_source_packaging_blocks_local_credentials_and_keeps_public_certificates(self):
        private_files = ("docs/.EnV.production", "keys/signing.PFX", "nested/.netrc",
                         "nested/.ssh/config", "nested/local.PEM", "tools/pip.ini")
        # A header crossing the scan chunk boundary must still be recognised.
        private_pem = b"x" * 65529 + b"\n-----BEGIN PRIVATE KEY-----\n"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / "source"
            for name in (*REQUIRED_RELEASE_FILES, *private_files, "docs/ca.pem"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(private_pem if name.endswith(".PEM") else b"fixture")
            files = {path.relative_to(root).as_posix() for path in iter_release_files(root)}
            self.assertTrue(files.isdisjoint(private_files))
            self.assertIn("docs/ca.pem", files)
            report = validate_release_tree(root)
            self.assertEqual(set(report.forbidden_paths),
                             set(private_files) - {"nested/.ssh/config"} | {"nested/.ssh/"})
            previous = Path(temp) / "release.zip"
            previous.write_bytes(b"previous release")
            with self.assertRaises(ValueError):
                create_source_archive(root, previous)
            self.assertEqual(previous.read_bytes(), b"previous release")

    def test_windows_package_gate_rejects_credentials_and_permits_public_ca_bundles(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "release.zip"
            for name, contents, allowed in (
                ("certifi/cacert.pem", b"-----BEGIN CERTIFICATE-----", True),
                ("local/settings/.env", b"fixture", False),
                ("docs/developer.P12", b"fixture", False),
                ("docs/combined.PEM", b"public certificate\n-----BEGIN EC PRIVATE KEY-----", False),
            ):
                with self.subTest(name=name):
                    with zipfile.ZipFile(path, "w") as archive:
                        archive.writestr("ImageDrawBot/ImageDrawBot.exe", b"MZfixture")
                        archive.writestr("ImageDrawBot/_internal/" + name, contents)
                    if allowed:
                        self.assertEqual(validate_windows_zip(path)["integrity"], "PASS")
                    else:
                        with self.assertRaises(ReleaseGateError):
                            validate_windows_zip(path)

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
                "verified-colors-microsoft-paint.json",
                "app-tools-generic.json",
                "paint-tools.json",
                "draw-time-calibration.json",
                "auto-tuner-feedback-generic.json",
                "correction-history-generic.json",
                "layout-fingerprints-v2.json",
                "profiles.json",
                "release-state.json",
                "session-recovery.png",
                ".hypothesis/examples/generated-case",
                ".HYPOTHESIS/constants/generated-constant",
                "tools/.hypothesis/examples/nested-generated-case",
            )
            public_files = (
                "palette-index-maps.json", "tests/fixtures/verified-color-cache-v2.json",
                "resource-scheduler-v2.json", "golden-regression/manifest.json",
                "docs/settings-example.json",
                "tests/fixtures/hypothesis/example.json",
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
