from __future__ import annotations

from pathlib import Path

OLD = "1.0.146-rc1"
NEW = "1.0.146-rc2"
FILE_VERSION = "1.0.146"
ROOT = Path(__file__).resolve().parents[2]


def replace(path: Path, old: str, new: str, *, required: bool = False) -> bool:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if required:
            raise RuntimeError(f"Expected {old!r} in {path}")
        return False
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


def prepend_history(path: Path, section: str) -> None:
    text = path.read_text(encoding="utf-8")
    marker = f"# Image Draw Bot v{NEW}"
    if marker in text:
        return
    path.write_text(section.rstrip() + "\n\n" + text.lstrip(), encoding="utf-8")


def main() -> None:
    version = ROOT / "Version.py"
    replace(version, f"APP_VERSION = '{OLD}'", f"APP_VERSION = '{NEW}'", required=True)
    version_text = version.read_text(encoding="utf-8")
    if f"FILE_VERSION = '{FILE_VERSION}'" not in version_text:
        raise RuntimeError("FILE_VERSION must remain 1.0.146 for the 1.0.146 RC line")

    installer = ROOT / "installer" / "ImageDrawBot.iss"
    replace(installer, f'#define MyAppVersion "{OLD}"', f'#define MyAppVersion "{NEW}"', required=True)
    # rc1 accidentally kept the previous Windows numeric file-version resource.
    replace(installer, "VersionInfoVersion=1.0.145.0", "VersionInfoVersion=1.0.146.0")

    # Public current-release surfaces. Historical release notes/history remain unchanged.
    replace(ROOT / "README.md", OLD, NEW, required=True)
    index = ROOT / "README-INDEX.md"
    index_text = index.read_text(encoding="utf-8")
    import re
    index_text = re.sub(
        r"- \[Current release: v[^\]]+\]\(RELEASE-NOTES-v[^\)]+\.md\)",
        f"- [Current release: v{NEW}](RELEASE-NOTES-v{NEW}.md)",
        index_text,
        count=1,
    )
    index.write_text(index_text, encoding="utf-8")

    # Active regressions intentionally assert the current application version. Keep all of
    # them synchronized atomically; do not rewrite historical scripts/release documents.
    updated_tests = 0
    for path in sorted(ROOT.rglob("test_*.py")):
        if ".git" in path.parts or ".github" in path.parts:
            continue
        if replace(path, OLD, NEW):
            updated_tests += 1

    notes = f"""# Image Draw Bot v{NEW} — Background Removal & Recognition-First Extra Fast

- Promote the validated post-rc1 fixes into the next 1.0.146 release candidate.
- Replace the old single-reference Remove BG flood fill with fully local classical edge-aware segmentation: adaptive border-colour clusters, chromatic edge barriers, conservative region growth, connected-component safety and a bounded contour matte.
- Keep Remove BG completely non-AI: no neural model, cloud service, OpenCV runtime dependency or generated replacement image.
- Make Extra Fast target-profile aware instead of applying one generic scanline-heavy policy to Paint, Gartic and Skribbl targets.
- Bind Extra Fast to the deterministic Drawing Style profile so Pixel Art preserves exact pixel regions, Line Art prioritizes connected contours, flat art prioritizes large colour regions, and Portrait/Photo prioritize recognisable structure before texture.
- Keep Gartic's verified multi-brush regional planning and safe Fill path while exposing recognition-first strategy metadata in preview/session diagnostics.
- Keep Estimated Draw Time tied to the real final execution sequence: mouse travel, strokes, colour changes, brush changes, Fill, tool changes and verification are costed instead of applying a cosmetic speed multiplier.
- Synchronize Windows installer metadata to the 1.0.146 RC line (`VersionInfoVersion=1.0.146.0`).
- Preserve CanvasGuard, calibration, cancellation, profile isolation, CPU fallback and no-CUDA operation.

Release publication remains gated by source-package hygiene, full regression tests, Image Draw Bot self-test, Windows packaging validation and the silent install/self-test/uninstall round trip.
"""
    (ROOT / f"RELEASE-NOTES-v{NEW}.md").write_text(notes, encoding="utf-8")

    history = f"""# Image Draw Bot v{NEW} — Background Removal & Recognition-First Extra Fast

- Promote the classical non-AI background-removal hardening merged after rc1.
- Promote target-profile + Drawing Style aware Extra Fast planning so recognition and region structure win over generic line soup.
- Preserve the final-execution-sequence ETA model and measured local timing calibration.
- Correct the installer numeric version resource to 1.0.146.0 and synchronize active version regressions.
- Keep the complete Windows release gate authoritative before publication.
"""
    prepend_history(ROOT / "VERSION-HISTORY.md", history)
    prepend_history(ROOT / "docs" / "VERSION-HISTORY.md", history)

    focused = f'''import unittest\nfrom pathlib import Path\n\nfrom Version import APP_VERSION, FILE_VERSION\n\n\nclass V10146Rc2ReleaseRollupTests(unittest.TestCase):\n    def test_release_version(self):\n        self.assertEqual(APP_VERSION, "{NEW}")\n        self.assertEqual(FILE_VERSION, "{FILE_VERSION}")\n\n    def test_installer_metadata_matches_rc_line(self):\n        text=Path("installer/ImageDrawBot.iss").read_text(encoding="utf-8")\n        self.assertIn('#define MyAppVersion "{NEW}"', text)\n        self.assertIn('VersionInfoVersion=1.0.146.0', text)\n\n    def test_release_notes_and_public_index(self):\n        self.assertTrue(Path("RELEASE-NOTES-v{NEW}.md").is_file())\n        readme=Path("README.md").read_text(encoding="utf-8")\n        index=Path("README-INDEX.md").read_text(encoding="utf-8")\n        self.assertIn("v{NEW}", readme)\n        self.assertIn("Current release: v{NEW}", index)\n\n    def test_rc2_rolls_up_both_validated_fixes(self):\n        self.assertTrue(Path("BackgroundRemoval.py").is_file())\n        self.assertTrue(Path("ExtraFastProfilePolicy.py").is_file())\n        auto=Path("AutoDrawing.py").read_text(encoding="utf-8")\n        self.assertIn("apply_extra_fast_profile_policy", auto)\n\n\nif __name__ == "__main__":\n    unittest.main()\n'''
    (ROOT / "test_v10146_rc2_release_rollup.py").write_text(focused, encoding="utf-8")

    # Make stale current-version assertions impossible to slip into the RC commit.
    stale=[]
    for path in sorted(ROOT.rglob("test_*.py")):
        if ".git" in path.parts or ".github" in path.parts:
            continue
        if OLD in path.read_text(encoding="utf-8", errors="ignore"):
            stale.append(str(path.relative_to(ROOT)))
    if stale:
        raise RuntimeError("Stale rc1 version assertions: " + ", ".join(stale))

    print(f"Prepared {NEW}; synchronized {updated_tests} existing version-assertion test files.")

    # One-shot branch automation: do not merge temporary release plumbing into main.
    for helper in (
        ROOT / ".github" / "prepare-v10146-rc2-trigger",
        ROOT / ".github" / "workflows" / "prepare-v10146-rc2.yml",
        ROOT / ".github" / "scripts" / "prepare_v10146_rc2.py",
    ):
        try:
            helper.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
