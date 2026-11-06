"""Visible chromatic boundaries through the real pre-input edge verifier."""
from contextlib import ExitStack, closing
import math
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from EdgeDetection import verify_canvas_edges, verify_canvas_edges_from_capture


OUTSIDE = (100, 100, 20)
INSIDE = (101, 69, 177)


def scene(actual=(30, 30, 110, 90), mode='RGB'):
    image = Image.new('RGB', (150, 130), OUTSIDE)
    x0, y0, x1, y1 = actual
    ImageDraw.Draw(image).rectangle((x0, y0, x1 - 1, y1 - 1), fill=INSIDE)
    if mode == 'RGB':
        return image
    with closing(image):
        return image.convert(mode)


class ChromaticBoundaryTests(unittest.TestCase):
    def test_equal_luminance_edges_have_their_exact_geometric_location(self):
        # Independent integer luma equality; no implementation helper is used.
        self.assertEqual(sum(a * w for a, w in zip(OUTSIDE, (299, 587, 114))),
                         sum(a * w for a, w in zip(INSIDE, (299, 587, 114))))
        contrast = math.sqrt(sum((a - b) ** 2 * w for a, b, w in
                                 zip(OUTSIDE, INSIDE, (.30, .59, .11))))
        with closing(scene()) as image:
            result = verify_canvas_edges_from_capture((image, (30, 30, 80, 60), (0, 0, 150, 130)))
            self.assertTrue(result.ok, result.as_dict())
            self.assertEqual(result.detected_sides, 4)
            self.assertEqual([s.offset_px for s in result.sides], [0, 0, 0, 0])
            for side in result.sides:
                self.assertAlmostEqual(side.strength, contrast, places=10)
            self.assertEqual(image.getpixel((30, 30)), INSIDE)

    def test_oversized_chromatic_selection_stops_but_conservative_selection_passes(self):
        with closing(scene()) as image:
            oversized = verify_canvas_edges(image, (22, 22, 96, 76))
            self.assertFalse(oversized.ok)
            self.assertEqual([s.offset_px for s in oversized.sides], [8, -8, 8, -8])
            self.assertEqual(len(oversized.failed_sides), 4)
            conservative = verify_canvas_edges(image, (38, 38, 64, 44))
            self.assertTrue(conservative.ok)
            self.assertEqual([s.offset_px for s in conservative.sides], [-8, 8, -8, 8])

    def test_weak_and_unavailable_edges_keep_canvas_guard_fallback(self):
        for outer, inner in (((100, 100, 100), (101, 100, 101)), (INSIDE, INSIDE)):
            with self.subTest(outer=outer), closing(Image.new('RGB', (150, 130), outer)) as image:
                ImageDraw.Draw(image).rectangle((30, 30, 109, 89), fill=inner)
                result = verify_canvas_edges(image, (30, 30, 80, 60))
                self.assertTrue(result.ok)
                self.assertEqual(result.detected_sides, 0)
                self.assertEqual([s.offset_px for s in result.sides], [0] * 4)
                fullscreen = verify_canvas_edges(image, (0, 0, 150, 130))
                self.assertTrue(fullscreen.ok)
                self.assertEqual(fullscreen.available_sides, 0)

    def test_real_execute_plan_uses_chromatic_boundary_before_fake_input(self):
        from DrawBot import execute_plan
        from test_drawbot import Mouse, NoWait
        from test_visual_verification_v1043 import simple_visual_plan

        for shifted in (False, True):
            with self.subTest(shifted=shifted), ExitStack() as stack:
                screenshot = stack.enter_context(closing(scene((38, 30, 118, 90) if shifted else (30, 30, 110, 90))))
                plan = simple_visual_plan()
                plan['image'].close()
                plan['image'] = stack.enter_context(closing(Image.new('RGB', (80, 60), 'white')))
                plan.update(fitted=(80, 60), groups=[[(20, 20, 50, 20)], []], count=1)
                plan['options'].update(visual_verification_enabled=False, unlimited_time=True,
                                       brush_px=1, canvas_guard_brush_px=1, edge_behavior='Hard Clip')
                mouse = Mouse()
                captures = []
                def capture(area, margin):
                    captures.append((area, margin))
                    return screenshot, (30, 30, 80, 60)
                mouse.snapshot_canvas_with_margin = capture
                stack.enter_context(patch('DrawBot.log_event'))
                stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda s: s.as_dict()))
                for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                             'CompletedDrawingAnalysis.record_completed_drawing',
                             'AutoTunerFeedback.record_completed_feedback', 'CorrectionHistory.record_correction_history'):
                    stack.enter_context(patch(name, return_value={}))
                def run():
                    execute_plan(plan, (100, 100, 80, 60), [(10, 10), (20, 10)], mouse,
                                 NoWait(), threading.Event(), lambda *e: None, clock=lambda: 0)
                if shifted:
                    with self.assertRaisesRegex(InterruptedError, 'Canvas edge verification stopped'):
                        run()
                    self.assertFalse(any(action[0] in ('click', 'press') for action in mouse.actions))
                else:
                    run()
                    self.assertEqual(sum(action[0] == 'press' for action in mouse.actions), 1)
                    self.assertEqual(plan['options']['canvas_edge_meta']['max_offset_px'], 0)
                self.assertEqual(captures, [((100, 100, 80, 60), 24)])
                self.assertFalse(mouse.held)

    def test_owned_conversion_closes_on_success_and_failure_without_closing_capture(self):
        real_convert = Image.Image.convert
        for fail in (False, True):
            converted = []
            def convert(image, *args, **kwargs):
                output = real_convert(image, *args, **kwargs)
                converted.append(output)
                return output
            with self.subTest(fail=fail), closing(scene(mode='RGBA')) as image, ExitStack() as stack:
                stack.enter_context(patch.object(Image.Image, 'convert', convert))
                if fail:
                    stack.enter_context(patch('EdgeDetection._side_contrast', side_effect=RuntimeError('fixture')))
                    with self.assertRaisesRegex(RuntimeError, 'fixture'):
                        verify_canvas_edges(image, (30, 30, 80, 60))
                else:
                    self.assertTrue(verify_canvas_edges(image, (30, 30, 80, 60)).ok)
                self.assertEqual(len(converted), 1)
                with self.assertRaises(ValueError):
                    converted[0].getpixel((0, 0))
                self.assertEqual(image.getpixel((30, 30)), (*INSIDE, 255))


if __name__ == '__main__':
    unittest.main()
