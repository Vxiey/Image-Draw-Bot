import hashlib
import random
import unittest
from collections.abc import Sequence
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdaptiveDetail as AD
import DrawingStyleProfiles as DSP
import FastDryRun as FDR
import PixelAccuratePlanner as PAP
import PixelStrokeEngine as PSE
import ProgressiveRenderer as PR
import StatefulFillSimulation as SFS


def pixel_map(indices, drawable=None, edge=None, **extra):
    idx = np.asarray(indices)
    height, width = idx.shape
    mask = np.ones(idx.shape, dtype=np.bool_) if drawable is None else np.asarray(drawable, dtype=np.bool_)
    values = np.zeros(idx.shape, dtype=np.float32) if edge is None else np.asarray(edge, dtype=np.float32)
    return PAP.PixelMap(width, height, np.zeros((height, width, 3), dtype=np.uint8), idx, mask,
                        values, values, np.zeros(idx.shape, dtype=np.bool_), {}, **extra)


class PaletteTileTests(unittest.TestCase):
    def test_scalar_policy_oracles_and_verified_outputs_are_tile_independent(self):
        from ColorFidelity import palette_match_cost

        rng = np.random.default_rng(148)
        rgb = rng.integers(0, 256, (15, 19, 3), dtype=np.uint8)
        palette = rng.integers(0, 256, (17, 3), dtype=np.uint8)
        digests = {
            (False, 'Faithful'): '85977be025c86e402ab5843cb750de27e04d7593c3066542cbe8c66dd04c9eb0',
            (True, 'Faithful'): '3dd8841e2502b61f33b4e0bd6516429bc83d45317f3376cc57908ec6fbd3f9b2',
            (True, 'Balanced'): '30e69407e034b0306ad25d32aa5993e86eaf87a7f5efdaafb58044ba7c6ecf13',
            (True, 'Off'): 'f46eb5d40684e2c0cebf38f703f7ca53746cb1135e933f15fbefa466446c2ef6',
        }
        for (perceptual, fidelity), digest in digests.items():
            # Scalar double-precision ColorFidelity is independent of the
            # vectorized fallback and its tile layout. CP01 intentionally
            # corrects the old near-neutral hue-family penalty in Balanced
            # and Faithful; RGB-nearest and unweighted OKLab stay unchanged.
            colors = [tuple(map(int, color)) for color in palette]
            expected = np.asarray([
                min(range(len(colors)), key=lambda index: palette_match_cost(
                    tuple(map(int, pixel)), colors[index],
                    color_rendering='Perceptual match' if perceptual else 'RGB nearest',
                    fidelity='Exact' if fidelity == 'Off' else fidelity))
                for pixel in rgb.reshape(-1, 3)
            ], dtype=np.int16).reshape(rgb.shape[:2])
            self.assertEqual(hashlib.sha256(expected.astype('<i2').tobytes()).hexdigest(), digest)
            for chunk in (1, 4, 96):
                actual = PAP._cpu_palette_map(rgb, palette, perceptual=perceptual,
                                              color_fidelity=fidelity, row_chunk=chunk)
                np.testing.assert_array_equal(actual, expected)
        direct = np.argmin(np.sum((rgb.astype(np.int32)[:, :, None] - palette.astype(np.int32)) ** 2, axis=3), axis=2)
        np.testing.assert_array_equal(PAP._cpu_palette_map(rgb, palette, perceptual=False), direct)

    def test_wide_noncontiguous_images_use_bounded_tiles_and_exact_matches(self):
        palette = np.repeat(np.arange(96, dtype=np.uint8)[:, None] * 2, 3, axis=1)
        indices = np.arange(12000).reshape(2, 6000) % 96
        image = palette[indices][:, ::-1]
        expected = indices[:, ::-1]
        observed = []
        original = PAP._to_oklab
        def convert(array):
            if array.ndim == 3:
                observed.append(array.shape[0] * array.shape[1] * len(palette))
            return original(array)
        with patch.object(PAP, '_to_oklab', side_effect=convert):
            for fidelity in ('Balanced', 'Faithful', 'Off'):
                result = PAP._cpu_palette_map(image, palette, perceptual=True, color_fidelity=fidelity)
                np.testing.assert_array_equal(result, expected)
        self.assertGreater(len(observed), 3)
        self.assertLessEqual(max(observed), 262144)


class PixelMapIntegrityTests(unittest.TestCase):
    def test_unsigned_palette_indices_keep_a_signed_background_sentinel(self):
        for dtype in (np.uint8, np.uint16, np.uint32, np.uint64):
            source = pixel_map(np.array([[0, np.iinfo(dtype).max, 1]], dtype=dtype), [[True, False, True]])
            for lines in (False, True):
                self.assertEqual(PAP.groups_from_pixel_map(source, 2, lines=lines),
                                 [[(0, 0, 0, 0)], [(2, 0, 2, 0)]])

    def test_invalid_drawable_indices_fail_for_dots_and_lines(self):
        for index in (-1, 2):
            for lines in (False, True):
                with self.assertRaises(ValueError):
                    PAP.groups_from_pixel_map(pixel_map([[index]], edge=[[0]]), 2, lines=lines)
        for lines in (False, True):
            self.assertEqual(PAP.groups_from_pixel_map(pixel_map([[-1]], [[False]]), 2, lines=lines), [[], []])
        with self.assertRaises(ValueError):
            PAP.groups_from_pixel_map(pixel_map([[.5]]), 2)
        malformed = pixel_map([[0]])
        malformed.width = 2
        with self.assertRaises(ValueError):
            PAP.groups_from_pixel_map(malformed, 2)

    def test_optional_shadow_statistics_do_not_allocate_zero_arrays_per_run(self):
        source = pixel_map([[0, 0, 1], [0, 1, 1]], edge=[[.25, .5, .75], [.75, .25, .5]])
        with patch.object(PSE.np, 'zeros_like', side_effect=AssertionError('unnecessary shadow allocation')):
            components, mapping, _ = PSE.connected_components(source)
        self.assertEqual([row.area for row in components], [3, 3])
        self.assertEqual([row.shadow_mean for row in components], [0.0, 0.0])
        self.assertEqual([row.shadow_detail_mean for row in components], [0.0, 0.0])
        np.testing.assert_array_equal(mapping, [[0, 0, 1], [0, 1, 1]])
        source.shadow_map = np.full((2, 3), .375, dtype=np.float32)
        source.shadow_detail_map = np.full((2, 3), .625, dtype=np.float32)
        components, _, _ = PSE.connected_components(source)
        self.assertEqual([row.shadow_mean for row in components], [.375, .375])
        self.assertEqual([row.shadow_detail_mean for row in components], [.625, .625])


class FillSimulationIntegrityTests(unittest.TestCase):
    def region(self):
        return {'row_spans': [(y, 1, 10) for y in range(1, 11)],
                'contour': [(1, 1), (5, 1), (5, 5), (1, 5), (1, 1)], 'seed_pixel': (3, 3)}

    def test_nonfinite_missing_tolerance_cannot_approve_incomplete_fill(self):
        rejected, _ = SFS.simulate_fill_region(self.region(), (12, 12))
        self.assertFalse(rejected.safe)
        self.assertEqual(rejected.missing_percent, 75.0)
        for tolerance in (float('nan'), float('inf'), -1, 101):
            with self.assertRaises(ValueError):
                SFS.simulate_fill_region(self.region(), (12, 12), max_missing_percent=tolerance)

    def test_precancelled_simulation_does_not_allocate_masks(self):
        with patch.object(SFS, '_mask_from_spans', side_effect=AssertionError('allocated before cancellation')):
            with self.assertRaises(InterruptedError):
                SFS.simulate_fill_region(self.region(), (12000, 12000), cancelled=lambda: True)
        with patch.object(SFS.np, 'zeros', side_effect=AssertionError('allocated before cancellation')):
            with self.assertRaises(InterruptedError):
                SFS.filter_stateful_fill_regions([], (12000, 12000), cancelled=lambda: True)

    def test_long_off_canvas_contour_cancels_with_bounded_progress(self):
        calls = 0
        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 4
        region = {'contour': [(0, 0), (100000000, 0), (100000000, 2), (0, 0)]}
        with self.assertRaises(InterruptedError):
            SFS._contour_wall(region, (5, 5), 1, cancelled=cancelled)
        self.assertEqual(calls, 4)


class AdaptiveCancellationTests(unittest.TestCase):
    def test_precancelled_off_mode_does_not_convert_full_image(self):
        image = Image.new('RGB', (8, 8))
        with patch.object(image, 'convert', side_effect=AssertionError('converted cancelled image')):
            with self.assertRaises(InterruptedError):
                AD.apply_adaptive_detail(image, 'Off', cancelled=lambda: True)

    def test_cancel_during_composite_does_not_publish_processed_image(self):
        image = Image.new('RGB', (8, 8))
        stopped = False
        original = Image.composite
        def composite(*args, **kwargs):
            nonlocal stopped
            value = original(*args, **kwargs)
            stopped = True
            return value
        with patch.object(Image, 'composite', side_effect=composite):
            with self.assertRaises(InterruptedError):
                AD.apply_adaptive_detail(image, 'Strong simplify', cancelled=lambda: stopped)


class BoundedSamplingTests(unittest.TestCase):
    def test_dryrun_reads_only_selected_sequence_items(self):
        class IndexedOnly(Sequence):
            def __len__(self):
                return 1000000
            def __getitem__(self, index):
                if 0 <= index < len(self):
                    return index
                raise IndexError(index)
            def __iter__(self):
                raise AssertionError('copied every source item')
        self.assertEqual(FDR.sample_items(IndexedOnly(), 8),
                         [0, 142857, 285714, 428571, 571428, 714285, 857142, 999999])
        self.assertEqual(FDR.sample_items(iter(range(10)), 3), [0, 4, 9])

    def test_style_metrics_preserve_rgb_rgba_palette_and_monochrome_sampling(self):
        rng = np.random.default_rng(148)
        image = Image.fromarray(rng.integers(0, 256, (249, 387, 4), dtype=np.uint8))
        sources = [image, image.convert('RGB'), image.convert('L'), image.convert('P'), image.convert('1')]
        sources[3].info['transparency'] = 0
        for source in sources:
            before = source.tobytes()
            reference = source.convert('RGBA')
            reference.thumbnail((160, 160), Image.Resampling.NEAREST)
            self.assertEqual(DSP._metrics(source), DSP._metrics(reference))
            self.assertEqual(source.tobytes(), before)
        converted_sizes = []
        original = Image.Image.convert
        def tracked(source, mode=None, *args, **kwargs):
            if mode == 'RGBA':
                converted_sizes.append(source.size)
            return original(source, mode, *args, **kwargs)
        with patch.object(Image.Image, 'convert', tracked):
            DSP._metrics(image.convert('RGB'))
        self.assertTrue(converted_sizes)
        self.assertLessEqual(max(max(size) for size in converted_sizes), 160)

    def test_progressive_metrics_match_independent_existing_geometry_helpers(self):
        rng = random.Random(148)
        paths = [tuple((rng.randrange(-50, 80), rng.randrange(-50, 80)) for _ in range(rng.randrange(1, 35)))
                 for _ in range(100)]
        def separate(path):
            return PR._path_len(path), PR._bbox_area(path), PR._center(path)
        with patch.object(PR, '_path_metrics', side_effect=separate):
            reference = PR.build_progressive_sequence([paths])
        self.assertEqual(PR.build_progressive_sequence([paths]), reference)
        with patch.object(PR, '_path_len', side_effect=AssertionError('repeated length scan')):
            with patch.object(PR, '_bbox_area', side_effect=AssertionError('repeated bounds scan')):
                sequence, _ = PR.build_progressive_sequence([[((0, 0), (100, 0)), ((3, 3),)]])
        self.assertEqual([row['phase'] for row in sequence], ['foundation', 'details'])


if __name__ == '__main__':
    unittest.main()
