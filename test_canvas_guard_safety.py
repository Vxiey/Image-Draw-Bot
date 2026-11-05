import math
import unittest

from CanvasGuard import CanvasGuard, CanvasSafetyStop, FinalMouseGuard, point_in_polygon


class RecordingMouse:
    def __init__(self):
        self.actions = []

    def move(self, x, y):
        self.actions.append(("move", x, y))

    def press(self):
        self.actions.append(("press",))


class CanvasGuardSafetyTests(unittest.TestCase):
    def test_concave_canvas_never_projects_mouse_outside_selected_polygon(self):
        # The old centroid fallback moved the inner corner (20, 20) to
        # (27, 27), outside this L-shaped canvas.
        polygon = ((0, 0), (100, 0), (100, 20), (20, 20), (20, 100), (0, 100))
        for ordered in (polygon, tuple(reversed(polygon))):
            with self.subTest(polygon=ordered):
                mouse = RecordingMouse()
                with self.assertRaises(CanvasSafetyStop):
                    guard = CanvasGuard.from_polygon(ordered, brush_px=15)
                    FinalMouseGuard(mouse, guard).move(20, 20)
                self.assertEqual(mouse.actions, [])

    def test_oversized_brush_is_rejected_instead_of_reducing_inset(self):
        with self.assertRaises(CanvasSafetyStop):
            CanvasGuard.from_area((100, 100, 10, 10), brush_px=50)

    def test_inverted_offset_rectangle_is_not_treated_as_safe(self):
        # Every shifted corner is still within the original rectangle, but no
        # center can accommodate the required six-pixel margin.
        with self.assertRaises(CanvasSafetyStop):
            CanvasGuard.from_area((0, 0, 11, 11), brush_px=11, edge_margin_px=0)

    def test_collapsed_triangle_inset_is_rejected(self):
        # The bounding box alone cannot determine whether a brush fits in a
        # narrow triangular canvas.
        with self.assertRaises(CanvasSafetyStop):
            CanvasGuard.from_polygon(((0, 0), (100, 0), (0, 20)), brush_px=15)

    def test_rounded_slanted_inset_preserves_brush_and_edge_clearance(self):
        polygon = ((0, 0), (100, 0), (0, 100))
        for ordered in (polygon, tuple(reversed(polygon))):
            with self.subTest(polygon=ordered):
                guard = CanvasGuard.from_polygon(ordered, brush_px=5, edge_margin_px=2)
                margin = guard.model.brush_inset.total_px
                for x, y in guard.model.safe_polygon:
                    self.assertTrue(point_in_polygon((x, y), ordered))
                    self.assertGreaterEqual(x, margin)
                    self.assertGreaterEqual(y, margin)
                    self.assertGreaterEqual((100 - x - y) / math.sqrt(2), margin)

    def test_valid_rectangle_keeps_default_input_coordinates(self):
        guard = CanvasGuard.from_area((100, 200, 50, 30), brush_px=5, edge_margin_px=2)
        self.assertEqual(guard.model.safe_bounds, (105, 205, 144, 224))
        self.assertEqual(guard.protect_point((100, 200)), (105, 205))

    def test_redundant_collinear_vertices_preserve_convex_canvas(self):
        polygon = ((0, 0), (50, 0), (100, 0), (100, 100), (0, 100))
        # Include a redundant point spanning the closing/first edge and both
        # winding directions, as calibration anchors need not start at a corner.
        rotated = polygon[1:] + polygon[:1]
        reference = CanvasGuard.from_area((0, 0, 101, 101), brush_px=3, edge_margin_px=2)
        for ordered in (polygon, tuple(reversed(polygon)), rotated, tuple(reversed(rotated))):
            with self.subTest(polygon=ordered):
                guard = CanvasGuard.from_polygon(ordered, brush_px=3, edge_margin_px=2)
                self.assertEqual(guard.model.safe_bounds, (4, 4, 96, 96))
                self.assertEqual(set(guard.model.safe_polygon), {(4, 4), (96, 4), (96, 96), (4, 96)})
                self.assertEqual(guard.protect_point((50, 0)), reference.protect_point((50, 0)))

    def test_collinear_backtracking_is_still_rejected(self):
        polygon = ((0, 0), (75, 0), (50, 0), (100, 0), (100, 100), (0, 100))
        for ordered in (polygon, tuple(reversed(polygon))):
            with self.subTest(polygon=ordered):
                with self.assertRaises(CanvasSafetyStop):
                    CanvasGuard.from_polygon(ordered, brush_px=3)

    def test_self_intersecting_polygon_is_still_rejected(self):
        polygon = ((0, 0), (100, 100), (0, 100), (100, 0), (100, 50))
        repeated = ((0, 0), (100, 0), (100, 100), (0, 100)) * 2
        for ordered in (polygon, tuple(reversed(polygon)), repeated, tuple(reversed(repeated))):
            with self.subTest(polygon=ordered):
                with self.assertRaises(CanvasSafetyStop):
                    CanvasGuard.from_polygon(ordered, brush_px=3)


if __name__ == "__main__":
    unittest.main()
