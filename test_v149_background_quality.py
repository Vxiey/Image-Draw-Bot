"""Background removal preserves cutouts and native detail on shipped PNGs."""
from contextlib import closing
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import BackgroundRemoval as background

ROOT = Path(__file__).resolve().parent


class NativeBackgroundQualityTests(unittest.TestCase):
    def test_cutout_with_a_narrow_clear_border_retains_every_edge_opacity(self):
        with Image.open(ROOT / 'assets/image-draw-bot-icon.png') as source:
            pixels = source.tobytes()
            alpha = np.asarray(source)[..., 3]
            self.assertLess(np.count_nonzero(alpha == 0), alpha.size * 0.20)
            self.assertGreater(np.count_nonzero((alpha > 0) & (alpha < 255)), 1000)
            with patch.object(background, '_grow', side_effect=AssertionError('already cut out')):
                first = background.remove_background(source)
                with closing(first.image):
                    self.assertEqual(first.image.tobytes(), pixels)
                    self.assertEqual(first.metadata['removed_pixels'], 0)
                    second = background.remove_background(first.image)
                    with closing(second.image):
                        self.assertEqual(second.image.tobytes(), pixels)
            self.assertEqual(source.tobytes(), pixels)

    def test_feather_gradation_never_reintroduces_exterior_background(self):
        with Image.open(ROOT / 'golden-regression/red-bananas-texture.png') as source:
            hard = background.remove_background(source, feather_px=0)
            with closing(hard.image):
                soft = background.remove_background(source)
                with closing(soft.image):
                    hard_alpha = np.asarray(hard.image)[..., 3]
                    soft_alpha = np.asarray(soft.image)[..., 3]
                    self.assertTrue(np.all(soft_alpha[hard_alpha == 0] == 0))
                    self.assertTrue(np.all(soft_alpha[hard_alpha != 0] >= 128))
                    self.assertGreater(np.unique(soft_alpha).size, 8)
                    np.testing.assert_array_equal(np.asarray(soft.image)[..., :3], np.asarray(source)[..., :3])

    def test_mode_bounds_apply_to_relaxed_growth_and_full_resolution_feather(self):
        with Image.open(ROOT / 'golden-regression/red-bananas-texture.png') as source:
            rgba = np.asarray(source)
            luma = background._luma(rgba[..., :3])
            for mode, protected in [('Light background', luma < 135), ('Dark background', luma > 120)]:
                for limit in (1200, 180):
                    with self.subTest(mode=mode, proxy_max_dimension=limit), \
                            patch.object(background, '_PROXY_MAX_DIMENSION', limit):
                        result = background.remove_background(source, mode=mode)
                        with closing(result.image):
                            alpha = np.asarray(result.image)[..., 3]
                            np.testing.assert_array_equal(alpha[protected], rgba[..., 3][protected])
                            self.assertGreater(np.count_nonzero(alpha == 0), 1000)


if __name__ == '__main__':
    unittest.main()
