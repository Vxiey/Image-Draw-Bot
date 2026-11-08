"""Actual source accuracy reads already normalized images without identity copies."""
from contextlib import ExitStack, closing, contextmanager
import copy
import unittest
from unittest.mock import patch

from PIL import Image

import AccuracyEvaluator as accuracy
import DrawBot
import UniversalGpuAcceleration as universal
from benchmark_v148_image_workflow import fingerprint
import test_v148_rendering_batch27_sketch_finalization as fixtures


def image_source(mode='RGB', size=(17, 13)):
    actual_mode = 'RGB' if mode == 'RGB-keyed' else mode
    image = Image.new(actual_mode, size)
    palette = ((10, 20, 30), (200, 70, 25), (25, 120, 210), (200, 210, 50))
    if mode == 'P':
        image.putpalette([component for color in palette for component in color] + [0] * 756)
        image.info['transparency'] = bytes((0, 63, 191, 255))
    for y in range(size[1]):
        for x in range(size[0]):
            rgb = palette[(x + 2*y) % 4]
            alpha = (x*41 + y*23) % 256
            value = (rgb + (alpha,) if mode == 'RGBA' else
                     ((x*19 + y*37) % 256, alpha) if mode == 'LA' else
                     (x*19 + y*37) % 256 if mode == 'L' else
                     (x + 2*y) % 4 if mode == 'P' else rgb)
            image.putpixel((x, y), value)
    if mode == 'RGB-keyed':
        image.info['transparency'] = palette[0]
    image.info['comment'] = 'borrowed source metadata'
    return image


def visible_reference(image):
    """Independent integer alpha-over-white pixels for the fixture modes."""
    result = Image.new('RGB', image.size)
    palette = image.getpalette() if image.mode == 'P' else None
    for y in range(image.height):
        for x in range(image.width):
            value = image.getpixel((x, y))
            if image.mode == 'RGBA':
                rgb, alpha = value[:3], value[3]
            elif image.mode == 'LA':
                rgb, alpha = (value[0],)*3, value[1]
            elif image.mode == 'L':
                rgb, alpha = (value,)*3, 255
            elif image.mode == 'P':
                rgb, alpha = palette[3*value:3*value+3], image.info['transparency'][value]
            else:
                rgb, alpha = value, 0 if value == image.info.get('transparency') else 255
            result.putpixel((x, y), tuple((channel*alpha + 255*(255-alpha) + 127)//255 for channel in rgb))
    return result


def snapshot(image):
    return image.mode, image.size, image.tobytes(), copy.deepcopy(image.info)


def is_open(image):
    try:
        image.getpixel((0, 0))
    except ValueError:
        return False
    return True


def score(source, preview, **kwargs):
    return accuracy.evaluate_preview(source, preview, gpu_mode='CPU',
        return_error_map=True, return_delta_e_heatmap=True, **kwargs)


@contextmanager
def observe_evaluations():
    """Count copies of the actual inputs only inside the real evaluation call."""
    actual_evaluate = accuracy.evaluate_preview
    actual_copy = Image.Image.copy
    records = []

    def evaluated(source, preview, *args, **kwargs):
        cached = kwargs.get('normalized_source')
        selected = cached if isinstance(cached, Image.Image) and cached.size == preview.size else source
        inputs = (selected, preview)
        targets = {id(selected): 'selected_source', id(preview): 'preview'}
        before = [snapshot(image) for image in inputs]
        copies = []
        owned = []

        def copied(image, *a, **kw):
            result = actual_copy(image, *a, **kw)
            if id(image) in targets:
                copies.append(dict(input=targets[id(image)], mode=image.mode, size=list(image.size),
                    pixel_payload_bytes=image.width*image.height*len(image.getbands())))
                owned.append(result)
            return result

        with patch.object(Image.Image, 'copy', new=copied):
            result = actual_evaluate(source, preview, *args, **kwargs)
        records.append(dict(copies=copies, copied_pixel_payload_bytes=sum(row['pixel_payload_bytes'] for row in copies),
            inputs_unchanged_and_open=all(is_open(image) and snapshot(image) == old
                for image, old in zip(inputs, before)),
            temporary_copy_outputs_closed=all(not is_open(image) for image in owned),
            inputs=[dict(mode=image.mode, size=list(image.size)) for image in inputs], result=fingerprint(result)))
        return result

    with patch.object(accuracy, 'evaluate_preview', new=evaluated):
        yield records


class AccuracyInputOwnershipTests(unittest.TestCase):
    def test_actual_public_plans_do_not_recopy_normalized_source_or_final_rgb_preview(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            for kind in ('rgb', 'rgba'):
                with self.subTest(quality=quality, kind=kind), fixtures.planner_fixture(quality, 1, kind) as (source, options):
                    before = snapshot(source)
                    plan = None
                    try:
                        with observe_evaluations() as records:
                            plan = DrawBot.make_plan(source, source.size, options)
                        self.assertEqual(len(records), 1)
                        row = records[0]
                        self.assertTrue(row['inputs_unchanged_and_open'])
                        self.assertTrue(row['temporary_copy_outputs_closed'])
                        self.assertEqual(snapshot(source), before)
                        self.assertIn('adaptive_accuracy_meta', plan['options'])
                        normalized = plan['ui_previews']['original_normalized']
                        preview = plan['preview']
                        error = sum(abs(a-b) for a, b in zip(normalized.tobytes(), preview.tobytes()))
                        expected = 100*(1-error/(normalized.width*normalized.height*765))
                        self.assertAlmostEqual(plan['options']['adaptive_accuracy_meta']['source_pixel_accuracy_percent'],
                                               expected, delta=.011)
                        self.assertEqual(row['copies'], [])
                    finally:
                        fixtures.close_plan(plan)

    def test_direct_and_valid_cached_rgb_are_borrowed_but_wrong_size_cache_is_ignored(self):
        with ExitStack() as stack:
            source = stack.enter_context(closing(image_source()))
            preview = stack.enter_context(closing(image_source()))
            cached = stack.enter_context(closing(image_source()))
            wrong = stack.enter_context(closing(image_source(size=(19, 15))))
            cached.putpixel((0, 0), (255, 255, 255))
            preview.putpixel((1, 1), (0, 0, 0))
            for supplied, expected_source in ((None, source), (cached, cached), (wrong, source)):
                with self.subTest(cache=supplied.size if supplied is not None else None):
                    expected = score(expected_source, preview)
                    try:
                        with observe_evaluations() as records:
                            actual = score(source, preview, normalized_source=supplied)
                        try:
                            self.assertEqual(fingerprint(actual), fingerprint(expected))
                            self.assertEqual(records[0]['copies'], [])
                            self.assertTrue(records[0]['inputs_unchanged_and_open'])
                        finally:
                            fixtures.close_plan(actual)
                    finally:
                        fixtures.close_plan(expected)
                    self.assertTrue(all(is_open(image) for image in (source, preview, cached, wrong)))

    def test_alpha_keyed_palette_and_non_rgb_inputs_keep_independent_visible_pixels(self):
        for mode in ('RGBA', 'RGB-keyed', 'P', 'L', 'LA'):
            with self.subTest(mode=mode), ExitStack() as stack:
                source = stack.enter_context(closing(image_source(mode)))
                preview = stack.enter_context(closing(image_source('RGBA')))
                expected_source = stack.enter_context(closing(visible_reference(source)))
                expected_preview = stack.enter_context(closing(visible_reference(preview)))
                before = snapshot(source), snapshot(preview)
                expected = score(expected_source, expected_preview)
                actual = score(source, preview, normalized_source=source)
                try:
                    self.assertEqual(fingerprint(actual), fingerprint(expected))
                    self.assertEqual((snapshot(source), snapshot(preview)), before)
                finally:
                    fixtures.close_plan(actual)
                    fixtures.close_plan(expected)

    def test_public_normalizer_keeps_owned_results_and_real_resize_semantics(self):
        for mode in ('RGB', 'RGBA', 'RGB-keyed', 'P'):
            with self.subTest(mode=mode), closing(image_source(mode)) as source:
                before = snapshot(source)
                with closing(accuracy.normalize_source(source, source.size)) as owned, \
                     closing(visible_reference(source)) as expected:
                    self.assertIsNot(owned, source)
                    self.assertEqual((owned.mode, owned.size, owned.tobytes()),
                                     (expected.mode, expected.size, expected.tobytes()))
                    owned.putpixel((0, 0), (1, 2, 3))
                    self.assertEqual(snapshot(source), before)
                with closing(accuracy.normalize_source(source, (11, 7))) as resized, \
                     closing(Image.new('RGB', (1, 1))) as wrong_cache:
                    self.assertEqual((resized.mode, resized.size), ('RGB', (11, 7)))
                    actual = score(source, resized, normalized_source=wrong_cache)
                    try:
                        self.assertEqual(actual['source_pixel_accuracy_percent'], 100.0)
                    finally:
                        fixtures.close_plan(actual)
                self.assertEqual(snapshot(source), before)

    def test_retained_closed_input_error_and_real_metric_stop_preserve_borrowed_owners(self):
        original_normalize = accuracy.normalize_source
        original_metric = universal.pixel_channel_error
        for stop in (False, True):
            with self.subTest(stop=stop), closing(image_source('RGBA')) as source, \
                 closing(image_source('RGB')) as preview:
                before = snapshot(source)
                outputs, stopped = [], []
                def normalized(*args, **kwargs):
                    value = original_normalize(*args, **kwargs)
                    outputs.append(value)
                    return value
                def metric(*args, **kwargs):
                    value = original_metric(*args, **kwargs)
                    stopped.append(True)
                    return value
                if not stop:
                    preview.close()
                retained = None
                with patch.object(accuracy, 'normalize_source', side_effect=normalized), \
                     patch.object(universal, 'pixel_channel_error', side_effect=metric):
                    try:
                        score(source, preview, cancelled=lambda: bool(stopped))
                    except (InterruptedError, ValueError) as error:
                        retained = error
                self.assertIsNotNone(retained)
                self.assertIsInstance(retained, InterruptedError if stop else ValueError)
                self.assertIsNotNone(retained.__traceback__)
                self.assertTrue(outputs)
                self.assertTrue(all(not is_open(image) for image in outputs))
                self.assertEqual(snapshot(source), before)
                self.assertEqual(is_open(preview), stop)
                self.assertEqual(bool(stopped), stop)


if __name__ == '__main__':
    unittest.main()
