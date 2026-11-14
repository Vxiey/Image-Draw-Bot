import copy
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import DetailZoomPass as zoom


class DetailZoomPhysicalQualityTests(unittest.TestCase):
    palette = ((255, 255, 255), (0, 0, 0), (255, 0, 0), (100, 100, 100))

    def source(self, size=(9, 9)):
        image = Image.new('RGB', size, 'white')
        self.addCleanup(image.close)
        return image

    def entry(self, path=((4, 4),), color=1, brush=1):
        return dict(path=path, color_index=color, brush_px=brush)

    def admit(self, source, proposals, base=(), work=None, **options):
        return zoom._quality_safe_zoom_proposals(source, base, proposals, self.palette,
            dict(dict(brush_px=1, _planning_canvas_size=(source.width + 8, source.height + 8)), **options), work or source.size, source.size, lambda: False)

    def test_beneficial_physical_dot_is_admitted(self):
        source = self.source(); source.putpixel((4, 4), (0, 0, 0))
        entries = [self.entry()]
        selected, meta = self.admit(source, entries)
        self.assertEqual(selected, entries)
        self.assertEqual(meta['admitted_paths'], 1)

    def test_wide_brush_cannot_destroy_neighboring_white_pixels(self):
        source = self.source(); source.putpixel((4, 4), (0, 0, 0))
        selected, meta = self.admit(source, [self.entry(brush=3)])
        self.assertEqual(selected, [])
        self.assertEqual(meta['rejected_paths'], 1)

    def test_wide_brush_is_accepted_when_entire_footprint_improves(self):
        source = self.source(); ImageDraw.Draw(source).rectangle((3, 3, 5, 5), fill='black')
        entries = [self.entry(brush=3)]
        self.assertEqual(self.admit(source, entries)[0], entries)

    def test_even_brush_preserves_established_asymmetric_footprint(self):
        source = self.source(); ImageDraw.Draw(source).rectangle((4, 4, 5, 5), fill='black')
        entries = [self.entry(brush=2)]
        self.assertEqual(self.admit(source, entries)[0], entries)

    def test_existing_correct_neighbor_cannot_be_repainted(self):
        source = self.source(); source.putpixel((4, 4), (0, 0, 0)); source.putpixel((5, 4), (255, 0, 0))
        base = [self.entry(((5, 4),), color=2)]
        self.assertEqual(self.admit(source, [self.entry(brush=3)], base)[0], [])

    def test_simulates_actual_base_not_working_image_or_palette_match(self):
        source = self.source(); source.putpixel((4, 4), (0, 0, 0))
        entry = self.entry()
        self.assertEqual(self.admit(source, [entry], [entry])[0], [])
        # A later white stroke changes what is really visible.
        self.assertEqual(self.admit(source, [entry], [entry, self.entry(color=0)])[0], [entry])

    def test_overlaps_are_evaluated_in_order_without_repainting_worse_color(self):
        source = self.source(); source.putpixel((4, 4), (0, 0, 0))
        gray, black = self.entry(color=3), self.entry()
        self.assertEqual(self.admit(source, [gray, black, gray])[0], [gray, black])
        self.assertEqual(self.admit(source, [black, black])[0], [black])
        # Budget dropping the gray step leaves the black step safe.
        self.assertEqual(self.admit(source, [black])[0], [black])

    def test_native_scale_maps_centers_without_scaling_brush_width(self):
        source = self.source((27, 18)); source.putpixel((13, 9), (0, 0, 0))
        entries = [self.entry()]
        self.assertEqual(self.admit(source, entries, work=(9, 9))[0], entries)
        self.assertEqual(self.admit(source, [self.entry(brush=3)], work=(9, 9))[0], [])

    def test_segments_test_connector_footprints_not_only_endpoints(self):
        source = self.source(); source.putpixel((3, 4), (0, 0, 0)); source.putpixel((5, 4), (0, 0, 0))
        self.assertEqual(self.admit(source, [self.entry(((3, 4), (5, 4)))])[0], [])
        source.putpixel((4, 4), (0, 0, 0))
        self.assertEqual(len(self.admit(source, [self.entry(((3, 4), (5, 4)))])[0]), 1)

    def test_boundary_footprint_is_skipped_by_canvas_guard(self):
        source = self.source(); ImageDraw.Draw(source).rectangle((0, 0, 1, 1), fill='black')
        self.assertEqual(self.admit(source, [self.entry(((0, 0),), brush=5)])[0], [])

    def test_skipped_base_stroke_cannot_manufacture_a_quality_gain(self):
        source = self.source()
        base = [self.entry(((1, 4),), brush=7)]
        # Without replaying the wide-brush safe skip, black makes gray look better
        # than black, but actual unpainted white would be made worse by gray.
        self.assertEqual(self.admit(source, [self.entry(((1, 4),), color=3)], base)[0], [])

    def test_integer_centering_preserves_physical_source_alignment(self):
        source = self.source(); source.putpixel((4, 4), (0, 0, 0))
        entries = [self.entry()]
        self.assertEqual(self.admit(source, entries, _planning_canvas_size=(13, 11))[0], entries)

    def test_odd_canvas_fit_difference_fails_closed(self):
        source = self.source(); entries = [self.entry()]
        selected, meta = self.admit(source, entries, _planning_canvas_size=(10, 9))
        self.assertEqual(selected, [])
        self.assertIn('fractional', meta['reason'])

    def test_fractional_fit_cannot_be_hidden_by_integer_truncation(self):
        source = self.source()
        with patch.object(zoom, '_visible_rgb', side_effect=AssertionError('must not allocate')):
            selected, meta = zoom._quality_safe_zoom_proposals(source, [], [self.entry()], self.palette,
                {'_planning_canvas_size': (11, 9)}, (9, 9), (9.8, 9), lambda: False)
        self.assertEqual(selected, [])
        self.assertIn('fractional fitted', meta['reason'])

    def test_missing_white_palette_still_has_true_white_canvas(self):
        source = self.source(); source.putpixel((4, 4), (0, 0, 0))
        entry = self.entry(color=0)
        result, _ = zoom._quality_safe_zoom_proposals(source, [], [entry], ((0, 0, 0),),
            {}, source.size, source.size, lambda: False)
        self.assertEqual(result, [entry])

    def test_unknown_fill_base_and_oversized_target_fail_closed(self):
        source = self.source(); entries = [self.entry()]
        self.assertEqual(self.admit(source, entries, fill_regions=[{'color_index': 1}])[0], [])
        self.assertEqual(self.admit(source, entries, background_fill_plan={'enabled': True})[0], [])
        with patch.object(zoom, '_visible_rgb', side_effect=AssertionError('must not allocate')):
            result, meta = zoom._quality_safe_zoom_proposals(source, [], entries, self.palette,
                {}, source.size, (100000, 100000), lambda: False)
        self.assertFalse(result)
        self.assertIn('bounded', meta['reason'])

    def test_cancel_before_and_during_simulation_preserves_inputs(self):
        source = self.source(); source.putpixel((4, 4), (0, 0, 0))
        base, entries = [self.entry(color=0)], [self.entry()]
        original = copy.deepcopy((base, entries)); pixels = source.tobytes()
        for after in (0, 5, 8):
            checks = [0]
            def cancel():
                checks[0] += 1
                return checks[0] > after
            with self.assertRaises(InterruptedError):
                zoom._quality_safe_zoom_proposals(source, base, entries, self.palette,
                    {}, source.size, source.size, cancel)
        self.assertEqual((base, entries), original)
        self.assertEqual(source.tobytes(), pixels)

    def test_integration_rejects_subpixel_candidate_that_worsens_native_target(self):
        source = self.source((64, 64)); draw = ImageDraw.Draw(source)
        for k in range(6, 11):
            draw.line((k * 4, 24, k * 4 + 3, 27), fill='black', width=1)
        work = self.source((16, 16)); groups = [[], []]; sequence = []
        options = dict(detail_zoom='4x', draw_quality='Maximum likeness', skip_white=False, brush_px=1)
        out = zoom.add_detail_zoom_pass(source, work, self.palette[:2], groups, groups, sequence,
            options, fitted=(16, 16))
        self.assertIs(out[0], groups); self.assertIs(out[2], sequence)
        self.assertFalse(out[-1]['enabled'])
        self.assertGreater(out[-1]['quality_gate']['rejected_paths'], 0)
        self.assertEqual(out[-1]['roi_boxes'], ())
        # Same source details become physically drawable on a larger target.
        grown = zoom.add_detail_zoom_pass(source, work, self.palette[:2], groups, groups, sequence,
            options, fitted=(64, 64))
        self.assertTrue(grown[-1]['enabled'])
        self.assertTrue(grown[2])


if __name__ == '__main__':
    unittest.main()
