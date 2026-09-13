import unittest
from PIL import Image, ImageDraw

from EdgeDetection import verify_canvas_edges
from UiCompatibility import patch_customtkinter_scroll_guard
from Version import APP_VERSION, FILE_VERSION


class Rc2FieldLogFixTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_conservative_bottom_outset_is_safe(self):
        image = Image.new('RGB', (140, 130), (170, 170, 170))
        draw = ImageDraw.Draw(image)
        # Selected canvas ends at y=80, but the visible boundary is lower at 101.
        # The selection is therefore conservative and CanvasGuard is tighter.
        draw.rectangle((20, 20, 119, 100), fill=(255, 255, 255))
        result = verify_canvas_edges(image, (20, 20, 100, 60), tolerance_px=4, search_px=24)
        self.assertTrue(result.ok, result.as_dict())
        bottom = next(s for s in result.sides if s.side == 'bottom')
        self.assertGreater(bottom.offset_px, 4)
        self.assertIn('conservatively inside', bottom.reason)

    def test_inward_bottom_edge_still_stops(self):
        image = Image.new('RGB', (140, 130), (170, 170, 170))
        draw = ImageDraw.Draw(image)
        # Selected canvas ends at y=90 but real visible bottom is y=81: the
        # selected area extends outside the real canvas and must hard-stop.
        draw.rectangle((20, 20, 119, 80), fill=(255, 255, 255))
        result = verify_canvas_edges(image, (20, 20, 100, 70), tolerance_px=4, search_px=24)
        self.assertFalse(result.ok, result.as_dict())
        bottom = next(s for s in result.failed_sides if s.side == 'bottom')
        self.assertLess(bottom.offset_px, -4)

    def test_scroll_guard_is_idempotent(self):
        # Works whether CustomTkinter is installed or not; repeated calls must
        # never stack wrappers or raise.
        first = patch_customtkinter_scroll_guard()
        second = patch_customtkinter_scroll_guard()
        self.assertEqual(bool(first), bool(second))
        if first:
            from customtkinter.windows.widgets.ctk_scrollable_frame import CTkScrollableFrame
            self.assertFalse(CTkScrollableFrame._check_if_valid_scroll(object(), 'stale-tcl-widget'))


if __name__ == '__main__':
    unittest.main()
