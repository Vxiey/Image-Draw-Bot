"""Clearing a cached drawing preserves Undo for the retained source image."""
import unittest
from unittest.mock import patch

from PIL import Image, ImageCms

import DrawBot
import test_v148_ui_batch20_auto_preview as preview_fixtures


class CachedDrawingEditHistoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = preview_fixtures.AutoPreviewHandoffTests('runTest')
        self.addCleanup(self.close_fixture)
        self.fixture.setUp()
        # Recovery persistence is outside this image-history operation. The
        # edit worker, decoder, controller, queue and planner remain real.
        self.fixture.stack.enter_context(patch('SessionRecovery.clear_snapshot'))
        for name in ('STATE_FILE', 'RENDER_FILE', 'IMAGE_FILE'):
            path = self.fixture.stack.enter_context(patch('SessionRecovery.' + name))
            path.exists.return_value = False

    def close_fixture(self):
        self.assertTrue(self.fixture.doCleanups(), 'Image workflow fixture cleanup failed')

    def accepted_edit(self, route):
        app = self.fixture.app('Manual')
        events = self.fixture.start_edit(app, route)
        source = app.original
        expected = source.size, source.tobytes()
        self.fixture.deliver(app, *events)
        history = app.upscale_original if route == 'upscale' else app.background_removal_original
        self.assertIsNotNone(history)
        self.fixture.images.append(history)
        self.assertEqual((history.size, history.tobytes()), expected)
        self.fixture.adopt_plan(app)
        return app, expected, history

    def undo(self, app, route):
        method = (DrawBot.DrawBotApp.undo_upscale if route == 'upscale'
                  else DrawBot.DrawBotApp.undo_background_removal)
        method(app)
        if app.original is not None:
            self.fixture.images.append(app.original)

    def check_cached_clear(self, route):
        app, expected, history = self.accepted_edit(route)
        edited = app.original
        DrawBot.DrawBotApp.clear_cached_drawing(app)
        self.assertIs(app.original, edited)
        self.assertIsNone(app.plan)
        self.assertIsNone(app.pending_clear_drawing)
        self.assertEqual(app.status.get(), 'Cached drawing cleared; source image kept.')
        current_history = app.upscale_original if route == 'upscale' else app.background_removal_original
        self.assertIs(current_history, history)
        self.undo(app, route)
        self.assertEqual((app.original.size, app.original.tobytes()), expected)
        self.assertIsNone(app.upscale_original)
        self.assertIsNone(app.background_removal_original)

    def test_actual_upscale_plan_cache_clear_and_undo_restore_exact_source(self):
        self.check_cached_clear('upscale')

    def test_actual_background_plan_cache_clear_and_undo_keep_existing_behavior(self):
        self.check_cached_clear('background')

    def test_clear_image_discards_both_real_edit_histories_and_undo_cannot_restore_them(self):
        for route in ('upscale', 'background'):
            with self.subTest(route=route):
                app, _expected, _history = self.accepted_edit(route)
                DrawBot.DrawBotApp.clear_image(app)
                self.assertIsNone(app.original)
                self.assertIsNone(app.plan)
                self.assertIsNone(app.upscale_original)
                self.assertIsNone(app.background_removal_original)
                self.undo(app, route)
                self.assertIsNone(app.original)
                self.assertIn('No ', app.status.get())

    def test_stop_discards_queued_edit_and_old_clear_callback_cannot_erase_new_history(self):
        for route in ('upscale', 'background'):
            for remove_image in (False, True):
                with self.subTest(route=route, remove_image=remove_image):
                    app = self.fixture.app('Manual')
                    events = self.fixture.start_edit(app, route)
                    source = app.original
                    rejected = events[0][1][0] if route == 'upscale' else events[0][1].image
                    clear = DrawBot.DrawBotApp.clear_image if remove_image else DrawBot.DrawBotApp.clear_cached_drawing
                    clear(app)
                    self.assertTrue(app.stop.is_set())
                    self.assertIs(app.pending_clear_drawing, remove_image)
                    self.assertIs(app.original, source)
                    token = next(token for token, (delay, _callback) in app.root.jobs.items() if delay == 50)
                    old_clear = app.root.jobs[token][1]
                    self.fixture.deliver(app, *events)
                    app.root.run(token)
                    self.assertIsNone(app.pending_clear_drawing)
                    self.assertIs(app.original, None if remove_image else source)
                    self.assertIsNone(app.upscale_original)
                    self.assertIsNone(app.background_removal_original)
                    with self.assertRaises(ValueError):
                        rejected.getpixel((0, 0))

                    # A later legitimate load clears Stop. Re-delivering the
                    # old scheduled clear must still leave the new Undo alone.
                    self.fixture.deliver(app, *self.fixture.start_edit(app, 'load'))
                    current = app.original
                    expected = current.size, current.tobytes()
                    self.assertTrue(DrawBot.DrawBotApp._start_upscale(app, current, 2, 'Pixel art'))
                    self.fixture.deliver(app, *self.fixture.take_worker_events(app, 'upscaled'))
                    resized = app.original
                    self.assertIs(app.upscale_original, current)
                    self.assertFalse(app.stop.is_set())
                    old_clear()
                    self.assertIs(app.original, resized)
                    self.assertIs(app.upscale_original, current)
                    self.undo(app, 'upscale')
                    self.assertEqual((app.original.size, app.original.tobytes()), expected)

    def test_background_undo_transfers_private_snapshot_without_copy_and_exports_exact_pixels(self):
        app = self.fixture.app('Manual')
        source = self.fixture.source(app)
        source.info.update(draw_studio_format='PNG', draw_studio_color_managed=True,
                           icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        expected = source.tobytes()
        metadata = dict(source.info)
        self.assertTrue(DrawBot.DrawBotApp.remove_image_background(app))
        self.fixture.deliver(app, *self.fixture.take_worker_events(app, 'background_removed'))
        snapshot = app.background_removal_original
        self.fixture.images.append(snapshot)
        # The successful-adoption contract still takes an independent snapshot.
        self.assertIsNot(snapshot, source)
        self.assertEqual(snapshot.tobytes(), expected)
        self.assertEqual(snapshot.info, metadata)
        self.fixture.adopt_plan(app)
        copied = []
        real_copy = Image.Image.copy

        def observe_copy(image):
            copied.append((image.mode, image.size))
            return real_copy(image)

        with patch.object(Image.Image, 'copy', new=observe_copy):
            self.assertTrue(DrawBot.DrawBotApp.undo_background_removal(app))
        self.assertEqual(copied, [], 'Undo transfers its private buffer instead of copying source pixels on Tk')
        self.assertIs(app.original, snapshot)
        self.assertIsNone(app.background_removal_original)
        self.assertIsNone(app.background_removal_meta)
        self.assertEqual(app.original.tobytes(), expected)
        self.assertEqual(app.original.info, metadata)
        self.assertEqual(source.tobytes(), expected)
        self.assertEqual(source.info, metadata)

        # A subsequent real export owns and closes its own snapshot. The
        # transferred live source and its embedded profile must survive it.
        destination = self.fixture.directory / 'restored-source.png'
        with patch('DrawBot.filedialog.asksaveasfilename', return_value=str(destination)):
            self.assertTrue(DrawBot.DrawBotApp.save_png_copy(app))
        self.fixture.deliver(app, *self.fixture.take_worker_events(app, 'png_saved'))
        with Image.open(destination) as saved:
            self.assertEqual(saved.tobytes(), expected)
            self.assertEqual(saved.info['icc_profile'], metadata['icc_profile'])
        self.assertIs(app.original, snapshot)
        self.assertEqual(app.original.tobytes(), expected)

    def test_actual_cross_editor_changes_keep_only_the_latest_edit_undo(self):
        for first, second in (('background', 'upscale'), ('upscale', 'background')):
            with self.subTest(first=first, second=second):
                app, _original, _history = self.accepted_edit(first)
                edited = app.original
                expected = edited.size, edited.tobytes()
                if second == 'upscale':
                    self.assertTrue(DrawBot.DrawBotApp._start_upscale(app, edited, 2, 'Pixel art'))
                    kind = 'upscaled'
                else:
                    self.assertTrue(DrawBot.DrawBotApp.remove_image_background(app))
                    kind = 'background_removed'
                self.fixture.deliver(app, *self.fixture.take_worker_events(app, kind))
                latest = app.original
                active = app.upscale_original if second == 'upscale' else app.background_removal_original
                self.fixture.images.append(active)
                if second == 'background':
                    self.assertIsNot(active, edited)
                self.undo(app, first)
                self.assertIs(app.original, latest)
                self.undo(app, second)
                self.assertEqual((app.original.size, app.original.tobytes()), expected)
                self.assertIsNone(app.upscale_original)
                self.assertIsNone(app.background_removal_original)

    def test_actual_noop_and_stopped_followup_keep_the_accepted_undo_snapshot_live(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                app, expected, history = self.accepted_edit('background')
                edited, plan = app.original, app.plan
                self.assertTrue(DrawBot.DrawBotApp.remove_image_background(app))
                events = self.fixture.take_worker_events(app, 'background_removed')
                result = events[0][1]
                self.assertTrue(result.metadata.get('no_op_reason'))
                self.assertFalse(DrawBot.DrawBotApp.undo_background_removal(app),
                                 'The still-owned worker must block Undo until done is handled')
                if cancelled:
                    DrawBot.DrawBotApp.cancel(app)
                self.fixture.deliver(app, *events)
                self.assertIs(app.original, edited)
                self.assertIs(app.plan, plan)
                self.assertIs(app.background_removal_original, history)
                with self.assertRaises(ValueError):
                    result.image.getpixel((0, 0))
                self.undo(app, 'background')
                self.assertEqual((app.original.size, app.original.tobytes()), expected)
                self.assertIsNone(app.background_removal_original)


if __name__ == '__main__':
    unittest.main()
