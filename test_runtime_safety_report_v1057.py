import json
import tempfile
import unittest
from pathlib import Path

from CanvasGuard import CanvasGuard, CanvasSafetyStop
from EdgeBehavior import apply_edge_behavior
from RuntimeSafetyReport import RuntimeSafetySession, safe_save
from Version import APP_VERSION, FILE_VERSION


class RuntimeSafetyReportV1057Tests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_counts_actual_edge_decisions(self):
        guard = CanvasGuard.from_area((100, 100, 20, 20), brush_px=3, edge_margin_px=2)
        session = RuntimeSafetySession(dry_run=True, profile_name='Microsoft Paint', edge_behavior='Hard Clip', planned_paths=3)

        raw_drawn = ((105, 110), (114, 110))
        result = apply_edge_behavior(guard, raw_drawn, behavior='Hard Clip')
        self.assertEqual(session.note_edge_result(result, raw_drawn), 'drawn')

        raw_clipped = ((100, 110), (114, 110))
        result = apply_edge_behavior(guard, raw_clipped, behavior='Hard Clip')
        self.assertEqual(session.note_edge_result(result, raw_clipped), 'clipped')

        raw_skipped = ((100, 100), (119, 100))
        result = apply_edge_behavior(guard, raw_skipped, behavior='Hard Clip')
        self.assertEqual(session.note_edge_result(result, raw_skipped), 'skipped')

        counts = session.summary_counts()
        self.assertEqual(counts['drawn'], 1)
        self.assertEqual(counts['clipped'], 1)
        self.assertEqual(counts['skipped'], 1)
        self.assertEqual(counts['processed'], 3)

    def test_edge_follow_block_and_stop_are_separate(self):
        guard = CanvasGuard.from_area((100, 100, 20, 20), brush_px=3, edge_margin_px=2)
        session = RuntimeSafetySession(edge_behavior='Adaptive Clip')
        raw = ((100, 100), (119, 100))
        result = apply_edge_behavior(guard, raw, behavior='Adaptive Clip')
        self.assertEqual(session.note_edge_result(result, raw), 'edge-follow')
        session.note_blocked(CanvasSafetyStop('outside canvas'))
        session.mark_stopped(InterruptedError('user stop'))
        counts = session.summary_counts()
        self.assertEqual(counts['edge_follow'], 1)
        self.assertEqual(counts['blocked'], 1)
        self.assertEqual(counts['stopped'], 1)
        self.assertFalse(session.completed)

    def test_saves_json_and_txt(self):
        session = RuntimeSafetySession(dry_run=True, planned_paths=1)
        session.counts['drawn'] = 1
        session.counts['paths_processed'] = 1
        session.note_fill('better_fill_simulated')
        session.mark_completed()
        with tempfile.TemporaryDirectory() as tmp:
            payload = safe_save(session, Path(tmp))
            json_path = Path(payload['json_path'])
            text_path = Path(payload['text_path'])
            self.assertTrue(json_path.is_file())
            self.assertTrue(text_path.is_file())
            parsed = json.loads(json_path.read_text(encoding='utf-8'))
            self.assertEqual(parsed['counts']['drawn'], 1)
            self.assertTrue(parsed['completed'])
            text = text_path.read_text(encoding='utf-8')
            self.assertIn('Drawn unchanged: 1', text)
            self.assertIn('Better', text.replace('better', 'Better'))


if __name__ == '__main__':
    unittest.main()
