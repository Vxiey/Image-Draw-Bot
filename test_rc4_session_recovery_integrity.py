import base64
import json
import multiprocessing
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import RenderResume as RR
import SessionRecovery as SR


def _concurrent_snapshot(directory, color, barrier, queue):
    """Separate app processes exercise the native interprocess save lock."""
    root = Path(directory)
    SR.RECOVERY_DIR = root
    SR.STATE_FILE = root / 'session-recovery.json'
    SR.IMAGE_FILE = root / 'last-image.png'
    SR.RENDER_FILE = root / 'render-resume.json'
    try:
        barrier.wait(timeout=15)
        for _ in range(3):
            SR.save_snapshot(profile=color, options={}, image=Image.new('RGBA', (8, 7), color))
        queue.put(None)
    except BaseException as error:
        queue.put(repr(error))


class SessionRecoveryIntegrityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for key, value in {
            'RECOVERY_DIR': self.root, 'STATE_FILE': self.root / 'session-recovery.json',
            'IMAGE_FILE': self.root / 'last-image.png', 'RENDER_FILE': self.root / 'render-resume.json',
        }.items():
            mock = patch.object(SR, key, value)
            mock.start()
            self.addCleanup(mock.stop)

    def raw_state(self, **changes):
        state = dict(schema=2, profile='Microsoft Paint', options={}, has_image=False)
        state.update(changes)
        SR.STATE_FILE.write_text(json.dumps(state), encoding='utf-8')
        return state

    def test_finite_recovery_options(self):
        SR.save_snapshot(profile='Microsoft Paint', options={
            'contrast': float('nan'), 'max_seconds': float('inf'), 'brush_px': -float('inf'), 'skip_white': True,
        })
        self.assertEqual(SR.load_snapshot()['options'], {'skip_white': True})
        self.raw_state(options={'contrast': float('nan')})
        self.assertIsNone(SR.load_snapshot())

    def test_schema_and_image_flags_are_not_coerced(self):
        for schema in (True, False, 1.0, '2'):
            self.raw_state(schema=schema)
            self.assertIsNone(SR.load_snapshot())
        for flag in ('false', 1, [], None):
            self.raw_state(has_image=flag)
            self.assertIsNone(SR.load_snapshot())
        self.raw_state(schema=1)
        self.assertFalse(SR.load_snapshot()['has_image'])

    def test_json_size_utf8_depth_and_render_load_fail_closed(self):
        for malformed in (b'\xff', b'[' * 2000 + b'0' + b']' * 2000, b'{}' + b' ' * SR.MAX_STATE_BYTES):
            SR.STATE_FILE.write_bytes(malformed)
            self.assertIsNone(SR.load_snapshot())
        self.raw_state(unknown=[[[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]])
        self.assertIsNone(SR.load_snapshot())
        self.raw_state()
        with patch.object(SR, 'MAX_RENDER_BYTES', 64):
            SR.RENDER_FILE.write_bytes(b' ' * 65)
            self.assertIsNone(SR.load_snapshot()['render_resume'])

    def test_saved_area_roundtrip_and_invalid_coordinates(self):
        for invalid in (
            [[float('inf'), 2], [3, 4]], [[True, 2], [3, 4]], [[1, 2, 3], [4, 5]],
            [[1, 2], [200001, 4]], [['1', 2], [3, 4]], [[1.5, 2], [3, 4]],
        ):
            SR.save_snapshot(profile='Paint', options={}, saved_area=invalid)
            self.assertIsNone(SR.load_snapshot()['saved_area'])
        self.raw_state(saved_area=[[10**100, 2], [3, 4]])
        self.assertIsNone(SR.load_snapshot()['saved_area'])
        SR.save_snapshot(profile='Paint', options={}, saved_area=[(-100, 2), (3, 4)])
        self.assertEqual(SR.load_snapshot()['saved_area'], [[-100, 2], [3, 4]])

    def test_target_hint_is_flat_bounded_non_authoritative_metadata(self):
        loop = []; loop.append(loop)
        SR.save_snapshot(profile='Paint', options={}, target_lock={
            'version': 1, 'profile': 'p' * 500, 'paint_tool': 'Pencil', 'target_dpi': float('inf'),
            'drawing_area_rel': loop, 'image_size': [8, 6], 'palette_required': True, 'target_handle': 99,
        })
        hint = SR.load_snapshot()['target_lock_hint']
        self.assertEqual(len(hint['profile']), 160)
        self.assertEqual(hint['image_size'], [8, 6])
        self.assertTrue(hint['palette_required'])
        self.assertNotIn('target_dpi', hint)
        self.assertNotIn('drawing_area_rel', hint)
        self.assertNotIn('target_handle', hint)

    def test_failed_state_publish_keeps_old_image_and_render_checkpoint(self):
        SR.save_snapshot(profile='red', options={}, image=Image.new('RGBA', (8, 6), 'red'))
        old = SR.STATE_FILE.read_bytes()
        digest = SR.load_snapshot()['image_sha256']
        SR.RENDER_FILE.write_text('old progress', encoding='utf-8')
        with patch.object(SR, 'atomic_write_text', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                SR.save_snapshot(profile='blue', options={}, image=Image.new('RGBA', (8, 6), 'blue'), clear_render_resume=True)
        self.assertEqual(SR.STATE_FILE.read_bytes(), old)
        self.assertEqual(SR.RENDER_FILE.read_text(), 'old progress')
        self.assertEqual(SR.load_cached_image(expected_sha256=digest).getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(len(list(self.root.glob('last-image-*.png'))), 1)
        self.assertEqual(list(self.root.glob('.recovery-image-*.tmp')), [])

    def test_image_digest_detects_tampering_and_previous_generation_is_retained(self):
        orphan = self.root / '.recovery-image-orphan.png.tmp'
        orphan.write_bytes(b'interrupted image encoding')
        digests = []
        for color in ('red', 'blue', 'green'):
            SR.save_snapshot(profile=color, options={}, image=Image.new('RGBA', (8, 6), color))
            digests.append(SR.load_snapshot()['image_sha256'])
        self.assertEqual(len(list(self.root.glob('last-image-*.png'))), 2)
        self.assertFalse(orphan.exists())
        self.assertIsNone(SR.load_cached_image(expected_sha256=digests[0]))
        self.assertIsNotNone(SR.load_cached_image(expected_sha256=digests[1]))
        SR._image_path(digests[-1]).write_bytes(SR._image_path(digests[1]).read_bytes())
        self.assertIsNone(SR.load_cached_image(expected_sha256=digests[-1]))
        self.assertIsNone(SR.load_cached_image(expected_sha256='../last-image.png'))

    def test_legacy_image_migrates_without_losing_source_or_restoring_arming(self):
        Image.new('RGBA', (7, 5), 'red').save(SR.IMAGE_FILE)
        self.raw_state(schema=1, has_image=True)
        self.assertEqual(SR.load_cached_image().size, (7, 5))
        SR.save_snapshot(profile='Paint', options={})
        state = SR.load_snapshot()
        self.assertIsNotNone(state['image_sha256'])
        self.assertEqual(SR.load_cached_image(expected_sha256=state['image_sha256']).size, (7, 5))
        self.assertTrue(all(value is False for value in json.loads(SR.STATE_FILE.read_text())['safety'].values()))
        SR.clear_snapshot()
        self.assertEqual(list(self.root.glob('*.png')), [])

    def test_cached_image_limits_apply_before_rgba_conversion(self):
        Image.new('RGB', (20, 10), 'red').save(SR.IMAGE_FILE)
        self.raw_state(has_image=True)
        with patch.object(SR, 'MAX_CACHED_IMAGE_PIXELS', 100), patch.object(Image.Image, 'convert') as convert:
            self.assertIsNone(SR.load_cached_image())
            convert.assert_not_called()
        with patch.object(Image, 'MAX_IMAGE_PIXELS', 150):
            self.assertIsNone(SR.load_cached_image())
        with patch.object(SR, 'MAX_CACHED_IMAGE_BYTES', 1):
            self.assertIsNone(SR.load_cached_image())

    def test_selected_legacy_snapshot_cannot_load_newly_published_image(self):
        Image.new('RGBA', (7, 5), 'red').save(SR.IMAGE_FILE)
        self.raw_state(schema=2, has_image=True, profile='legacy red')
        selected = SR.load_snapshot()
        SR.save_snapshot(profile='new blue', options={}, image=Image.new('RGBA', (7, 5), 'blue'))
        restored = SR.load_cached_image(expected_sha256=selected['image_sha256'])
        self.assertEqual(restored.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(SR.load_cached_image().getpixel((0, 0)), (0, 0, 255, 255))

    def test_explicit_clear_reports_locked_hash_image_and_staging_file(self):
        for staging in (False, True):
            with self.subTest(staging=staging):
                SR.save_snapshot(profile='red', options={}, image=Image.new('RGBA', (7, 5), 'red'))
                locked = (self.root / '.recovery-image-interrupted.png.tmp') if staging else SR._image_path(SR.load_snapshot()['image_sha256'])
                if staging:
                    locked.write_bytes(b'partial private image')
                real_unlink = Path.unlink
                def fail_locked(path, *args, **kwargs):
                    if path == locked:
                        raise PermissionError('file is locked')
                    return real_unlink(path, *args, **kwargs)
                with patch.object(Path, 'unlink', fail_locked):
                    with self.assertRaisesRegex(OSError, 'could not be completely removed'):
                        SR.clear_snapshot()
                self.assertTrue(locked.exists())
                SR.clear_snapshot()
                self.assertFalse(locked.exists())
        SR.save_snapshot(profile='red', options={}, image=Image.new('RGBA', (7, 5), 'red'))
        with patch.object(SR.os, 'scandir', side_effect=PermissionError('directory cannot be listed')):
            with self.assertRaisesRegex(OSError, 'Could not enumerate'):
                SR.clear_snapshot()
        SR.clear_snapshot()

    def test_recent_snapshot_settings_survive_and_authorization_does_not(self):
        options = dict(resource_scheduler='Conservative', detail_zoom='High', visual_verification='Strict',
                       color_fidelity='Faithful', profile_engine='Auto', edge_behavior='Safe',
                       sketch_detail='High', read_gartic_timer=True, render_preset='Manual')
        SR.save_snapshot(profile='Paint', options=dict(options, full_draw_armed=True, preview_mode='Auto full'))
        self.assertEqual(SR.load_snapshot()['options'], options)

    def test_clear_render_progress_after_successful_publication(self):
        SR.RENDER_FILE.write_text('progress', encoding='utf-8')
        SR.save_snapshot(profile='Paint', options={}, clear_render_resume=True)
        self.assertTrue(SR.STATE_FILE.exists())
        self.assertFalse(SR.RENDER_FILE.exists())

    def test_simultaneous_process_saves_publish_matching_bounded_images(self):
        context = multiprocessing.get_context('spawn')
        barrier, queue = context.Barrier(2), context.Queue()
        processes = [context.Process(target=_concurrent_snapshot, args=(str(self.root), color, barrier, queue))
                     for color in ('red', 'blue')]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=25)
                self.assertFalse(process.is_alive(), 'snapshot process did not finish')
                self.assertEqual(process.exitcode, 0)
            self.assertEqual([queue.get(timeout=3) for _ in processes], [None, None])
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate(); process.join(timeout=5)
            queue.close(); queue.join_thread()
        state = SR.load_snapshot()
        expected = {'red': (255, 0, 0, 255), 'blue': (0, 0, 255, 255)}[state['profile']]
        self.assertEqual(SR.load_cached_image(expected_sha256=state['image_sha256']).getpixel((0, 0)), expected)
        self.assertLessEqual(len(list(self.root.glob('last-image-*.png'))), 2)


class RenderResumeIntegrityTests(unittest.TestCase):
    def progress(self, total=4):
        return dict(schema=3, plan_fingerprint='0' * 64, total_colors=1, completed_count=0,
                    completed_keys=[], prelude_complete=True, path_level=False, sequence_level=True,
                    sequence_total=total, sequence_completed_count=0, sequence_catalog_fingerprint='1' * 64,
                    sequence_completed_bits=base64.b64encode(bytes((total + 7) // 8)).decode('ascii'))

    def test_first_palette_color_is_not_replaced_by_missing_color_sentinel(self):
        plan = {'colors': [(0, 0, 0)], 'groups': [[(0, 0, 1, 1)]], 'count': 1,
                'execution_sequence': [{'color_index': 0, 'path': [[0, 0], [1, 1]]}]}
        row = plan['execution_sequence'][0]
        state = RR.checkpoint_sequence_progress(plan, {RR.sequence_entry_key(row): 1}, last_entry=row)
        self.assertEqual(RR.validate_progress(state)['sequence_last_color_index'], 0)
        self.assertEqual(RR.resolve_resume(plan, state)['sequence_last_color_index'], 0)

    def test_conflicting_resume_modes_are_rejected(self):
        self.assertIsNone(RR.validate_progress(dict(self.progress(), path_level=True)))

    def test_validation_memory_stays_proportional_to_packed_bytes(self):
        state = self.progress(4_000_000)
        tracemalloc.start()
        try:
            self.assertIsNotNone(RR.validate_progress(state))
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 8 * 1024 * 1024)
        self.assertIsNone(RR.validate_progress(dict(state, sequence_total=10**12)))

    def test_bit_count_padding_and_non_string_input_are_validated(self):
        state = self.progress(4)
        self.assertIsNone(RR.validate_progress(dict(state, sequence_completed_bits='gA==')))
        self.assertIsNone(RR.validate_progress(dict(state, sequence_completed_bits='AQ==')))
        self.assertIsNone(RR.validate_progress(dict(state, sequence_completed_bits=1234)))
        state.update(sequence_completed_bits='AQ==', sequence_completed_count=1)
        self.assertEqual(RR.validate_progress(state)['sequence_completed_count'], 1)


if __name__ == '__main__':
    unittest.main()
