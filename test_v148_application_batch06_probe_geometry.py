"""Ink probes stay on delivered geometry without copying every segment."""
from contextlib import ExitStack
import random
import threading
import unittest
from unittest.mock import patch

from PIL import Image

import DrawBot as app
from CanvasGuard import CanvasGuard
from EdgeBehavior import apply_edge_behavior
from StrokeProbeGeometry import representative_segment
from test_drawbot import Mouse, NoWait
from test_visual_verification_v1043 import simple_visual_plan


class ProbeGeometryTests(unittest.TestCase):
    def test_streamed_choice_matches_independent_brute_force_including_ties(self):
        rng = random.Random(14806)
        for _ in range(120):
            paths = [tuple((rng.randrange(-20, 21), rng.randrange(-20, 21))
                           for _ in range(rng.randrange(0, 50)))
                     for _ in range(rng.randrange(1, 12))]
            candidates = []
            for path in paths:
                for index in range(1, len(path)):
                    a, b = path[index-1], path[index]
                    if a != b:
                        candidates.append((a, b))
            if not candidates:
                continue
            expected = max(candidates, key=lambda p: (p[1][0]-p[0][0])**2+(p[1][1]-p[0][1])**2)
            unchanged = tuple(paths)
            self.assertEqual(representative_segment(paths), expected)
            self.assertEqual(tuple(paths), unchanged)
        self.assertEqual(representative_segment([((0,0),(3,4)), ((20,20),(23,24))]),
                         ((0,0),(3,4)))

    def test_isolated_dots_never_create_an_undrawn_segment(self):
        self.assertEqual(representative_segment([(), ((2,3),), ((10,20),)]), ((2,3),(2,3)))
        self.assertEqual(representative_segment([((5,6),(5,6)), ((20,20),)]), ((5,6),(5,6)))
        with self.assertRaises(ValueError):
            representative_segment([(), ()])

    def test_cancellation_is_polled_for_long_paths_and_many_isolated_dots(self):
        for paths in ([tuple((i,0) for i in range(10000))], [((i,0),) for i in range(10000)]):
            checks = 0
            def stopped():
                nonlocal checks
                checks += 1
                return checks >= 4
            with self.assertRaises(InterruptedError):
                representative_segment(paths, cancelled=stopped)
            self.assertEqual(checks, 4)

    def test_selector_never_slices_the_borrowed_paths(self):
        class NoSlice(list):
            def __getitem__(self, key):
                if isinstance(key, slice):
                    raise AssertionError('verification must not allocate path copies')
                return super().__getitem__(key)
        self.assertEqual(representative_segment([NoSlice([(0,0),(1,0),(9,0)])]),
                         ((1,0),(9,0)))


class DeliveredDotTests(unittest.TestCase):
    def test_real_canvas_clipping_verifies_one_delivered_dot_not_the_gap(self):
        raw = ((102,104),(106,101),(113,101),(117,104))
        guard = CanvasGuard.from_area((100,100,20,20), brush_px=2, edge_margin_px=2)
        self.assertEqual(apply_edge_behavior(guard, raw, behavior='Hard Clip').subpaths,
                         (((103,103),), ((116,103),)))
        plan = simple_visual_plan()
        plan['image'].close()
        plan['image'] = Image.new('RGB', (20,20), 'white')
        self.addCleanup(plan['image'].close)
        path = tuple((x-100,y-100) for x,y in raw)
        plan.update(groups=[[path],[]], count=1,
                    execution_sequence=[{'color_index':0,'path':path,'brush_px':2,
                                         'phase':'major_coverage','estimated_cost_seconds':.01,
                                         'importance':1.,'structural_score':1.}])
        plan['options'].update(visual_verification_enabled=False, visual_verification='Off',
                               visual_verification_resolved='Off', strict_color_verification=True,
                               unlimited_time=True, edge_behavior='Hard Clip')
        class ProbeMouse(Mouse):
            def __init__(self):
                super().__init__(); self.probes=[]; self.clicks=[]
            def click(self):
                self.clicks.append(self.position); super().click()
            def verify_ink_segment(self, start, end, *args):
                self.probes.append((start,end))
                if start != end:
                    raise InterruptedError('The gap between isolated dots contains no ink.')
        mouse=ProbeMouse()
        with ExitStack() as stack:
            stack.enter_context(patch.object(app,'log_event'))
            stack.enter_context(patch.object(app,'save_runtime_safety_report',side_effect=lambda s:s.as_dict()))
            for name in ('RealSpeedBudget.record_runtime_sample','DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing','AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(name,return_value={}))
            app.execute_plan(plan,(100,100,20,20),[(10,10),(20,10)],mouse,NoWait(),
                             threading.Event(),lambda *args:None,clock=lambda:0)
        self.assertEqual([p for p in mouse.clicks if p[0]>=100],[(103,103),(116,103)])
        self.assertEqual(mouse.probes,[((103,103),(103,103))])
        self.assertFalse(mouse.held)
        self.assertEqual(plan['options']['runtime_path_counts']['sent'],1)


if __name__ == '__main__':
    unittest.main()
