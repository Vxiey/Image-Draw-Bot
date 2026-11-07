"""Keep actual mutable color verification data outside source releases."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import ColorCache
import ProfileStorage
import ReleasePackage


FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "verified-color-cache-v2.json"


class VerifiedColorArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "source"
        for relative in (*ReleasePackage.REQUIRED_RELEASE_FILES, "DrawBot.py"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("public release fixture\n", encoding="utf-8")

    def archive(self):
        self.assertTrue(ReleasePackage.validate_release_tree(self.root).ok)
        destination = self.base / "source.zip"
        ReleasePackage.create_source_archive(self.root, destination)
        return zipfile.ZipFile(destination)

    def test_actual_verified_color_writes_are_excluded_for_paint_and_another_profile(self):
        original = FIXTURE.read_bytes()
        private = {}
        with mock.patch.object(ProfileStorage, "data_dir", return_value=self.root):
            # A source run used to overwrite the shipped seed at this very path.
            paint_path = ColorCache.cache_path("microsoft-paint")
            paint_path.write_bytes(original)
            for profile in ("microsoft-paint", "local-private-target"):
                entry = ColorCache.put_verified(
                    profile, (17, 93, 208), (17, 93, 208), delta_e2000=0,
                    method="native-color-probe", confidence=99,
                    context_fingerprint="local-calibration-context",
                    workflow="local-workflow",
                )
                path = ColorCache.cache_path(profile)
                private[path.name] = path.read_bytes()
                self.assertNotEqual(private[path.name], original)
                self.assertEqual(
                    ColorCache.load_cache(profile, context_fingerprint="local-calibration-context",
                                          workflow="local-workflow")["115DD0"], entry)
        with self.archive() as archive:
            names = set(archive.namelist())
            for name, data in private.items():
                with self.subTest(profile_file=name):
                    self.assertNotIn(f"{ReleasePackage.ROOT_PREFIX}/{name}", names)
                    self.assertEqual((self.root / name).read_bytes(), data)
            self.assertIn(f"{ReleasePackage.ROOT_PREFIX}/DrawBot.py", names)

    def test_case_and_lock_variants_remain_root_only_exclusions(self):
        private = (
            "verified-colors-microsoft-paint.json",
            "VERIFIED-COLORS-CUSTOM-TARGET.JSON",
            "verified-colors-generic.json.lock",
            "VERIFIED-COLORS-CUSTOM-TARGET.JSON.LOCK",
        )
        examples = {f"docs/examples/{name}": b"documented color-cache example\n" for name in private}
        for name in private:
            (self.root / name).write_bytes(b"local verification state\n")
        for name, data in examples.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.assertFalse(ReleasePackage.is_forbidden_path(name))
        with self.archive() as archive:
            names = set(archive.namelist())
            for name in private:
                with self.subTest(private=name):
                    self.assertTrue(ReleasePackage.is_forbidden_path(name))
                    self.assertTrue(ReleasePackage.is_nonfatal_excluded_path(name))
                    self.assertNotIn(f"{ReleasePackage.ROOT_PREFIX}/{name}", names)
            for name, data in examples.items():
                self.assertEqual(archive.read(f"{ReleasePackage.ROOT_PREFIX}/{name}"), data)

    def test_separate_synthetic_seed_is_unchanged_readable_and_shipped(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "5f62e83ab4a0bef941bb34ee4e91b5b3db23c93daf3dcd96c20f67a87dc61930")
        with mock.patch.object(ColorCache, "cache_path", return_value=FIXTURE):
            colors = ColorCache.load_cache("microsoft-paint",
                context_fingerprint="55e856b4dbe34017adbd8fe5", workflow="")
        self.assertEqual(set(colors), {"000000"})
        self.assertEqual(colors["000000"]["requested_rgb"], [0, 0, 0])
        self.assertEqual(colors["000000"]["created_rgb"], [0, 0, 0])
        relative = "tests/fixtures/verified-color-cache-v2.json"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        with self.archive() as archive:
            self.assertEqual(archive.read(f"{ReleasePackage.ROOT_PREFIX}/{relative}"), raw)


if __name__ == "__main__":
    unittest.main()
