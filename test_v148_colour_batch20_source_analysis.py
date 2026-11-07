"""Real dynamic color plans share source pixels and release private images."""
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import unittest
import weakref
from unittest.mock import patch

from PIL import Image
import numpy as np

import ColorMatchingEngine as measurement
import DrawBot
import DynamicColors as dynamic
import PictureCustomPaletteLegacy as picture
import RegionAwareQuantization as regions
from test_v148_colour_batch19_regions import PALETTE, dynamic_settings, public_settings, region_graphic
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch17_layered_diagnostics import calibrated


def image_is_open(image):
    try:
        image.im
    except ValueError:
        return False
    return True


@contextmanager
def image_operations(borrowed=()):
    """Observe actual Pillow outputs, then dispose fixtures after assertions.

    Retaining wrappers lets tests inspect explicit ownership. It is not a
    peak-memory measurement; performance probes run without these observers.
    """
    events = []
    borrowed_ids = {id(image) for image in borrowed}
    with ExitStack() as stack:
        for method in ('copy', 'convert', 'getchannel', 'quantize', 'crop'):
            original = getattr(Image.Image, method)
            def observed(image, *args, _method=method, _original=original, **kwargs):
                result = _original(image, *args, **kwargs)
                if isinstance(result, Image.Image) and id(result) not in borrowed_ids and min(result.size) > 0:
                    events.append({'operation': _method, 'source_mode': image.mode,
                        'mode': result.mode, 'size': result.size, 'image': result})
                return result
            stack.enter_context(patch.object(Image.Image, method, new=observed))
        for method in ('new', 'fromarray'):
            original = getattr(Image, method)
            def observed(*args, _method=method, _original=original, **kwargs):
                result = _original(*args, **kwargs)
                if id(result) not in borrowed_ids and min(result.size) > 0:
                    events.append({'operation': _method, 'source_mode': None,
                        'mode': result.mode, 'size': result.size, 'image': result})
                return result
            stack.enter_context(patch.object(Image, method, new=observed))
        try:
            yield events
        finally:
            for image in {id(row['image']): row['image'] for row in events}.values():
                image.close()


def operation_summary(events, size):
    counts = Counter((row['operation'], row['source_mode'], row['mode'])
                     for row in events if row['size'] == size)
    return {f'{operation}:{source or "-"}->{mode}': count
            for (operation, source, mode), count in sorted(counts.items(), key=str)}


@contextmanager
def source_variant(original, variant):
    mode = variant.split(':', 1)[0]
    with closing(original.convert(mode)) as source:
        if variant.endswith(':key'):
            source.info['transparency'] = source.getpixel((0, 0))
        elif variant.endswith(':alpha'):
            source.info['transparency'] = bytes(range(256))
        source.info['fixture'] = 'borrowed color source'
        yield source


SOURCE_VARIANTS = ('RGBA', 'RGB', 'RGB:key', 'L', 'L:key', 'LA', 'P', 'P:alpha', 'RGBa')


class SharedColorSourceTests(unittest.TestCase):
    def test_visible_pixels_alpha_and_region_samples_match_independent_source_masks(self):
        with closing(region_graphic((19, 13))) as original:
            labels = (np.arange(19 * 13, dtype=np.uint16).reshape(13, 19) % 5).astype(np.uint8)
            active = labels != 2
            for variant in SOURCE_VARIANTS:
                with self.subTest(variant=variant), source_variant(original, variant) as source, \
                        closing(Image.fromarray(labels)) as label_image:
                    before = source.tobytes(), dict(source.info)
                    with closing(source.convert('RGBA')) as rgba, \
                            closing(Image.new('RGBA', source.size, 'white')) as white:
                        white.alpha_composite(rgba)
                        with closing(white.convert('RGB')) as visible:
                            expected = np.asarray(visible)
                        with closing(rgba.getchannel('A')) as alpha:
                            expected_alpha = np.asarray(alpha)
                    samples = {int(label): measurement.measure_color_pixels(
                        expected[(labels == label) & active],
                        alpha_values=expected_alpha[(labels == label) & active])
                        for label in np.unique(labels[active])}
                    with measurement._ColorSourceAnalysis(source) as data:
                        visible = data.visible
                        np.testing.assert_array_equal(data.rgb, expected)
                        self.assertFalse(data.rgb.flags.writeable)
                        if data.alpha is not None:
                            np.testing.assert_array_equal(data.alpha, expected_alpha)
                            self.assertFalse(data.alpha.flags.writeable)
                        self.assertEqual(measurement.measure_quantized_regions(
                            source, label_image, drawable_mask=active, _source_data=data), samples)
                        self.assertEqual(measurement.measure_quantized_regions(
                            source, label_image, drawable_mask=active), samples)
                    self.assertFalse(image_is_open(visible))
                    self.assertIsNone(data.rgb)
                    self.assertIsNone(data.alpha)
                    self.assertIsNone(data.source)
                    self.assertEqual((source.tobytes(), source.info), before)

    def test_source_buffers_end_at_their_actual_last_consumers(self):
        for palette_only in (False, True):
            with self.subTest(palette_only=palette_only), closing(region_graphic((48, 36))) as source:
                observed = {}
                quantize, measure, region = dynamic._quantize_drawable, dynamic.measure_quantized_regions, dynamic.build_region_context
                merge = dynamic._merge_quantized
                def quantized(rgb, *args, **kwargs):
                    self.assertTrue(image_is_open(rgb))
                    observed['visible'] = rgb
                    result = quantize(rgb, *args, **kwargs)
                    observed['labels'] = result[0]
                    return result
                def measured(*args, **kwargs):
                    self.assertFalse(image_is_open(observed['visible']))
                    self.assertIsNotNone(kwargs['_source_data'].alpha)
                    return measure(*args, **kwargs)
                def regional(*args, **kwargs):
                    data = observed['data'] = kwargs['_source_data']
                    self.assertIsNone(data.alpha)
                    self.assertIsNotNone(data.rgb)
                    return region(*args, **kwargs)
                def merged(*args, **kwargs):
                    data = observed['data']
                    self.assertIsNone(data.rgb)
                    self.assertIsNone(data.source)
                    self.assertEqual(image_is_open(observed['labels']), not palette_only)
                    return merge(*args, **kwargs)
                with patch.object(dynamic, '_quantize_drawable', new=quantized), \
                        patch.object(dynamic, 'measure_quantized_regions', new=measured), \
                        patch.object(dynamic, 'build_region_context', new=regional), \
                        patch.object(dynamic, '_merge_quantized', new=merged):
                    result = dynamic.build_dynamic_color_strokes(source, PALETTE,
                        **dynamic_settings(), _palette_only=palette_only)
                self.assertTrue(result[-1]['region_aware_quantization'])
                self.assertFalse(image_is_open(observed['labels']))
                self.assertTrue(image_is_open(source))

    def test_direct_measurement_closes_visible_before_statistics_use_independent_exports(self):
        owner = measurement._ColorSourceAnalysis
        real_measure = measurement.measure_color_pixels
        visible = []
        class ObservedOwner(owner):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                visible.append(self.visible)
        def measured(*args, **kwargs):
            self.assertTrue(visible)
            self.assertFalse(image_is_open(visible[0]))
            return real_measure(*args, **kwargs)
        with closing(region_graphic((19, 13))) as source, \
                closing(Image.fromarray((np.arange(19*13).reshape(13, 19) % 3).astype(np.uint8))) as labels:
            expected = measurement.measure_quantized_regions(source, labels)
            with patch.object(measurement, '_ColorSourceAnalysis', ObservedOwner), \
                    patch.object(measurement, 'measure_color_pixels', new=measured):
                actual = measurement.measure_quantized_regions(source, labels)
            self.assertEqual(actual, expected)
            self.assertTrue(image_is_open(source))

    def test_shared_source_is_operation_local_and_parallel_calls_remain_independent(self):
        with closing(region_graphic((31, 23))) as first, closing(region_graphic((29, 19))) as second:
            with measurement._ColorSourceAnalysis(first) as data:
                with self.assertRaisesRegex(ValueError, 'different or finished'):
                    data.rgb_for(second)
                first_result = dynamic.build_dynamic_color_strokes(first, PALETTE, **dynamic_settings())
                second_result = dynamic.build_dynamic_color_strokes(second, PALETTE, **dynamic_settings())
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(dynamic.build_dynamic_color_strokes, source, PALETTE,
                        **dynamic_settings()) for source in (first, second)]
                    self.assertEqual([future.result() for future in futures], [first_result, second_result])
                self.assertIsNotNone(data.rgb)
            with self.assertRaisesRegex(ValueError, 'different or finished'):
                data.rgb_for(first)
            self.assertTrue(image_is_open(first))
            self.assertTrue(image_is_open(second))

    def test_retained_real_stage_errors_release_the_shared_rgb_export(self):
        owner = dynamic._ColorSourceAnalysis
        for boundary in ('drawable allocation', 'quantizer counts', 'region labels', 'local contrast'):
            with self.subTest(boundary=boundary), closing(region_graphic((24, 18))) as source:
                source.putalpha(255)
                exports = []
                retained = None
                state = {'region': False}
                class ObservedOwner(owner):
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        exports.append(weakref.ref(self.rgb))
                real_region = dynamic.build_region_context
                real_array = np.asarray
                def region(*args, **kwargs):
                    state['region'] = True
                    return real_region(*args, **kwargs)
                def arrays(value, *args, **kwargs):
                    if state['region'] and isinstance(value, Image.Image):
                        raise MemoryError('actual label-export allocation boundary')
                    return real_array(value, *args, **kwargs)
                with ExitStack() as stack:
                    stack.enter_context(patch.object(dynamic, '_ColorSourceAnalysis', ObservedOwner))
                    if boundary == 'drawable allocation':
                        stack.enter_context(patch.object(np, 'ones', side_effect=MemoryError('drawable allocation')))
                    elif boundary == 'quantizer counts':
                        stack.enter_context(patch.object(Image.Image, 'getcolors', side_effect=MemoryError('quantizer counts')))
                    elif boundary == 'region labels':
                        stack.enter_context(patch.object(dynamic, 'build_region_context', new=region))
                        stack.enter_context(patch.object(np, 'asarray', new=arrays))
                    else:
                        stack.enter_context(patch.object(np, 'abs', side_effect=MemoryError('contrast scratch allocation')))
                    try:
                        dynamic.build_dynamic_color_strokes(source, PALETTE, skip_white=False)
                    except MemoryError as error:
                        retained = error
                self.assertIsNotNone(retained)
                self.assertIsNotNone(retained.__traceback__)
                frames = []
                trace = retained.__traceback__
                while trace is not None:
                    frames.append(trace.tb_frame.f_code.co_name)
                    trace = trace.tb_next
                self.assertIn({'drawable allocation': '_drawable_source',
                    'quantizer counts': '_quantize_drawable', 'region labels': 'build_region_context',
                    'local contrast': '_local_importance'}[boundary], frames)
                self.assertEqual(len(exports), 1)
                self.assertIsNone(exports[0](), 'A completed owner survives through a source-array alias in the traceback')
                self.assertTrue(image_is_open(source))

    def test_direct_region_keeps_straight_rgb_and_releases_export_after_contrast_failure(self):
        with closing(region_graphic((24, 18))) as source, \
                closing(Image.fromarray((np.indices((18, 24))[1] % 2).astype(np.uint8))) as labels:
            source.putalpha(0)
            entries = [dict(qindex=i, rgb=PALETTE[i+2], count=216) for i in range(2)]
            with closing(source.convert('RGB')) as straight:
                expected = regions.build_region_context(straight, labels, entries)
            self.assertTrue(any(row.importance > 0 for row in expected['stats'].values()))
            self.assertEqual(regions.build_region_context(source, labels, entries), expected)
            exports = []
            retained = None
            real_array = np.asarray
            def arrays(value, *args, **kwargs):
                result = real_array(value, *args, **kwargs)
                if isinstance(value, Image.Image) and value.mode == 'RGB':
                    exports.append(weakref.ref(result))
                return result
            with patch.object(np, 'asarray', new=arrays), \
                    patch.object(np, 'abs', side_effect=MemoryError('contrast scratch allocation')):
                try:
                    regions.build_region_context(source, labels, entries)
                except MemoryError as error:
                    retained = error
            self.assertIsNotNone(retained.__traceback__)
            self.assertEqual(len(exports), 1)
            self.assertIsNone(exports[0]())
            self.assertTrue(image_is_open(source))

    def test_actual_standard_high_ultra_plans_do_not_reconvert_the_same_rgba_source(self):
        with closing(region_graphic()) as source, calibrated(PALETTE), \
                patch('ResourceAllocation.available_ram_mb', return_value=8192), \
                patch('ResourceAllocation.logical_cpu_count', return_value=8):
            before = source.tobytes(), dict(source.info)
            sizes = []
            real = dynamic.build_dynamic_color_strokes
            for resolution in ('Standard', 'High', 'Ultra'):
                with self.subTest(resolution=resolution):
                    settings = public_settings()
                    settings['planning_resolution'] = resolution
                    settings.update(cpu_workers='4', cpu_workers_resolved=4)
                    observations = []
                    def observed(image, *args, **kwargs):
                        with image_operations((image,)) as events:
                            result = real(image, *args, **kwargs)
                            observations.append((image.size, image.mode, operation_summary(events, image.size)))
                            return result
                    with patch.object(DrawBot, 'build_dynamic_color_strokes', new=observed):
                        plan = DrawBot.make_plan(source, (600, 450), settings)
                    try:
                        self.assertEqual(plan['options']['planning_resolution_effective'], resolution)
                        self.assertEqual(len(observations), 1)
                        size, mode, counts = observations[0]
                        sizes.append(size)
                        self.assertEqual(mode, 'RGBA')
                        self.assertEqual(plan['options']['advanced_color_meta']['mode'], 'dynamic-exact-v4')
                        self.assertEqual(counts.get('convert:RGBA->RGBA', 0), 0, counts)
                        self.assertEqual(sum(value for key, value in counts.items()
                                             if key.startswith('convert:') and key.endswith('->RGB')), 1, counts)
                        self.assertEqual(counts.get('getchannel:RGBA->L', 0), 1, counts)
                    finally:
                        close_plan(plan, source)
            self.assertEqual(len(set(sizes)), 3)
            self.assertEqual((source.tobytes(), source.info), before)

    def test_actual_dynamic_planner_stop_and_retained_error_close_every_private_image(self):
        for boundary in ('after quantization', 'after region measurement'):
            with self.subTest(boundary=boundary), closing(region_graphic((48, 36))) as source, calibrated(PALETTE):
                state = {'stop': False}
                captured = []
                retained = None
                quantize, measure = dynamic._quantize_drawable, dynamic.measure_quantized_regions
                build = dynamic.build_dynamic_color_strokes
                def quantized(*args, **kwargs):
                    result = quantize(*args, **kwargs)
                    if boundary == 'after quantization':
                        state['stop'] = True
                    return result
                def measured(*args, **kwargs):
                    result = measure(*args, **kwargs)
                    if boundary == 'after region measurement':
                        raise RuntimeError('controlled post-analysis failure')
                    return result
                def observed(image, *args, **kwargs):
                    with image_operations((image,)) as events:
                        try:
                            return build(image, *args, **kwargs)
                        finally:
                            captured.extend({'mode': row['mode'], 'size': row['size'],
                                'open_at_return': image_is_open(row['image'])} for row in events)
                with patch.object(dynamic, '_quantize_drawable', new=quantized), \
                        patch.object(dynamic, 'measure_quantized_regions', new=measured), \
                        patch.object(DrawBot, 'build_dynamic_color_strokes', new=observed):
                    try:
                        DrawBot.make_plan(source, source.size, public_settings(), cancelled=lambda: state['stop'])
                    except (InterruptedError, RuntimeError) as error:
                        retained = error
                self.assertIsNotNone(retained)
                self.assertIsNotNone(retained.__traceback__)
                self.assertTrue(captured)
                self.assertFalse([row for row in captured if row['open_at_return']], captured)
                self.assertTrue(image_is_open(source))

    def test_picture_analysis_is_closed_after_success_stop_and_retained_refinement_error(self):
        from PicturePaletteRefinement import refine_picture_palette
        for boundary in ('success', 'stop after analysis', 'refinement error'):
            with self.subTest(boundary=boundary), closing(region_graphic((48, 36))) as source:
                state = {'stop': False}
                analysis = []
                prepare = picture._analysis_image
                retained = None
                def prepared(*args, **kwargs):
                    result = prepare(*args, **kwargs)
                    analysis.append(result)
                    if boundary == 'stop after analysis':
                        state['stop'] = True
                    return result
                def refine(*args, **kwargs):
                    result = refine_picture_palette(*args, **kwargs)
                    if boundary == 'refinement error':
                        raise RuntimeError('controlled post-refinement failure')
                    return result
                try:
                    with patch.object(picture, '_analysis_image', new=prepared), \
                            patch.object(picture, 'load_cached_palette', return_value=None), \
                            patch.object(picture, 'save_palette'), \
                            patch('PicturePaletteRefinement.refine_picture_palette', new=refine):
                        try:
                            result = picture.build_picture_palette(source, PALETTE,
                                max_colors=8, cancelled=lambda: state['stop'])
                        except (InterruptedError, RuntimeError) as error:
                            retained = error
                        else:
                            self.assertEqual(boundary, 'success')
                            self.assertTrue(result.colors)
                    if boundary != 'success':
                        self.assertIsNotNone(retained)
                        self.assertIsNotNone(retained.__traceback__)
                    self.assertTrue(analysis)
                    self.assertFalse([image.size for image in analysis if image_is_open(image)])
                    self.assertTrue(image_is_open(source))
                finally:
                    for image in analysis:
                        image.close()

    def test_direct_measurement_and_quantizer_failures_close_private_images_with_tracebacks(self):
        for boundary in ('invalid labels', 'quantizer counts'):
            with self.subTest(boundary=boundary), closing(region_graphic((12, 9))) as source, \
                    image_operations((source,)) as events:
                retained = None
                try:
                    if boundary == 'invalid labels':
                        measurement.measure_quantized_regions(source, source)
                    else:
                        source.putalpha(255)
                        with patch.object(Image.Image, 'getcolors', side_effect=RuntimeError('count failure')):
                            dynamic.build_dynamic_color_strokes(source, PALETTE, skip_white=False)
                except (ValueError, RuntimeError) as error:
                    retained = error
                self.assertIsNotNone(retained)
                self.assertIsNotNone(retained.__traceback__)
                self.assertTrue(events)
                self.assertFalse([row['mode'] for row in events if image_is_open(row['image'])])
                self.assertTrue(image_is_open(source))

    def test_picture_fingerprint_strips_and_failed_thumbnail_release_owned_images(self):
        with closing(region_graphic((17, 401))) as source:
            with closing(source.convert('RGBA')) as rgba, closing(Image.new('RGBA', source.size, 'white')) as white:
                white.alpha_composite(rgba)
                with closing(white.convert('RGB')) as rgb:
                    expected = hashlib.sha256(b'17x401|RGB|' + rgb.tobytes()).hexdigest()
            for stopped in (False, True):
                with self.subTest(stopped=stopped), image_operations((source,)) as events:
                    def cancelled():
                        return stopped and any(row['operation'] == 'crop' for row in events)
                    if stopped:
                        with self.assertRaises(InterruptedError):
                            picture.image_fingerprint(source, cancelled=cancelled)
                    else:
                        self.assertEqual(picture.image_fingerprint(source), expected)
                    self.assertFalse([row['mode'] for row in events if image_is_open(row['image'])])
                    self.assertTrue(image_is_open(source))
        with closing(region_graphic((641, 3))) as source, image_operations((source,)) as events:
            retained = None
            with patch.object(Image.Image, 'thumbnail', side_effect=RuntimeError('thumbnail failure')):
                try:
                    picture._analysis_image(source)
                except RuntimeError as error:
                    retained = error
            self.assertIsNotNone(retained.__traceback__)
            self.assertFalse([row['mode'] for row in events if image_is_open(row['image'])])
            self.assertTrue(image_is_open(source))


if __name__ == '__main__':
    unittest.main()
