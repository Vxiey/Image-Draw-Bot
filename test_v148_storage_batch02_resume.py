import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import RenderResume as resume
import SessionRecovery as recovery
from test_rc14_sequence_resume import seq_plan
from test_smart_recovery_resume_v1079 import plan as batch_plan


class StorageResumeBatch02Tests(unittest.TestCase):
    def test_completed_work_without_prelude_cannot_resume_and_replay_fills(self):
        plan = batch_plan()
        states = [resume.checkpoint_after_batch(plan, 1),
                  resume.checkpoint_before_path(plan, 1, 1, 2,
                                                ordered_items=plan['execution_groups'][0])]
        sequence = seq_plan()
        states.append(resume.checkpoint_sequence_progress(sequence,
                      {resume.sequence_entry_key(sequence['execution_sequence'][0]): 1}))
        for state in states:
            with self.subTest(state=state.get('sequence_level', state.get('path_level'))):
                state['prelude_complete'] = False
                self.assertIsNone(resume.validate_progress(state))
                self.assertFalse(resume.resolve_resume(sequence if state.get('sequence_level') else plan,
                                                       state)['compatible'])
        self.assertIsNotNone(resume.validate_progress(resume.new_progress(plan)))

    def test_checkpoint_writers_reject_invalid_completion_instead_of_clamping(self):
        plan = batch_plan()
        for invalid in (-1, 100, True, 1.5, '1'):
            with self.subTest(count=invalid):
                with self.assertRaises(ValueError):
                    resume.checkpoint_after_batch(plan, invalid)
        with self.assertRaises(ValueError):
            resume.checkpoint_after_batch(plan, 1, prelude_complete=False)
        with self.assertRaises(ValueError):
            resume.checkpoint_after_path(plan, 1, -1, 2)

    def test_sequence_checkpoint_hashes_context_once_and_streams_its_flags(self):
        plan = seq_plan()
        count = {resume.sequence_entry_key(plan['execution_sequence'][0]): 1}
        with patch.object(resume, 'plan_fingerprint', wraps=resume.plan_fingerprint) as fingerprint:
            state = resume.checkpoint_sequence_progress(plan, count)
        self.assertEqual(fingerprint.call_count, 1)
        self.assertTrue(resume.resolve_resume(plan, state)['compatible'])
        flags = (index % 3 == 0 for index in range(1000))
        encoded = resume._encode_bits(flags)
        self.assertEqual(resume._decode_bits(encoded, 1000), [index % 3 == 0 for index in range(1000)])

    def test_image_hash_uses_bounded_rgba_strips_and_detects_the_last_pixel(self):
        plan = batch_plan()
        plan['image'] = Image.new('RGB', (1300, 1000), 'white')
        original = Image.Image.tobytes
        sizes = []
        def record_bytes(image, *args, **kwargs):
            sizes.append(image.width * image.height * len(image.getbands()))
            return original(image, *args, **kwargs)
        with patch.object(Image.Image, 'tobytes', record_bytes):
            before = resume.plan_fingerprint(plan)
        self.assertGreater(len(sizes), 1)
        self.assertLessEqual(max(sizes), 1024 * 1024)
        plan['image'].putpixel((1299, 999), (1, 2, 3))
        self.assertNotEqual(resume.plan_fingerprint(plan), before)

    def test_unreadable_source_cannot_be_replaced_with_a_size_only_fingerprint(self):
        plan = batch_plan()
        with patch.object(Image.Image, 'crop', side_effect=OSError('source unavailable')):
            with self.assertRaises(OSError):
                resume.checkpoint_after_batch(plan, 1)

    def test_hash_failure_closes_owned_strips_without_closing_the_source(self):
        plan = batch_plan()
        source = plan['image']
        owned = []
        original_crop = Image.Image.crop
        original_convert = Image.Image.convert
        def crop(image, *args, **kwargs):
            result = original_crop(image, *args, **kwargs)
            owned.append(result)
            return result
        def convert(image, *args, **kwargs):
            result = original_convert(image, *args, **kwargs)
            owned.append(result)
            return result
        try:
            with patch.object(Image.Image, 'crop', crop), \
                 patch.object(Image.Image, 'convert', convert), \
                 patch.object(Image.Image, 'tobytes', side_effect=OSError('injected pixel read failure')):
                with self.assertRaises(OSError):
                    resume.plan_fingerprint(plan)
            self.assertEqual(len(owned), 2)
            for value in owned:
                with self.assertRaises(ValueError):
                    value.getpixel((0, 0))
            self.assertIsNotNone(source.getpixel((0, 0)))
        finally:
            for value in owned:
                value.close()

    def test_ambiguous_recovery_json_is_not_restored(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'recovery.json'
            path.write_text('{"schema":3,"profile":"Paint","profile":"other","options":{}}')
            with patch.object(recovery, 'STATE_FILE', path):
                self.assertIsNone(recovery.load_snapshot())

    def test_clear_render_failure_is_reported_and_preserves_existing_progress(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / 'resume.json'
            path.write_text('old progress')
            original = Path.unlink
            def fail_selected(target, *args, **kwargs):
                if target == path:
                    raise PermissionError('progress is locked')
                return original(target, *args, **kwargs)
            with patch.object(recovery, 'RECOVERY_DIR', root), patch.object(recovery, 'RENDER_FILE', path), \
                 patch.object(Path, 'unlink', fail_selected):
                with self.assertRaises(PermissionError):
                    recovery.clear_render_progress()
            self.assertEqual(path.read_text(), 'old progress')

    def test_recovery_area_must_have_positive_extent(self):
        self.assertIsNone(recovery._clean_area([[5, 5], [5, 100]]))
        self.assertIsNone(recovery._clean_area([[5, 5], [100, 5]]))
        self.assertEqual(recovery._clean_area([[100, 90], [-10, -20]]), [[100, 90], [-10, -20]])


if __name__ == '__main__':
    unittest.main()
