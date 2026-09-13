import unittest
from PIL import Image, ImageDraw

from GarticEngineV2 import detect_gartic_canvas, choose_runtime_profile, stroke_graph_order
from GarticPhoneFastRenderer import build_gartic_execution_paths
from Version import APP_VERSION, FILE_VERSION


class GarticEngineV2Tests(unittest.TestCase):
    def test_detects_reference_canvas_from_full_screenshot_like_layout(self):
        im = Image.new('RGB', (1920, 1080), (190, 20, 80))
        draw = ImageDraw.Draw(im)
        # Purple card/frame surrounding the drawing paper.
        draw.rounded_rectangle((470, 300, 1470, 880), radius=22, fill=(96, 40, 155))
        draw.rectangle((479, 319, 1461, 868), fill=(255, 255, 255))
        result = detect_gartic_canvas(im)
        self.assertTrue(result.found)
        self.assertGreaterEqual(result.confidence, 0.70)
        self.assertAlmostEqual(result.aspect, 982/549, delta=0.04)

    def test_runtime_profile_becomes_more_aggressive_when_timer_is_low(self):
        normal = choose_runtime_profile(None, canvas_size=(982, 549), requested_speed='Fast')
        low = choose_runtime_profile(18, canvas_size=(982, 549), requested_speed='Fast')
        self.assertLess(low.max_colors, normal.max_colors)
        self.assertLess(low.max_paths, normal.max_paths)
        self.assertGreater(low.stroke_step_px, normal.stroke_step_px)
        self.assertEqual(low.color_order, 'dark-first')

    def test_stroke_graph_reduces_travel_without_adding_paths(self):
        paths = [((0, 0), (0, 10)), ((400, 0), (400, 10)), ((2, 11), (2, 20)), ((402, 11), (402, 20))]
        ordered, meta = stroke_graph_order(paths, allow_reverse=True, window=8)
        self.assertEqual(len(ordered), len(paths))
        self.assertTrue(meta['stroke_graph'])
        self.assertLess(meta['pen_up_after'], meta['pen_up_before'])

    def test_gartic_execution_paths_apply_stroke_graph_order(self):
        groups = [[(0,0,0,10), (400,0,400,10), (2,11,2,20), (402,11,402,20)]]
        paths = build_gartic_execution_paths(groups, {'0': 'vertical'})[0]
        self.assertEqual(len(paths), 4)
        # Nearest-neighbour ordering should keep the two left-side paths near each other.
        self.assertLess(abs(paths[1][0][0] - paths[0][-1][0]), 20)

    def test_current_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')


if __name__ == '__main__':
    unittest.main()
