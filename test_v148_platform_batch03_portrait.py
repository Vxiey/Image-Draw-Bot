from contextlib import closing
import math
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageFilter

import PortraitPlanner as portrait


class PortraitBudgetTests(unittest.TestCase):
    def test_explicit_small_and_zero_stroke_caps_are_honored(self):
        with closing(Image.new("L", (80, 80), 0)) as image:
            for lines in (True, False):
                for limit in (0, 1, 5, 79):
                    groups, stats = portrait.portrait_strokes(image, 9, lines=lines, max_strokes=limit, gpu_mode="CPU")
                    self.assertLessEqual(sum(map(len, groups)), limit)
                    self.assertEqual(sum(map(len, groups)), stats.tone_strokes + stats.edge_strokes)

    def test_dot_generation_stops_after_the_requested_visible_prefix(self):
        reads = []
        class Pixels:
            def __getitem__(self, point):
                reads.append(point)
                return 0
        image = SimpleNamespace(size=(1000000, 1000000), load=lambda: Pixels())
        result = portrait._dot_strokes(image, 10, lambda: False, max_strokes=5)
        self.assertEqual(len(result), 5)
        self.assertEqual(len(reads), 5)


class PortraitNumericTests(unittest.TestCase):
    def test_vector_contrast_preserves_scalar_rounding_and_original_image(self):
        raw = np.random.default_rng(95).integers(0, 256, (127, 93), dtype=np.uint8)
        with closing(Image.fromarray(raw)) as image:
            for strength in (.27, .42, .52):
                with closing(image.filter(ImageFilter.GaussianBlur(1.35))) as blur:
                    expected = bytes(max(0, min(255, round(value + (value - low) * strength)))
                                     for value, low in zip(image.tobytes(), blur.tobytes()))
                with closing(portrait._enhance_local_contrast(image, strength)) as result:
                    self.assertEqual(result.tobytes(), expected)
                self.assertEqual(image.tobytes(), raw.tobytes())

    def test_priority_heap_and_streamed_coverage_preserve_exact_selection(self):
        with closing(Image.fromarray(np.random.default_rng(96).integers(0, 256, (30, 40), dtype=np.uint8))) as image:
            candidates = [(x, y, x + 2, y) for y in range(30) for x in range(38)]
            saliency = np.random.default_rng(97).random(1200).tolist()
            pixels = image.load()
            for wanted in (1, 17, 200, len(candidates), len(candidates) + 9):
                for fraction in (0, .26, .88, 1):
                    scored = [(portrait._stroke_score(stroke, saliency, pixels, 40, 30), i, stroke)
                              for i, stroke in enumerate(candidates)]
                    scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)
                    count = min(wanted, len(scored))
                    priority_count = min(count, max(0, round(count * fraction)))
                    priority = scored[:priority_count]
                    ids = {i for _, i, _ in priority}
                    rest = [stroke for i, stroke in enumerate(candidates) if i not in ids]
                    expected = [stroke for _, _, stroke in priority] + portrait._evenly_sample(rest, count - priority_count)
                    actual, n = portrait._select_tone_candidates(candidates, wanted, saliency, pixels, 40, 30, fraction)
                    self.assertEqual(actual, expected)
                    self.assertEqual(n, priority_count)

    def test_priority_selection_can_stop_inside_one_large_candidate_set(self):
        count = [0]
        def score(*args):
            count[0] += 1
            return 1.0
        with mock.patch.object(portrait, "_stroke_score", side_effect=score), self.assertRaises(InterruptedError):
            portrait._select_tone_candidates([(0, 0, 1, 0)] * 2000, 10, [], None, 4, 4, .5,
                                             cancelled=lambda: count[0] >= 130)
        self.assertLessEqual(count[0], 256)


class PortraitImageLifetimeTests(unittest.TestCase):
    def test_retained_failure_frames_close_owned_images_and_preserve_caller(self):
        owned = []
        original = portrait._OwnedImages.own
        def capture(owner, image):
            owned.append(image)
            return original(owner, image)
        with closing(Image.new("RGBA", (100, 70), (30, 50, 90, 128))) as image:
            with mock.patch.object(portrait._OwnedImages, "own", capture), \
                 mock.patch.object(portrait, "gpu_enhance_portrait", side_effect=RuntimeError("synthetic failure")):
                try:
                    portrait.prepare_portrait_image(image, (200, 200), 8, gpu_mode="CPU")
                except RuntimeError as error:
                    retained = error
                else:
                    self.fail("injected failure did not propagate")
            self.assertIsNotNone(retained.__traceback__)
            self.assertTrue(owned)
            for intermediate in owned:
                with self.assertRaises(ValueError):
                    intermediate.getpixel((0, 0))
            self.assertEqual(image.getpixel((0, 0)), (30, 50, 90, 128))

    def test_success_keeps_only_returned_image_open(self):
        owned = []
        original = portrait._OwnedImages.own
        def capture(owner, image):
            owned.append(image)
            return original(owner, image)
        with closing(Image.new("RGB", (70, 50), "gray")) as image:
            with mock.patch.object(portrait._OwnedImages, "own", capture):
                result, _ = portrait.prepare_portrait_image(image, (100, 100), 8, gpu_mode="CPU")
            with closing(result):
                result.getpixel((0, 0))
                for intermediate in owned:
                    if intermediate is result:
                        continue
                    with self.assertRaises(ValueError):
                        intermediate.getpixel((0, 0))
            self.assertEqual(image.getpixel((0, 0)), (128, 128, 128))


if __name__ == "__main__":
    unittest.main()
