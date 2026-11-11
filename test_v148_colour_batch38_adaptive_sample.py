"""Adaptive-count preparation preserves real source pixels with less scratch.

All inputs are existing repository images or mode/crop/orientation derivatives
of them. The reference is the established full visible-RGB composite followed
by Pillow BOX. No synthetic raster pattern or successful compute path is mocked.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import weakref

from PIL import Image

import AdaptiveColorCount as adaptive
from ColorMatchingEngine import visible_rgb_image
import EndToEndAutoTuner as tuner


ASSETS = Path(__file__).resolve().parent / 'assets'


def full_composite_sample(image, max_side=176, **_kwargs):
    """The former sample path, retaining its exact public Pillow arithmetic."""
    with visible_rgb_image(image) as visible:
        width, height = visible.size
        if max(width, height) <= max_side:
            return visible.copy()
        scale = max_side / max(width, height)
        size = max(1, round(width * scale)), max(1, round(height * scale))
        return visible.resize(size, Image.Resampling.BOX)


class ImageAllocations:
    """Observe Python-visible owned image buffers, not process RSS/native scratch."""
    def __init__(self, *, retain=False):
        self.retain = retain
        self.held, self.live, self.records = [], {}, []
        self.peak_samples = 0
        self.stack = ExitStack()

    def observed(self, image):
        identity = id(image)
        if identity not in self.live:
            samples = image.width * image.height * len(image.getbands())
            reference = weakref.ref(image, lambda _ref, key=identity: self.live.pop(key, None))
            self.live[identity] = (reference, samples)
            self.records.append((image.mode, image.size))
            if self.retain:
                self.held.append(image)
            self.peak_samples = max(self.peak_samples, sum(row[1] for row in self.live.values()))
        return image

    def __enter__(self):
        for name in ('copy', 'convert', 'resize', 'getchannel', 'quantize'):
            original = getattr(Image.Image, name)

            def call(source, *args, _original=original, **kwargs):
                output = _original(source, *args, **kwargs)
                return self.observed(output) if output is not source else output

            self.stack.enter_context(patch.object(Image.Image, name, call))
        for name in ('new', 'merge'):
            original = getattr(Image, name)

            def factory(*args, _original=original, **kwargs):
                return self.observed(_original(*args, **kwargs))

            self.stack.enter_context(patch.object(Image, name, factory))
        close = Image.Image.close

        def closed(image):
            self.live.pop(id(image), None)
            return close(image)

        self.stack.enter_context(patch.object(Image.Image, 'close', closed))
        return self

    def __exit__(self, *_error):
        self.stack.close()

    def close(self):
        for image in self.held:
            image.close()
        self.held.clear()


class AdaptiveSampleTests(unittest.TestCase):
    @contextmanager
    def source(self, filename='image-draw-bot-app-screenshot.png'):
        with Image.open(ASSETS / filename) as existing:
            source = existing.copy()
        pixels, info = source.tobytes(), dict(source.info)
        try:
            yield source
            self.assertEqual(source.tobytes(), pixels)
            self.assertEqual(source.info, info)
        finally:
            source.close()

    def owned_observation(self):
        observed = ImageAllocations(retain=True)
        self.addCleanup(observed.close)
        return observed

    def assert_closed(self, images):
        live = []
        for image in images:
            try:
                image.getpixel((0, 0))
            except ValueError:
                continue
            live.append((image.mode, image.size))
        self.assertEqual(live, [], 'Adaptive analysis retained private raster cores.')

    def test_opaque_samples_match_full_composite_across_modes_and_geometry(self):
        with self.source() as source, ExitStack() as owned:
            inputs = [source]
            inputs.extend(owned.enter_context(image) for image in (
                source.convert('RGB'), source.convert('L'),
                source.transpose(Image.Transpose.ROTATE_90),
                source.crop((0, 0, 719, 393)), source.crop((0, 0, 1, 1048)),
                source.crop((0, 0, 1920, 1))))
            for image in inputs:
                for bound in (37, 176, 193):
                    with self.subTest(mode=image.mode, size=image.size, bound=bound), \
                            full_composite_sample(image, bound) as expected, \
                            adaptive._bounded_sample(image, bound) as actual:
                        self.assertEqual((actual.mode, actual.size), (expected.mode, expected.size))
                        self.assertEqual(actual.tobytes(), expected.tobytes())
                        self.assertEqual(actual.info, expected.info)

    def test_transparency_modes_keep_original_compositing_and_pixel_rounding(self):
        with self.source('image-draw-bot-icon.png') as source, ExitStack() as owned:
            rgb = owned.enter_context(source.convert('RGB'))
            rgb.info['transparency'] = rgb.getpixel((0, 0))
            gray = owned.enter_context(source.convert('L'))
            gray.info['transparency'] = gray.getpixel((0, 0))
            indexed = owned.enter_context(source.convert('P'))
            for image in (source, rgb, gray, indexed):
                with self.subTest(mode=image.mode), full_composite_sample(image) as expected, \
                        adaptive._bounded_sample(image) as actual:
                    self.assertEqual(actual.tobytes(), expected.tobytes())
                    self.assertEqual(actual.info, expected.info)

    def test_opaque_import_preparation_keeps_only_one_large_single_channel_buffer(self):
        with self.source() as source:
            with ImageAllocations() as previous:
                with full_composite_sample(source) as expected:
                    expected_bytes = expected.tobytes()
            with ImageAllocations() as observed:
                with adaptive._bounded_sample(source) as actual:
                    self.assertEqual(actual.tobytes(), expected_bytes)
            budget = source.width * source.height + 8 * 176 * 176
            self.assertLessEqual(observed.peak_samples, budget,
                                 'The small sample still materialized a full multichannel source.')
            self.assertLess(observed.peak_samples, previous.peak_samples)
            full_buffers = [mode for mode, size in observed.records if size == source.size]
            self.assertTrue(full_buffers)
            self.assertTrue(all(mode == 'L' for mode in full_buffers))

    def test_public_recommendations_and_actual_tuner_keep_complete_results(self):
        with self.source() as source:
            for fidelity, ceiling in (('Fast', 8), ('Balanced', 16), ('Faithful', 24), ('Exact', 32)):
                with self.subTest(fidelity=fidelity):
                    with patch.object(adaptive, '_bounded_sample', full_composite_sample):
                        expected = adaptive.recommend_adaptive_color_count(
                            source, ceiling=ceiling, fidelity=fidelity)
                    self.assertEqual(adaptive.recommend_adaptive_color_count(
                        source, ceiling=ceiling, fidelity=fidelity), expected)
            with patch.object(adaptive, '_bounded_sample', full_composite_sample):
                expected = tuner.analyze_source(source).as_dict()
            original_sample = adaptive._bounded_sample
            observations = []

            def sample(*args, **kwargs):
                with ImageAllocations() as observed:
                    result = original_sample(*args, **kwargs)
                observations.append(observed.peak_samples)
                return result

            with patch.object(adaptive, '_bounded_sample', sample):
                actual = tuner.analyze_source(source).as_dict()
            self.assertEqual(actual, expected)
            self.assertEqual(len(observations), 1)
            self.assertLessEqual(observations[0], source.width * source.height + 8 * 176 * 176)

    def test_successful_count_closes_its_sample_and_quantizer(self):
        with self.source('image-draw-bot-icon.png') as source, self.owned_observation() as observed:
            count, metadata = adaptive.recommend_adaptive_color_count(source, ceiling=16)
            self.assertEqual(metadata['recommended_colors'], count)
            self.assertTrue(any(image.mode == 'P' for image in observed.held))
            self.assert_closed(observed.held)

    def test_retained_quantizer_failure_releases_all_owned_images(self):
        failure = MemoryError('quantizer counts allocation failed')
        counts = Image.Image.getcolors

        def denied(image, *args, **kwargs):
            if image.mode == 'P':
                raise failure
            return counts(image, *args, **kwargs)

        with self.source() as source, self.owned_observation() as observed, \
                patch.object(Image.Image, 'getcolors', denied):
            try:
                adaptive.recommend_adaptive_color_count(source, ceiling=16)
            except MemoryError as actual:
                self.assertIs(actual, failure)
            else:
                self.fail('The quantizer failure must stay visible.')
            self.assert_closed(observed.held)

    def test_stop_after_actual_resize_closes_partial_sample_before_quantization(self):
        stopped = threading.Event()
        resize = Image.Image.resize
        resized = []

        def stop_after_resize(image, *args, **kwargs):
            result = resize(image, *args, **kwargs)
            resized.append(image.size)
            stopped.set()
            return result

        with self.source() as source, patch.object(Image.Image, 'resize', stop_after_resize), \
                self.owned_observation() as observed, patch.object(adaptive, '_quantized_candidates') as quantize:
            with self.assertRaises(InterruptedError):
                adaptive.recommend_adaptive_color_count(source, ceiling=16, cancelled=stopped.is_set)
            self.assertEqual(len(resized), 1)
            quantize.assert_not_called()
            self.assert_closed(observed.held)

    def test_retained_resize_failure_closes_intermediates_and_preserves_source(self):
        failure = MemoryError('sample resize allocation failed')

        def denied(*_args, **_kwargs):
            raise failure

        with self.source() as source, patch.object(Image.Image, 'resize', denied), \
                self.owned_observation() as observed:
            try:
                adaptive.recommend_adaptive_color_count(source, ceiling=16)
            except MemoryError as actual:
                self.assertIs(actual, failure)
            else:
                self.fail('The sample resize failure must stay visible.')
            self.assert_closed(observed.held)

    def test_small_sources_return_independent_owned_pixels(self):
        with self.source('paint-tools-reference.png') as source:
            with full_composite_sample(source) as expected:
                actual = adaptive._bounded_sample(source)
                try:
                    self.assertIsNot(actual, source)
                    self.assertEqual(actual.tobytes(), expected.tobytes())
                    self.assertEqual(actual.info, expected.info)
                finally:
                    actual.close()
            source.getpixel((0, 0))

    def test_quantizer_failure_survives_secondary_close_error_and_lone_close_is_visible(self):
        counts, close = Image.Image.getcolors, Image.Image.close
        for primary in (True, False):
            with self.subTest(primary=primary), self.source('paint-tools-reference.png') as source:
                failure = MemoryError('quantizer counts allocation failed')
                closed = []

                def counted(image, *args, **kwargs):
                    if primary and image.mode == 'P':
                        raise failure
                    return counts(image, *args, **kwargs)

                def noisy_close(image):
                    close(image)
                    if image.mode == 'P':
                        closed.append(image)
                        raise OSError('quantizer disposal failed')

                with patch.object(Image.Image, 'getcolors', counted), \
                        patch.object(Image.Image, 'close', noisy_close):
                    if primary:
                        with self.assertRaises(MemoryError) as caught:
                            adaptive.recommend_adaptive_color_count(source, ceiling=16)
                        self.assertIs(caught.exception, failure)
                        self.assertEqual(len(closed), 1)
                        self.assertTrue(any('OSError' in note for note in getattr(failure, '__notes__', ())))
                    else:
                        with self.assertRaisesRegex(OSError, 'quantizer disposal failed'):
                            adaptive.recommend_adaptive_color_count(source, ceiling=16)


if __name__ == '__main__':
    unittest.main()
