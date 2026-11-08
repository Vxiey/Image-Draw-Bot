"""Background cleanup cannot promote protected detail into removable background."""
from contextlib import closing
import queue
import tempfile
import threading
from pathlib import Path
from types import MethodType
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image, ImageDraw

import BackgroundRemoval as background
import DrawBot
from test_v148_ui_batch16_plan_status import PlanStatusFixture


def detailed_source(width=1, *, mode='RGBA', base=(255, 255, 255), ink=(20, 40, 70), alpha=255):
    source = Image.new('RGBA', (100, 80), (*base, 255))
    pen = ImageDraw.Draw(source)
    pen.rectangle((35, 25, 64, 54), fill=(*ink, alpha))
    pen.line((15, 40, 35, 40), width=width, fill=(*ink, alpha))
    del pen
    if mode == 'RGBA':
        return source
    try:
        return source.convert(mode)
    finally:
        source.close()


class BackgroundDetailTests(PlanStatusFixture):
    def app(self):
        app = super().app()
        app.events = queue.Queue()
        app.mouse = Mock()
        app.refresh_runtime_safety_ui = Mock()
        app.refresh_correction_review_ui = Mock()
        app.begin_worker = MethodType(DrawBot.DrawBotApp.begin_worker, app)
        return app

    def drain(self, app, expected):
        worker = app.worker
        self.assertIsInstance(worker, threading.Thread)
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive(), 'The actual worker must finish before fixture cleanup')
        events = []
        while not app.events.empty():
            events.append(app.events.get_nowait())
        self.assertEqual([event[0] for event in events], [expected, 'done'])
        return events

    @staticmethod
    def adopt(app, events):
        for kind, value in events:
            DrawBot.DrawBotApp._handle_event(app, kind, value)

    def test_actual_remove_background_adoption_and_png_keep_connected_thin_details(self):
        # A large connected subject makes this a real accepted cut, not a
        # preservation/no-op case. The 3px case is the unchanged control.
        for width in (1, 2, 3):
            with self.subTest(width=width), tempfile.TemporaryDirectory() as directory:
                source = detailed_source(width)
                self.images.append(source)
                before = source.tobytes()
                raw = np.array(source)
                feature = np.any(raw[..., :3] != 255, axis=2)
                feature[:, 35:] = False
                self.assertEqual(int(feature.sum()), 20 * width)
                app = self.app()
                app.original = source
                observed = {}
                grow = background._grow

                def observe_grow(*args, **kwargs):
                    result = grow(*args, **kwargs)
                    observed['foreground_protected'] = not result[0][feature].any()
                    observed['worker_thread'] = threading.get_ident()
                    return result

                with patch.object(background, '_grow', new=observe_grow):
                    self.assertTrue(DrawBot.DrawBotApp.remove_image_background(app))
                    events = self.drain(app, 'background_removed')
                result = events[0][1]
                self.images.append(result.image)
                self.assertTrue(observed['foreground_protected'])
                self.assertNotEqual(observed['worker_thread'], threading.get_ident())
                self.assertIs(app.original, source, 'Worker must not adopt its own output')
                self.assertIsNone(result.metadata['no_op_reason'])
                self.adopt(app, events)
                self.images.append(app.background_removal_original)
                self.assertIs(app.original, result.image)
                self.assertIsNone(app.activity)
                self.assertEqual(source.tobytes(), before)
                self.assertEqual(app.background_removal_original.tobytes(), before)
                output = np.array(app.original)
                np.testing.assert_array_equal(output[..., :3], raw[..., :3])
                self.assertEqual(app.original.getpixel((0, 0))[3], 0)
                self.assertEqual(app.original.getpixel((50, 35))[3], 255)
                # Feathering can soften the edge, but the connected feature
                # must still exist after the accepted segmentation.
                self.assertTrue(np.all(output[..., 3][feature] > 0))
                self.assertEqual(app.background_removal_meta['foreground_bbox'][0], 15)

                path = Path(directory) / 'removed.png'
                with patch.object(DrawBot.filedialog, 'asksaveasfilename', return_value=str(path)):
                    self.assertTrue(DrawBot.DrawBotApp.save_png_copy(app))
                exports = self.drain(app, 'png_saved')
                self.adopt(app, exports)
                with closing(Image.open(path)) as exported:
                    self.assertEqual(exported.mode, 'RGBA')
                    self.assertEqual(exported.tobytes(), app.original.tobytes())
                self.assertTrue(DrawBot.DrawBotApp.undo_background_removal(app))
                self.assertEqual(app.original.tobytes(), before)

    def test_cleanup_does_not_add_unverified_pixels_at_any_strength(self):
        # The caller supplies a categorical border-flood mask. Zero includes
        # both known foreground and unresolved pixels inside a closed outline.
        mask = np.ones((43, 57), dtype=np.uint8)
        mask[10:34, 25:46] = 0
        mask[19, 5:26] = 0
        mask[25:27, 6:26] = 0
        mask[5:11, 32] = 0
        mask[7:9, 8:10] = 0
        before = mask.tobytes()
        protected = {(x, y) for y in range(mask.shape[0]) for x in range(mask.shape[1]) if mask[y, x] == 0}
        for strength in background.STRENGTHS:
            with self.subTest(strength=strength):
                cleaned = background._cleanup(mask, strength)
                self.assertEqual(cleaned.shape, mask.shape)
                self.assertEqual(cleaned.dtype, np.dtype('uint8'))
                self.assertTrue(all(cleaned[y, x] == 0 for x, y in protected))
                self.assertEqual(mask.tobytes(), before, 'Borrowed flood classification must stay unchanged')
                self.assertEqual(int(cleaned[0, 0]), 1)

    def test_feather_zero_preserves_source_alpha_and_chromatic_thin_foreground(self):
        cases = (
            ('RGB', 'Auto', (255, 255, 255), (20, 40, 70), 255),
            ('RGBA', 'Light background', (255, 255, 255), (20, 40, 70), 128),
            ('RGBA', 'Dark background', (20, 20, 20), (230, 210, 180), 255),
            ('RGBA', 'Corner color', (120, 170, 120), (200, 100, 105), 255),
        )
        for mode, removal_mode, base, ink, source_alpha in cases:
            for width in (1, 2):
                for strength in background.STRENGTHS:
                    with self.subTest(mode=mode, removal=removal_mode, width=width, strength=strength), \
                            closing(detailed_source(width, mode=mode, base=base, ink=ink, alpha=source_alpha)) as source:
                        before = source.tobytes()
                        raw = np.array(source)
                        foreground = np.any(raw[..., :3] != np.array(base), axis=2)
                        result = background.remove_background(source, mode=removal_mode,
                            strength=strength, feather_px=0)
                        with closing(result.image):
                            self.assertIsNone(result.metadata['no_op_reason'])
                            output = np.array(result.image)
                            np.testing.assert_array_equal(output[..., :3], raw[..., :3])
                            self.assertTrue(np.all(output[..., 3][foreground] == source_alpha))
                            self.assertEqual(result.image.getpixel((0, 0))[3], 0)
                            self.assertEqual(source.tobytes(), before)
                            visible_after = int(np.count_nonzero(output[..., 3] > 8))
                            self.assertEqual(result.metadata['removed_pixels'], 8000 - visible_after)

    def test_enclosed_thin_holes_stay_foreground_and_connected_background_slots_remain_removable(self):
        for width in (1, 2):
            with self.subTest(width=width), closing(detailed_source(width)) as source:
                pen = ImageDraw.Draw(source)
                # A white slot reaches the canvas border, unlike the enclosed
                # white strip to its lower right. Both are only 1-2px wide.
                pen.rectangle((0, 31, 49, 30 + width), fill='white')
                pen.rectangle((57, 43, 56 + width, 49), fill='white')
                del pen
                source_bytes = source.tobytes()
                result = background.remove_background(source, feather_px=0)
                with closing(result.image):
                    self.assertIsNone(result.metadata['no_op_reason'])
                    for y in range(31, 31 + width):
                        for x in range(50):
                            self.assertEqual(result.image.getpixel((x, y))[3], 0)
                    for y in range(43, 50):
                        for x in range(57, 57 + width):
                            self.assertEqual(result.image.getpixel((x, y)), (255, 255, 255, 255))
                    for x in range(15, 35):
                        self.assertEqual(result.image.getpixel((x, 40))[3], 255)
                    self.assertEqual(source.tobytes(), source_bytes)

    def test_ordinary_subject_and_preservation_safety_controls_remain_exact(self):
        with closing(detailed_source(3)) as source:
            expected = np.array(source)
            foreground = np.any(expected[..., :3] != 255, axis=2)
            expected[..., 3] = np.where(foreground, 255, 0)
            result = background.remove_background(source, feather_px=0)
            with closing(result.image):
                np.testing.assert_array_equal(np.asarray(result.image), expected)
                self.assertEqual(result.metadata['removed_pixels'], 7040)
                self.assertEqual(result.metadata['region_pixels_processed'], 7040)
                self.assertEqual(result.metadata['foreground_bbox'], [15, 25, 65, 55])
        for color, reason in (((255, 255, 255, 255), 'over 98.5%'),
                              ((20, 40, 60, 0), 'substantial transparency')):
            with self.subTest(color=color), closing(Image.new('RGBA', (60, 40), color)) as source:
                result = background.remove_background(source)
                with closing(result.image):
                    self.assertIsNot(result.image, source)
                    self.assertEqual(result.image.tobytes(), source.tobytes())
                    self.assertEqual(result.metadata['removed_pixels'], 0)
                    self.assertIn(reason, result.metadata['no_op_reason'])

    def test_stop_or_failure_after_real_cleanup_keeps_source_and_closes_private_images(self):
        prepare = background._oriented_rgba
        cleanup = background._cleanup
        for failure in ('stop', 'error'):
            with self.subTest(failure=failure), closing(detailed_source(1)) as source:
                before = source.tobytes()
                private = []
                stopped = threading.Event()
                retained = None
                calls = []

                def prepared(image):
                    result = prepare(image)
                    private.append(result)
                    return result

                def after_cleanup(mask, strength):
                    result = cleanup(mask, strength)
                    calls.append(True)
                    if failure == 'stop':
                        stopped.set()
                    else:
                        raise MemoryError('after actual background-mask cleanup')
                    return result

                with patch.object(background, '_oriented_rgba', new=prepared), \
                        patch.object(background, '_cleanup', new=after_cleanup):
                    try:
                        background.remove_background(source, cancelled=stopped.is_set)
                    except BaseException as error:
                        retained = error
                self.assertEqual(calls, [True])
                self.assertIsInstance(retained, InterruptedError if failure == 'stop' else MemoryError)
                self.assertIsNotNone(retained.__traceback__)
                self.assertEqual(source.tobytes(), before)
                self.assertTrue(private)
                for image in private:
                    with self.assertRaises(ValueError):
                        image.getpixel((0, 0))


if __name__ == '__main__':
    import unittest
    unittest.main()
