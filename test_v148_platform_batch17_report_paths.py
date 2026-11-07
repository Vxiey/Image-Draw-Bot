"""Stored report metadata cannot choose the file opened by the application."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import DrawBot
import RuntimeSafetyReport as reports
from test_v148_application_batch04_settings import Value


class SafetyReportOpenPathsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.directory = self.root / 'reports'
        self.directory.mkdir()
        self.stack.enter_context(patch.object(reports, 'REPORT_DIR', self.directory))
        # No external file is opened. Exercise the actual controller through
        # its final platform boundary on every supported test platform.
        self.open_file = self.stack.enter_context(patch('os.startfile', create=True))
        self.app = SimpleNamespace(status=Value('Ready.'))
        self.path = self.directory / 'ImageDrawBot-Safety-current-drawing.json'

    def write_report(self, **extra):
        payload = reports.RuntimeSafetySession(profile_name='Microsoft Paint').as_dict()
        payload.update(completed=True, counts={'drawn': 7, 'clipped': 2})
        payload.update(extra)
        self.path.write_text(json.dumps(payload), encoding='utf-8')
        return self.path.read_bytes()

    def open_current(self):
        self.open_file.reset_mock()
        DrawBot.DrawBotApp.open_latest_safety_report(self.app)

    def test_missing_sibling_text_ignores_embedded_destinations_at_actual_open_boundary(self):
        for suffix in ('.exe', '.lnk', '.txt'):
            with self.subTest(suffix=suffix):
                outside = self.root / ('external-target' + suffix)
                outside.write_bytes(b'Harmless test marker; never launched.')
                original = self.write_report(text_path=str(outside), json_path=str(outside))
                self.open_current()
                self.open_file.assert_called_once_with(self.path)
                loaded = reports.latest_report()
                self.assertEqual(loaded['json_path'], str(self.path))
                self.assertNotIn('text_path', loaded)
                self.assertEqual(self.path.read_bytes(), original)

    def test_real_adjacent_text_remains_the_preferred_report(self):
        outside = self.root / 'external-target.exe'
        outside.write_bytes(b'Harmless marker.')
        self.write_report(text_path=str(outside), json_path=str(outside))
        sibling = self.path.with_suffix('.txt')
        sibling.write_text('The actual adjacent safety report.', encoding='utf-8')
        self.open_current()
        self.open_file.assert_called_once_with(sibling)
        loaded = reports.latest_report()
        self.assertEqual((loaded['json_path'], loaded['text_path']),
                         (str(self.path), str(sibling)))
        self.assertIn('Drawn 7', reports.compact_summary(loaded))

    def test_untrusted_path_types_and_directory_sibling_cannot_break_json_fallback(self):
        self.path.with_suffix('.txt').mkdir()
        for value in (True, 42, ['elsewhere.txt'], {'file': 'elsewhere.txt'}):
            with self.subTest(value=value):
                self.write_report(text_path=value)
                self.open_current()
                self.open_file.assert_called_once_with(self.path)
                self.assertNotIn('text_path', reports.latest_report())

    def test_genuine_saved_session_retains_its_local_pair_and_usable_summary(self):
        session = reports.RuntimeSafetySession(profile_name='Microsoft Paint')
        session.mark_completed()
        saved = session.save(self.directory)
        self.open_current()
        self.open_file.assert_called_once_with(Path(saved['text_path']))
        loaded = reports.latest_report()
        self.assertEqual((loaded['json_path'], loaded['text_path']),
                         (saved['json_path'], saved['text_path']))
        self.assertEqual(reports.compact_summary(loaded), reports.compact_summary(saved))


if __name__ == '__main__':
    unittest.main()
