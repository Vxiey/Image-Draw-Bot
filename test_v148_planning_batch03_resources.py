from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from PIL import Image

import AutoSketchBudget as sketch
import PixelAccuratePlanner as pixels


class AutoSketchTrialTests(unittest.TestCase):
    def test_discarded_trial_buffers_close_but_returned_and_borrowed_images_survive(self):
        original = Image.new('RGB', (4, 4), 'white')
        borrowed = Image.new('RGB', (4, 4), 'blue')
        trials = []
        def planner(image, area, options, cancelled):
            plan = {'image': image.copy(), 'preview': image.copy(), 'ui_previews': {'mask': image.copy()},
                    'options': dict(options), 'count': 1,
                    'estimate': 100 if options['sketch_detail'] == 'Detailed' else 1}
            plan['ui_previews']['borrowed'] = borrowed
            trials.append(plan)
            return plan
        try:
            with patch.object(sketch.time, 'monotonic', return_value=0):
                result = sketch.choose_sketch(original, (4, 4), {'max_seconds': 20, 'borrowed': borrowed}, planner, Mock())
            self.assertIs(result, trials[1])
            for image in (trials[0]['image'], trials[0]['preview'], trials[0]['ui_previews']['mask']):
                with self.assertRaises(ValueError):image.getpixel((0, 0))
            for image in (original, borrowed, result['image'], result['preview'], result['ui_previews']['mask']):
                image.getpixel((0, 0))
        finally:
            original.close(); borrowed.close()
            for plan in trials:
                for image in sketch._trial_images(plan):image.close()

    def test_same_preview_transferred_to_next_candidate_is_preserved(self):
        shared = Image.new('RGB', (2, 2), 'red')
        def planner(original, area, options, cancelled):
            return {'preview': shared, 'options': dict(options), 'count': 1,
                    'estimate': 100 if options['sketch_detail'] == 'Detailed' else 1}
        try:
            with patch.object(sketch.time, 'monotonic', return_value=0):
                result = sketch.choose_sketch(None, (2, 2), {'max_seconds': 20}, planner, Mock())
            self.assertIs(result['preview'], shared)
            self.assertEqual(shared.getpixel((0, 0)), (255, 0, 0))
        finally:
            shared.close()

    def test_unlimited_alias_is_not_trimmed_and_late_cancel_releases_trial(self):
        images = []
        stopped = False
        def planner(original, area, options, cancelled):
            nonlocal stopped
            image = Image.new('RGB', (2, 2))
            images.append(image); stopped = True
            return {'image': image, 'options': dict(options), 'estimate': 500, 'count': 100}
        with self.assertRaises(InterruptedError):
            sketch.choose_sketch(None, (2, 2), {'time_budget_mode': 'Unlimited / Accuracy'}, planner, Mock(), lambda: stopped)
        with self.assertRaises(ValueError):images[0].getpixel((0, 0))
        result = sketch.choose_sketch(None, (2, 2), {'time_budget_mode': 'Unlimited / Accuracy'}, planner, Mock())
        try:
            self.assertEqual(result['options']['sketch_auto_meta']['timer_source'], 'Unlimited')
            self.assertEqual(result['count'], 100)
        finally:
            result['image'].close()

    def test_invalid_estimate_fails_with_owned_images_closed(self):
        for estimate in (-1, float('nan'), float('inf'), True, '1', 10 ** 1000):
            image = Image.new('RGB', (2, 2))
            plan = {'image': image, 'options': {}, 'estimate': estimate, 'count': 1}
            with self.subTest(estimate=repr(estimate)), self.assertRaises(ValueError):
                sketch.choose_sketch(None, (2, 2), {'unlimited_time': True}, lambda *args: plan, Mock())
            with self.assertRaises(ValueError):image.getpixel((0, 0))


class PaletteImageOwnershipTests(unittest.TestCase):
    def test_oriented_and_rgba_buffers_close_after_backend_and_fallback_failure(self):
        original = Image.new('RGB', (2, 2), 'red')
        oriented = original.copy()
        converted = []
        convert = Image.Image.convert
        def tracked(image, *args, **kwargs):
            result = convert(image, *args, **kwargs)
            converted.append(result)
            return result
        try:
            with patch.object(pixels.ImageOps, 'exif_transpose', return_value=oriented), \
                    patch.object(Image.Image, 'convert', new=tracked), \
                    patch('UniversalGpuAcceleration.palette_indices_rgba', side_effect=RuntimeError('backend')), \
                    patch.object(pixels, '_cpu_palette_map', side_effect=RuntimeError('fallback')):
                with self.assertRaisesRegex(RuntimeError, 'fallback'):
                    pixels.exact_palette_map(original, [(0, 0, 0)])
            for image in [oriented, *converted]:
                with self.assertRaises(ValueError):image.getpixel((0, 0))
            self.assertEqual(original.getpixel((0, 0)), (255, 0, 0))
        finally:
            original.close()


if __name__ == '__main__':
    unittest.main()
