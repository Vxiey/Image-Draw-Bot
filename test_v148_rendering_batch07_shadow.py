from __future__ import annotations

from contextlib import closing
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageFilter

import ShadowDetailEngine as shadow
from PixelAccuratePlanner import build_pixel_map


def reference_maps(rgb, index, draw, edges):
    """Separate finite-difference/boundary oracle for the documented formulas."""
    f = rgb.astype(np.float32) / 255
    luma = f[..., 0] * .2126 + f[..., 1] * .7152 + f[..., 2] * .0722
    radius = max(2, min(18, round(min(luma.shape) / 48)))
    with closing(Image.fromarray(np.rint(luma * 255).astype(np.uint8))) as image:
        with closing(image.filter(ImageFilter.BoxBlur(radius))) as blurred:
            tone = np.asarray(blurred, np.float32) / 255
    relative = np.maximum(tone - luma, 0)
    scale = max(.025, float(np.percentile(relative[draw], 97))) if draw.any() else 1
    shade = np.clip(np.clip(relative / scale, 0, 1) * .76 +
                    np.clip((.68 - luma) / .68, 0, 1) * .24, 0, 1) * draw
    boundary = np.zeros(index.shape, np.float32)
    for y, x in np.ndindex(index.shape):
        if not draw[y, x]:
            continue
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < index.shape[0] and 0 <= nx < index.shape[1]:
                if not draw[ny, nx] or index[ny, nx] != index[y, x]:
                    boundary[y, x] = 1
    contour = np.clip(edges * .78 + boundary * .34, 0, 1) * draw
    gy = np.gradient(shade, axis=0) if shade.shape[0] > 1 else np.zeros_like(shade)
    gx = np.gradient(shade, axis=1) if shade.shape[1] > 1 else np.zeros_like(shade)
    gradient = np.sqrt(gx * gx + gy * gy)
    gradient = np.clip(gradient / max(1e-4, float(np.percentile(gradient, 99))), 0, 1)
    fine = np.clip(shade * (.30 + .70 * contour) + gradient * .56, 0, 1) * draw
    contour_threshold = max(.52, float(np.percentile(contour[draw], 86))) if draw.any() else .60
    shadow_threshold = max(.48, float(np.percentile(fine[draw], 84))) if draw.any() else .55
    return dict(luma_map=luma, local_tone_map=tone, shadow_map=shade, contour_map=contour,
                shadow_detail_map=fine, contour_mask=draw & (contour >= contour_threshold),
                shadow_detail_mask=draw & (fine >= shadow_threshold),
                deep_shadow_mask=draw & (shade >= max(.58, shadow_threshold * .88)))


class ShadowStorageTests(unittest.TestCase):
    def test_every_map_matches_independent_formulas_and_keeps_inputs_read_only(self):
        rng = np.random.default_rng(712)
        for height, width, empty in ((24, 32, False), (1, 19, False), (21, 1, False), (8, 9, True)):
            rgb = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
            index = rng.integers(0, 4, (height, width), dtype=np.int16)
            draw = np.zeros((height, width), bool) if empty else rng.random((height, width)) > .25
            edges = rng.random((height, width), dtype=np.float32)
            original = [value.copy() for value in (rgb, index, draw, edges)]
            for value in (rgb, index, draw, edges):
                value.flags.writeable = False
            expected = reference_maps(rgb, index, draw, edges)
            result = shadow.analyze_shadow_contours(rgb, index, draw, edges)
            with self.subTest(shape=(height, width), empty=empty):
                for key, value in expected.items():
                    np.testing.assert_array_equal(result[key], value, err_msg=key)
                self.assertEqual(result['metadata']['contour_pixels'], int(expected['contour_mask'].sum()))
                self.assertEqual(result['metadata']['shadow_detail_pixels'], int(expected['shadow_detail_mask'].sum()))
                for key in ('luma_map', 'local_tone_map', 'shadow_map', 'contour_map', 'shadow_detail_map'):
                    self.assertEqual(result[key].dtype, np.float32)
                    result[key].fill(0)
                for value, saved in zip((rgb, index, draw, edges), original):
                    np.testing.assert_array_equal(value, saved)

    def test_owned_luminance_and_local_tone_planes_are_transferred(self):
        retained = {}
        luma, blur = shadow._luma, shadow._box_blur
        def capture_luma(*args):
            retained['luma_map'] = luma(*args)
            return retained['luma_map']
        def capture_blur(*args):
            retained['local_tone_map'] = blur(*args)
            return retained['local_tone_map']
        with patch.object(shadow, '_luma', side_effect=capture_luma), \
                patch.object(shadow, '_box_blur', side_effect=capture_blur):
            result = shadow.analyze_shadow_contours(np.full((12, 16, 3), 128, np.uint8),
                np.zeros((12, 16), np.int16), np.ones((12, 16), bool), np.zeros((12, 16), np.float32))
        for key, plane in retained.items():
            self.assertIs(result[key], plane)

    def test_actual_pixel_map_retains_guidance_without_changing_source(self):
        rgb = np.tile(np.arange(32, dtype=np.uint8)[None, :, None] * 8, (24, 1, 3))
        retained = {}
        original = shadow.analyze_shadow_contours
        def capture(*args, **kwargs):
            retained.update(original(*args, **kwargs))
            return retained
        with closing(Image.fromarray(rgb)) as image, patch.object(shadow, 'analyze_shadow_contours', side_effect=capture):
            pixel_map = build_pixel_map(image, ((0, 0, 0), (128, 128, 128), (255, 255, 255)),
                                        gpu_mode='CPU', skip_white=False)
            self.assertEqual(image.tobytes(), rgb.tobytes())
        expected = reference_maps(pixel_map.rgb, pixel_map.palette_index, pixel_map.drawable_mask, pixel_map.edge_map)
        for key in ('contour_map', 'shadow_map', 'shadow_detail_map'):
            self.assertIs(getattr(pixel_map, key), retained[key])
            np.testing.assert_array_equal(getattr(pixel_map, key), expected[key])
        self.assertTrue(pixel_map.protected_mask.any())

    def test_owned_blur_images_really_close(self):
        images = []
        fromarray, filter_image = Image.fromarray, Image.Image.filter
        def capture_fromarray(*args, **kwargs):
            image = fromarray(*args, **kwargs)
            images.append(image)
            return image
        def capture_filter(image, *args, **kwargs):
            result = filter_image(image, *args, **kwargs)
            images.append(result)
            return result
        with patch.object(Image, 'fromarray', side_effect=capture_fromarray), \
                patch.object(Image.Image, 'filter', new=capture_filter):
            result = shadow._box_blur(np.full((5, 6), .5, np.float32), 2)
        self.assertEqual(len(images), 2)
        for image in images:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))
        self.assertAlmostEqual(float(result[0, 0]), 128 / 255, places=7)


if __name__ == '__main__':
    unittest.main()
