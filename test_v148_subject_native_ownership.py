"""Native Subject diagnostics transfer ownership only with a completed plan."""
from contextlib import ExitStack, closing
import unittest
from unittest.mock import patch

from PIL import Image

import DrawBot
import PixelAccuracyEngine
import SubjectFocus
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch09_subject import BLUE, settings


class NativeSubjectOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.source = self.stack.enter_context(closing(Image.new('RGB', (64, 64), BLUE)))
        self.options = settings(browser_brush_plan=None, brush_px=4,
                                corners=((100, 100), (181, 164)))
        self.images = []
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        evaluate = SubjectFocus.evaluate_native_subject_plan
        def observe(*args, **kwargs):
            result = evaluate(*args, **kwargs)
            for name in ('coverage_preview', 'error_preview'):
                image = result[name]
                self.images.append(image)
                # Keep failure diagnostics owned even when a regression leaves
                # them open. Tests assert the product closed them before this.
                self.stack.callback(image.close)
            return result
        self.stack.enter_context(patch.object(SubjectFocus, 'evaluate_native_subject_plan', side_effect=observe))

    def assert_failed_images_closed(self):
        self.assertEqual(len(self.images), 2)
        for image in self.images:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))
        self.assertEqual(self.source.getpixel((0, 0)), BLUE, 'The caller retains its source image.')

    def test_failure_after_evaluation_before_finish_closes_both_native_views(self):
        groups = PixelAccuracyEngine.execution_groups_from_sequence
        for kind in (InterruptedError, RuntimeError):
            with self.subTest(kind=kind.__name__):
                self.images.clear()
                failure = kind('injected before finish_plan')
                def fail_after_evaluation(*args, **kwargs):
                    if self.images:
                        raise failure
                    return groups(*args, **kwargs)
                with patch.object(PixelAccuracyEngine, 'execution_groups_from_sequence', side_effect=fail_after_evaluation), \
                     self.assertRaises(kind) as caught:
                    DrawBot.make_plan(self.source, (81, 64), self.options)
                self.assertIs(caught.exception, failure)
                self.assert_failed_images_closed()

    def test_failure_inside_finish_closes_both_native_views(self):
        start = DrawBot.profiler_start
        for kind in (InterruptedError, RuntimeError):
            with self.subTest(kind=kind.__name__):
                self.images.clear()
                failure = kind('injected inside finish_plan')
                def fail_in_finish(options, stage):
                    if stage == 'execution_estimate':
                        self.assertEqual(len(self.images), 2)
                        raise failure
                    return start(options, stage)
                with patch.object(DrawBot, 'profiler_start', side_effect=fail_in_finish), \
                     self.assertRaises(kind) as caught:
                    DrawBot.make_plan(self.source, (81, 64), self.options)
                self.assertIs(caught.exception, failure)
                self.assert_failed_images_closed()

    def test_success_keeps_plan_views_open_and_does_not_close_callers_source(self):
        plan = DrawBot.make_plan(self.source, (81, 64), self.options)
        try:
            self.assertEqual(len(self.images), 2)
            for image, key in zip(self.images, ('_pixel_coverage_preview', '_pixel_error_preview')):
                self.assertIs(plan['options'][key], image)
                self.assertEqual(image.size, (81, 64))
                image.getpixel((0, 0))
            self.assertEqual(self.source.getpixel((0, 0)), BLUE)
            self.assertIsNot(plan['ui_previews']['coverage'], self.images[0])
            plan['ui_previews']['coverage'].getpixel((0, 0))
            plan['ui_previews']['accuracy_error'].getpixel((0, 0))
        finally:
            close_plan(plan, self.source)
        self.assert_failed_images_closed()

    def test_close_error_cannot_replace_primary_failure_or_skip_second_view(self):
        failure = InterruptedError('primary planning Stop')
        def fail_finish(*args, **kwargs):
            self.assertEqual(len(self.images), 2)
            close = self.images[0].close
            def fail_close():
                close()
                raise PermissionError('secondary image cleanup error')
            self.stack.enter_context(patch.object(self.images[0], 'close', side_effect=fail_close))
            raise failure
        with patch.object(DrawBot, 'finish_plan', side_effect=fail_finish), \
             self.assertRaises(InterruptedError) as caught:
            DrawBot.make_plan(self.source, (81, 64), self.options)
        self.assertIs(caught.exception, failure)
        self.assert_failed_images_closed()
        self.assertTrue(any('PermissionError' in note for note in getattr(failure, '__notes__', ())))


if __name__ == '__main__':
    unittest.main()
