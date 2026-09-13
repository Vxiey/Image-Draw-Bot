import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ReleaseState as rs
from Version import APP_VERSION, BUILD_CHANNEL, FILE_VERSION


class ReleaseTests(unittest.TestCase):
    def test_release_metadata(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')
        self.assertEqual(BUILD_CHANNEL,'rc')

    def test_first_run_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'release-state.json'
            with mock.patch.object(rs,'STATE_FILE',path):
                self.assertTrue(rs.should_show_welcome()); rs.mark_welcome_seen(); self.assertFalse(rs.should_show_welcome())
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['last_seen_version'],APP_VERSION)

    def test_remote_bug_report_backend_removed(self):
        root=Path(__file__).resolve().parent
        self.assertFalse((root/'BugReporting.py').exists())
        self.assertFalse((root/'reporting.default.json').exists())
        self.assertFalse((root/'developer'/'report-server-example').exists())

    def test_manifest_is_non_elevated(self):
        text=(Path(__file__).resolve().parent/'ImageDrawBot.manifest').read_text(encoding='utf-8')
        self.assertIn('level="asInvoker"',text); self.assertIn('PerMonitorV2,PerMonitor',text)

    def test_release_builder_verifies_frozen_exe(self):
        text=(Path(__file__).resolve().parent/'build_release.py').read_text(encoding='utf-8')
        self.assertIn('[str(exe), "--self-test"]',text); self.assertIn('SHA256',text)

    def test_github_workflow_builds_and_publishes(self):
        text=(Path(__file__).resolve().parent/'.github'/'workflows'/'build-windows.yml').read_text(encoding='utf-8')
        self.assertIn('actions/checkout@v4',text); self.assertIn('actions/setup-python@v5',text)
        self.assertIn('actions/upload-artifact@v4',text); self.assertIn('python ReleasePackage.py --check',text); self.assertIn('ReleaseCandidateHardening.py --source-gate',text)
        self.assertIn('gh release create',text); self.assertIn('--notes-file',text)
        self.assertIn("- 'Version.py'",text); self.assertIn("- '.github/release-build-trigger'",text)

    def test_runtime_safety_ui_present(self):
        text=(Path(__file__).resolve().parent/'StudioUI.py').read_text(encoding='utf-8')
        self.assertIn('Runtime safety report',text); self.assertIn('Open latest report',text); self.assertIn('ToolTip',text)

if __name__=='__main__': unittest.main()
