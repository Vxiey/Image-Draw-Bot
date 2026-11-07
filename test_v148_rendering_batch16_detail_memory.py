"""Detail-preview scratch reductions preserve exact pixels and complete plans."""
from contextlib import ExitStack, closing, contextmanager
import copy
import sys
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image, ImageFilter, ImageOps

import DrawBot
import PreviewDetailEngine as detail
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch15_prepare import image_state
from test_v148_rendering_batch15_sketch_memory import (
    comparable_plan, graphic_source, planner_options,
)


def reference_cell(rgb, base_rgb, factor, dark_bias):
    """Select each cell independently, without the packed RGB cell layout."""
    height, width = base_rgb.shape[:2]
    luma = rgb[..., 0]*.299 + rgb[..., 1]*.587 + rgb[..., 2]*.114
    base_luma = base_rgb[..., 0]*.299 + base_rgb[..., 1]*.587 + base_rgb[..., 2]*.114
    chosen = np.empty_like(base_rgb)
    contrast = np.empty((height, width), dtype=np.float32)
    for y in range(height):
        for x in range(width):
            cell = luma[y*factor:(y+1)*factor, x*factor:(x+1)*factor].reshape(-1)
            deviation = np.abs(cell - base_luma[y, x])
            dark = np.clip(base_luma[y, x] - cell, 0.0, 255.0)
            index = int(np.argmax(deviation + dark*float(dark_bias)))
            chosen[y, x] = rgb[y*factor + index//factor, x*factor + index%factor]
            contrast[y, x] = cell.max() - cell.min()
    return chosen, contrast


def reference_resize(image, size, mode='Detailed', *, cancelled=lambda: False, metadata=None):
    """Baseline resampling/float32 expressions with the independent cell oracle.

    The standalone benchmark also loads the entire recorded historical module;
    this portable reference needs neither Git history nor network access.
    """
    detail.validate_preview_detail_mode(mode)
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    profile = detail._PROFILES[mode]
    factor = detail._bounded_factor((w, h), profile.oversample)
    if cancelled():
        raise InterruptedError()
    owned = []
    result = None
    try:
        source = ImageOps.exif_transpose(image) if image.getexif().get(274, 1) not in (None, 1) else image
        if source is not image:
            owned.append(source)
        if factor <= 1 or profile.recovery_strength <= 0:
            out = detail._resize_rgba(source, (w, h)); owned.append(out)
            if cancelled():
                raise InterruptedError()
            if metadata is not None:
                metadata.update(preview_detail_mode=mode, preview_detail_oversample=1,
                    preview_detail_recovered_cells=0, preview_detail_recovered_percent=0.0,
                    preview_detail_threshold=int(profile.threshold))
            result = out
            return result
        hi = detail._resize_rgba(source, (w*factor, h*factor)); owned.append(hi)
        arr = np.asarray(hi, dtype=np.uint8)
        if cancelled():
            raise InterruptedError()
        alpha = arr[..., 3:4].astype(np.float32)/255.0
        visible = arr[..., :3].astype(np.float32)*alpha + 255.0*(1.0-alpha)
        base = hi.resize((w, h), Image.Resampling.LANCZOS); owned.append(base)
        base_arr = np.asarray(base, dtype=np.uint8).astype(np.float32)
        base_alpha = base_arr[..., 3:4]/255.0
        base_visible = base_arr[..., :3]*base_alpha + 255.0*(1.0-base_alpha)
        chosen, contrast = reference_cell(visible, base_visible, factor, profile.dark_bias)
        if cancelled():
            raise InterruptedError()
        active = contrast >= float(profile.threshold)
        strength = np.clip((contrast-profile.threshold)/max(1.0, 90.0-profile.threshold), 0.0, 1.0)
        strength = (.20+.80*strength)*float(profile.recovery_strength)
        strength *= active.astype(np.float32)
        mixed = base_visible*(1.0-strength[..., None]) + chosen*strength[..., None]
        mixed = np.rint(mixed).clip(0, 255).astype(np.uint8)
        out_arr = np.asarray(base, dtype=np.uint8).copy()
        a = out_arr[..., 3:4].astype(np.float32)/255.0
        denom = np.maximum(a, 1.0/255.0)
        straight = (mixed.astype(np.float32)-255.0*(1.0-a))/denom
        straight = np.where(a > 0.0, straight, out_arr[..., :3].astype(np.float32))
        out_arr[..., :3] = np.rint(straight).clip(0, 255).astype(np.uint8)
        out = Image.fromarray(out_arr, mode='RGBA'); owned.append(out)
        if profile.sharpen_percent > 0:
            alpha_channel = out.getchannel('A'); owned.append(alpha_channel)
            out = out.filter(ImageFilter.UnsharpMask(radius=.55, percent=profile.sharpen_percent, threshold=2))
            owned.append(out)
            out.putalpha(alpha_channel)
        if cancelled():
            raise InterruptedError()
        if metadata is not None:
            recovered = int(np.count_nonzero(active))
            metadata.update(preview_detail_mode=mode, preview_detail_oversample=factor,
                preview_detail_recovered_cells=recovered,
                preview_detail_recovered_percent=round(recovered*100.0/max(1, w*h), 3),
                preview_detail_threshold=int(profile.threshold),
                preview_detail_max_local_contrast=round(float(np.max(contrast)) if contrast.size else 0.0, 2))
        result = out
        return result
    finally:
        for image in reversed(owned):
            if image is not result:
                image.close()


def preview_settings(mode, *, outline=False):
    settings = planner_options('Standard / pixel', quality='Balanced')
    settings.update(outline=outline, preview_detail_level=mode, planning_resolution='Standard')
    settings = DrawBot.preview_safe_options(settings, 'Manual')
    settings.update(_preview_plan=True, _preview_mode='Manual')
    return settings


@contextmanager
def observed_images():
    owned = []
    original = detail._detail_aware_resize
    def record(*args, **kwargs):
        owned.append(kwargs['_owned'])
        return original(*args, **kwargs)
    with patch.object(detail, '_detail_aware_resize', new=record):
        yield owned


class DetailPreviewScratchTests(unittest.TestCase):
    def assert_closed(self, images, retained=()):
        identities = {id(image) for image in retained}
        for image in images:
            if id(image) not in identities:
                with self.assertRaises(ValueError):
                    image.getpixel((0, 0))

    def test_cell_selection_and_first_ties_match_independent_cells(self):
        rng = np.random.default_rng(1481602)
        for height, width in ((1, 1), (1, 7), (9, 1), (3, 5), (17, 23)):
            for factor in (1, 2, 3):
                rgb = rng.random((height*factor, width*factor, 3), dtype=np.float32)*255.0
                base = rng.random((height, width, 3), dtype=np.float32)*255.0
                # Include non-contiguous, read-only inputs as well as ordinary arrays.
                for pixels in (rgb, rgb[:, ::-1]):
                    pixels.flags.writeable = False
                    base.flags.writeable = False
                    original = pixels.tobytes(), base.tobytes()
                    for bias in (0., .06, .10, .14):
                        with self.subTest(shape=(height, width), factor=factor, bias=bias):
                            expected = reference_cell(pixels, base, factor, bias)
                            actual = detail._cell_extreme(pixels, base, factor, bias)
                            for result, reference in zip(actual, expected):
                                np.testing.assert_array_equal(result, reference)
                                self.assertEqual(result.dtype, np.float32)
                                self.assertFalse(np.shares_memory(result, pixels))
                            self.assertEqual((pixels.tobytes(), base.tobytes()), original)
        for factor in (2, 3):
            for first in (0., 255.):
                rgb = np.full((factor, factor, 3), 255.-first, dtype=np.float32)
                rgb[0, 0] = first
                chosen, contrast = detail._cell_extreme(rgb, np.full((1, 1, 3), 127.5, np.float32), factor, 0.)
                np.testing.assert_array_equal(chosen, np.full((1, 1, 3), first, np.float32))
                self.assertEqual(float(contrast[0, 0]), 255.)

    def test_full_rgba_pixels_metadata_and_source_ownership_match_original_pipeline(self):
        rng = np.random.default_rng(1481603)
        pixels = rng.integers(0, 256, (19, 27, 4), dtype=np.uint8)
        pixels[::3, :, 3] = 0
        pixels[1::3, :, 3] = 255
        pixels.flags.writeable = False
        with closing(Image.fromarray(pixels)) as original:
            for mode in ('RGBA', 'RGB', 'L', 'LA', 'P', 'RGBa'):
                for orientation in (1, 6, 8):
                    with closing(original.convert(mode)) as source:
                        if mode == 'P':
                            source.info['transparency'] = bytes(range(256))
                        elif mode in ('RGB', 'L'):
                            source.info['transparency'] = source.getpixel((1, 1))
                        source.getexif()[274] = orientation
                        source.info['exif'] = source.getexif().tobytes()
                        before = image_state(source)
                        for profile in detail.PREVIEW_DETAIL_MODES:
                            with self.subTest(mode=mode, orientation=orientation, profile=profile):
                                old_meta = {'retained': 7}; new_meta = dict(old_meta)
                                with closing(reference_resize(source, (9, 7), profile, metadata=old_meta)) as expected, \
                                        closing(detail.detail_aware_resize(source, (9, 7), profile, metadata=new_meta)) as actual:
                                    self.assertEqual(image_state(actual), image_state(expected))
                                    self.assertEqual(new_meta, old_meta)
                                self.assertEqual(image_state(source), before)

    def test_bounded_oversampling_and_gray_path_keep_complete_output(self):
        with closing(graphic_source((30, 22))) as source:
            for cap, factor in ((25, 1), (100, 2), (225, 3)):
                with self.subTest(factor=factor), patch.object(detail, '_MAX_OVERSAMPLED_PIXELS', cap):
                    old_meta = {}; new_meta = {}
                    with closing(reference_resize(source, (5, 5), 'Micro detail', metadata=old_meta)) as expected, \
                            closing(detail.detail_aware_resize(source, (5, 5), 'Micro detail', metadata=new_meta)) as actual:
                        self.assertEqual(image_state(actual), image_state(expected))
                        self.assertEqual(new_meta, old_meta)
                        self.assertEqual(new_meta['preview_detail_oversample'], factor)
            for profile in detail.PREVIEW_DETAIL_MODES:
                old_meta = {}; new_meta = {}
                with patch.object(detail, 'detail_aware_resize', new=reference_resize):
                    expected = detail.detail_aware_resize_gray(source, (11, 8), profile, metadata=old_meta)
                with closing(expected), closing(detail.detail_aware_resize_gray(source, (11, 8), profile, metadata=new_meta)) as actual:
                    self.assertEqual(image_state(actual), image_state(expected))
                    self.assertEqual(new_meta, old_meta)

    def test_cell_selection_avoids_an_independent_oversampled_rgb_cell_copy(self):
        observations = []
        argmax = np.argmax
        def inspect(*args, **kwargs):
            frame = sys._getframe(1)
            if frame.f_code is detail._cell_extreme.__code__:
                rgb = frame.f_locals['rgb']
                copied_rgb = [value.nbytes for value in frame.f_locals.values()
                              if isinstance(value, np.ndarray) and value.ndim == 4
                              and value.shape[-1] == 3 and value.size == rgb.size
                              and not np.shares_memory(value, rgb)]
                observations.append(copied_rgb)
            return argmax(*args, **kwargs)
        with closing(graphic_source((96, 72))) as source, patch.object(np, 'argmax', new=inspect):
            with closing(detail.detail_aware_resize(source, (32, 24), 'Micro detail')):
                pass
        self.assertEqual(observations, [[]])

    def test_selection_buffers_are_dead_before_straight_alpha_output(self):
        references = []; observations = []
        extreme = detail._cell_extreme
        where = np.where
        def record(rgb, base_rgb, *args):
            references.extend((weakref.ref(rgb), weakref.ref(base_rgb)))
            result = extreme(rgb, base_rgb, *args)
            references.extend(weakref.ref(value) for value in result)
            return result
        def inspect(*args, **kwargs):
            if sys._getframe(1).f_code.co_name == '_detail_aware_resize':
                observations.append([reference() is None for reference in references])
            return where(*args, **kwargs)
        with closing(graphic_source((96, 72))) as source, \
                patch.object(detail, '_cell_extreme', new=record), patch.object(np, 'where', new=inspect):
            with closing(detail.detail_aware_resize(source, (32, 24), 'Micro detail', metadata={})):
                pass
        self.assertEqual(observations, [[True, True, True, True]])

    def test_stop_failure_and_success_release_only_owned_images(self):
        with closing(graphic_source((64, 48))) as source:
            original = image_state(source)
            for stop_at in range(1, 5):
                checks = []; failures = []
                def cancelled():
                    checks.append(None)
                    return len(checks) == stop_at
                with self.subTest(stop_at=stop_at), observed_images() as owned:
                    try:
                        detail.detail_aware_resize(source, (20, 16), 'Micro detail', cancelled=cancelled)
                    except InterruptedError as error:
                        failures.append(error)
                    self.assertEqual(len(failures), 1)
                    self.assert_closed([image for group in owned for image in group])
                    self.assertEqual(image_state(source), original)
            failure = MemoryError('injected selection failure'); caught = []
            with observed_images() as owned, patch.object(detail, '_cell_extreme', side_effect=failure):
                try:
                    detail.detail_aware_resize(source, (20, 16), 'Micro detail')
                except MemoryError as error:
                    caught.append(error)
                self.assertEqual(caught, [failure])
                self.assert_closed([image for group in owned for image in group])
            with observed_images() as owned:
                result = detail.detail_aware_resize(source, (20, 16), 'Micro detail')
                with closing(result):
                    self.assert_closed([image for group in owned for image in group], (result,))
                    result.putpixel((0, 0), (1, 2, 3, 4))
                    self.assertEqual(image_state(source), original)

    def test_actual_bounded_preview_planners_preserve_every_stable_plan_field(self):
        for profile in ('Detailed', 'Micro detail'):
            for outline in (False, True):
                with self.subTest(profile=profile, outline=outline), ExitStack() as stack:
                    source = stack.enter_context(closing(graphic_source((96, 72))))
                    original = image_state(source)
                    settings = preview_settings(profile, outline=outline)
                    stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
                    stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
                    with patch.object(detail, 'detail_aware_resize', new=reference_resize):
                        expected = DrawBot.make_plan(source, (64, 48), copy.deepcopy(settings))
                    stack.callback(close_plan, expected, source)
                    with patch.object(detail, 'detail_aware_resize', wraps=detail.detail_aware_resize) as reached:
                        actual = DrawBot.make_plan(source, (64, 48), copy.deepcopy(settings))
                    stack.callback(close_plan, actual, source)
                    self.assertEqual(reached.call_count, 1)
                    self.assertGreater(actual['count'], 0)
                    self.assertEqual(actual['options']['preview_detail_meta']['preview_detail_mode'], profile)
                    self.assertEqual(comparable_plan(actual), comparable_plan(expected))
                    self.assertEqual(image_state(source), original)


if __name__ == '__main__':
    unittest.main()
