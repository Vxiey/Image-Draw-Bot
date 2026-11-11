"""An unreadable required recovery image cannot restore unrelated settings.

The controller, storage reader, Pillow decoder, worker, queue and Tcl variables
are real. Corrupt bytes are truncated existing repository PNGs; the only reader
interleavings control a disappearing file and a late Stop.
"""
import hashlib
import json
import unittest
from unittest.mock import patch

from DrawBot import DrawBotApp
import SessionRecovery as recovery
import test_v148_application_batch37_recovery_dialog as fixtures


class RequiredRecoveryImageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecoveryDialogIdentityTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.app = self.fixture.app
        self.app.saved_area = [(2, 3), (42, 43)]
        self.app.corners = [(5, 6), (45, 46)]
        self.previous = {
            'image': self.app.original,
            'pixels': self.fixture.pixels(self.app.original),
            'quality': self.app.quality.get(),
            'file_label': self.app.file_label.get(),
            'preview_mode': self.app.preview_mode.get(),
            'saved_area': list(self.app.saved_area),
            'corners': list(self.app.corners),
            'resume': self.app.pending_render_resume,
        }
        self.image_path = recovery._image_path(self.fixture.offered_state['image_sha256'])
        self.valid_png = self.image_path.read_bytes()

    def restore(self):
        self.fixture.offer(True)
        worker = self.app.worker
        self.assertIsNotNone(worker)
        worker.join(5)
        self.assertFalse(worker.is_alive(), 'The actual recovery worker did not finish.')
        published = []
        while not self.app.events.empty():
            kind, value = self.app.events.get_nowait()
            published.append(kind)
            if kind == 'recovery_loaded' and value[1] is not None:
                self.fixture.images.append(value[1])
            DrawBotApp._handle_event(self.app, kind, value)
        self.assertIn('done', published)
        self.assertIsNone(self.app.worker)
        self.assertIsNone(self.app.activity)
        return published

    def assert_current_work(self):
        self.assertIs(self.app.original, self.previous['image'])
        self.assertEqual(self.fixture.pixels(self.app.original), self.previous['pixels'])
        for name in ('quality', 'file_label', 'preview_mode'):
            self.assertEqual(getattr(self.app, name).get(), self.previous[name], name)
        for name in ('saved_area', 'corners'):
            self.assertEqual(getattr(self.app, name), self.previous[name], name)
        self.assertIs(self.app.pending_render_resume, self.previous['resume'])
        self.assertIsNone(getattr(self.app, 'recovery_loaded_pending', None))

    def assert_failed_restore(self, published, expected_files):
        self.assertNotIn('recovery_loaded', published)
        self.assertIn('terminal_status', published)
        self.assert_current_work()
        self.assertIn('recovery image', self.app.status.get().lower())
        self.assertIn('current work was kept', self.app.status.get().lower())
        self.assertEqual(self.fixture.payloads(), expected_files)

    def test_hash_mismatch_keeps_current_image_settings_and_checkpoint(self):
        self.image_path.write_bytes((fixtures.ASSETS / 'paint-tools-reference.png').read_bytes())
        self.assertTrue(recovery.load_snapshot()['has_image'])
        before = self.fixture.payloads()
        self.assert_failed_restore(self.restore(), before)

    def test_matching_digest_with_undecodable_png_keeps_current_work(self):
        # Keep the PNG signature but remove the existing image's chunk data.
        truncated = self.valid_png[:16]
        digest = hashlib.sha256(truncated).hexdigest()
        recovery._image_path(digest).write_bytes(truncated)
        state = json.loads(recovery.STATE_FILE.read_text(encoding='utf-8'))
        state['image_sha256'] = digest
        recovery.STATE_FILE.write_text(json.dumps(state), encoding='utf-8')
        self.assertTrue(recovery.load_snapshot()['has_image'])
        self.assertEqual(hashlib.sha256(recovery._image_path(digest).read_bytes()).hexdigest(), digest)
        before = self.fixture.payloads()
        self.assert_failed_restore(self.restore(), before)

    def test_file_disappearing_after_accepted_dialog_keeps_current_work(self):
        actual_load = recovery.load_cached_image
        after_removal = {}

        def disappear(*args, **kwargs):
            self.image_path.unlink()
            after_removal.update(self.fixture.payloads())
            return actual_load(*args, **kwargs)

        with patch.object(recovery, 'load_cached_image', side_effect=disappear) as reader:
            published = self.restore()
        reader.assert_called_once()
        self.assert_failed_restore(published, after_removal)

    def test_reader_byte_budget_rejection_keeps_current_work(self):
        before = self.fixture.payloads()
        with patch.object(recovery, 'MAX_CACHED_IMAGE_BYTES', len(self.valid_png) - 1):
            published = self.restore()
        self.assert_failed_restore(published, before)

    def test_required_modern_image_missing_before_offer_keeps_current_work(self):
        self.image_path.unlink()
        self.assertFalse(recovery.load_snapshot()['has_image'])
        before = self.fixture.payloads()
        self.assert_failed_restore(self.restore(), before)

    def test_required_legacy_image_missing_before_offer_keeps_current_work(self):
        state = json.loads(recovery.STATE_FILE.read_text(encoding='utf-8'))
        state['schema'] = 2
        state.pop('image_sha256')
        recovery.STATE_FILE.write_text(json.dumps(state), encoding='utf-8')
        self.assertFalse(recovery.IMAGE_FILE.exists())
        self.assertFalse(recovery.load_snapshot()['has_image'])
        before = self.fixture.payloads()
        self.assert_failed_restore(self.restore(), before)

    def test_invalid_modern_reference_cannot_borrow_an_unrelated_legacy_image(self):
        state = json.loads(recovery.STATE_FILE.read_text(encoding='utf-8'))
        state['image_sha256'] = 'invalid-digest'
        recovery.STATE_FILE.write_text(json.dumps(state), encoding='utf-8')
        recovery.IMAGE_FILE.write_bytes((fixtures.ASSETS / 'paint-tools-reference.png').read_bytes())
        self.assertFalse(recovery.load_snapshot()['has_image'])
        before = self.fixture.payloads()
        with patch.object(recovery, 'load_cached_image', wraps=recovery.load_cached_image) as reader:
            published = self.restore()
        reader.assert_not_called()
        self.assert_failed_restore(published, before)

    def test_stop_after_failed_read_wins_without_a_failure_publication(self):
        self.image_path.write_bytes(self.valid_png[:16])
        before = self.fixture.payloads()
        actual_load = recovery.load_cached_image

        def stop_after_read(*args, **kwargs):
            result = actual_load(*args, **kwargs)
            self.assertIsNone(result)
            self.app.stop.set()
            return result

        with patch.object(recovery, 'load_cached_image', side_effect=stop_after_read) as reader:
            published = self.restore()
        reader.assert_called_once()
        self.assertNotIn('recovery_loaded', published)
        self.assertNotIn('terminal_status', published)
        self.assert_current_work()
        self.assertEqual(self.app.status.get(), 'Stopped.')
        self.assertEqual(self.fixture.payloads(), before)

    def test_valid_retry_restores_image_and_settings_disarmed(self):
        self.image_path.write_bytes(self.valid_png[:16])
        failed_files = self.fixture.payloads()
        self.assert_failed_restore(self.restore(), failed_files)
        self.image_path.write_bytes(self.valid_png)
        before = self.fixture.payloads()
        published = self.restore()
        self.assertIn('recovery_loaded', published)
        self.assertNotIn('terminal_status', published)
        self.assertEqual(self.fixture.pixels(self.app.original), self.fixture.pixels(self.fixture.offered_source))
        self.assertEqual(self.app.quality.get(), 'High detail')
        self.assertEqual(self.app.preview_mode.get(), 'Manual')
        self.assertEqual(self.app.saved_area, [(10, 20), (110, 120)])
        self.assertEqual(self.app.corners, [])
        for name in ('small_test_passed', 'target_lock_passed', 'safety_preflight_passed', 'dry_run_passed'):
            self.assertFalse(getattr(self.app, name), name)
        self.assertIn('recovered DISARMED', self.app.status.get())
        self.assertEqual(self.fixture.payloads(), before)

    def test_settings_only_checkpoint_still_restores_without_loading_an_image(self):
        recovery.clear_snapshot()
        recovery.save_snapshot(profile='Other drawing app', options={'quality': 'High detail'})
        # An unrelated legacy file must not turn an intentional settings-only
        # checkpoint into a required-image restore.
        recovery.IMAGE_FILE.write_bytes(self.valid_png)
        self.assertFalse(recovery.load_snapshot()['has_image'])
        before = self.fixture.payloads()
        with patch.object(recovery, 'load_cached_image', wraps=recovery.load_cached_image) as reader:
            published = self.restore()
        reader.assert_not_called()
        self.assertIn('recovery_loaded', published)
        self.assertNotIn('terminal_status', published)
        self.assertIs(self.app.original, self.previous['image'])
        self.assertEqual(self.fixture.pixels(self.app.original), self.previous['pixels'])
        self.assertEqual(self.app.quality.get(), 'High detail')
        self.assertEqual(self.app.preview_mode.get(), 'Manual')
        self.assertIn('recovered DISARMED', self.app.status.get())
        self.assertEqual(self.fixture.payloads(), before)


if __name__ == '__main__':
    unittest.main()
