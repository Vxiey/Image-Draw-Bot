import threading
import unittest
from PIL import Image

from CanvasGuard import CanvasGuard, CanvasSafetyStop, clip_path_to_polygon, clip_segment_to_polygon, point_in_polygon
from DrawBot import execute_plan
from Version import APP_VERSION, FILE_VERSION


class Stop:
    def is_set(self): return False
    def wait(self, seconds): return False


class Mouse:
    def __init__(self):
        self.position=(0,0);self.held=False;self.actions=[]
    def get_position(self): return self.position
    def move(self,x,y):
        self.position=(int(x),int(y));self.actions.append(('move',int(x),int(y)))
    def click(self): self.actions.append(('click',))
    def press(self): self.held=True;self.actions.append(('press',))
    def release(self): self.held=False;self.actions.append(('release',))


def plan_with_group(group):
    return {
        'image': Image.new('RGBA',(10,10),'black'),
        'fitted': (20,20),
        'groups': [group],
        'execution_groups': None,
        'execution_sequence': [],
        'count': len(group),
        'options': {'delay':0,'max_seconds':30,'precision':'Normal','speed':'Fast','brush_px':3,
                    'paint_current_color':False,'strict_color_verification':False},
        'colors': ((0,0,0),),
        'color_selectors': ({'kind':'palette','palette_index':0},),
    }


class StrokeClipV1053Tests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_clip_segment_to_polygon_keeps_only_inside_part(self):
        poly=((100,100),(120,100),(120,120),(100,120))
        clipped=clip_segment_to_polygon((90,110),(130,110),poly)
        self.assertEqual(clipped, (((100,110),(120,110)),))

    def test_clip_path_preserves_gaps_as_subpaths(self):
        poly=((100,100),(120,100),(120,120),(100,120))
        clipped=clip_path_to_polygon(((105,105),(130,105),(130,115),(105,115)),poly)
        self.assertEqual(clipped, (((105,105),(120,105)), ((120,115),(105,115))))

    def test_canvas_guard_clips_edge_stroke_instead_of_endpoint_clamping(self):
        guard=CanvasGuard.from_area((100,100,20,20),brush_px=3,edge_margin_px=2)
        clipped=guard.clip_path_to_safe_subpaths(((100,110),(119,110)), 'unit stroke')
        self.assertEqual(clipped, (((104,110),(115,110)),))
        for path in clipped:
            for point in path:
                self.assertTrue(point_in_polygon(point, guard.model.safe_polygon))

    def test_execute_plan_skips_stroke_that_only_touches_canvas_edge(self):
        plan=plan_with_group([(0,0,9,0)])
        mouse=Mouse();events=[]
        execute_plan(plan,(100,100,20,20),[(10,10)],mouse,Stop(),threading.Event(),lambda *e: events.append(e),dry_run=True)
        drawing_moves=[a for a in mouse.actions if a[0]=='move' and a[1]>=100 and a[2]>=100]
        # The top-edge stroke is outside the brush-inset safe polygon; Step 7
        # clips it away instead of moving it down and changing the drawing.
        self.assertFalse(drawing_moves)
        self.assertTrue(any(e[0]=='progress' for e in events))

    def test_execute_plan_clips_normal_midline_stroke_to_safe_polygon(self):
        plan=plan_with_group([(0,5,9,5)])
        mouse=Mouse()
        execute_plan(plan,(100,100,20,20),[(10,10)],mouse,Stop(),threading.Event(),lambda *e: None,dry_run=True)
        drawing_moves=[a for a in mouse.actions if a[0]=='move' and a[1]>=100 and a[2]>=100]
        self.assertTrue(drawing_moves)
        xs=[a[1] for a in drawing_moves]
        ys=[a[2] for a in drawing_moves]
        self.assertGreaterEqual(min(xs),104)
        self.assertLessEqual(max(xs),115)
        self.assertEqual(set(ys),{111})

    def test_source_points_outside_selected_canvas_still_stop(self):
        plan=plan_with_group([(-20,5,9,5)])
        with self.assertRaises(CanvasSafetyStop):
            execute_plan(plan,(100,100,20,20),[(10,10)],Mouse(),Stop(),threading.Event(),lambda *e: None,dry_run=True)


if __name__=='__main__':unittest.main()
