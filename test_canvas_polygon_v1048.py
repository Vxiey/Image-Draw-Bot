import threading
import unittest
from PIL import Image

from CanvasGuard import CanvasGuard, CanvasModel, CanvasSafetyStop, normalize_canvas_polygon, point_in_polygon
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


def base_plan():
    return {
        'image': Image.new('RGBA',(10,10),'black'),
        'fitted': (10,10),
        'groups': [[(4,5,6,5)]],
        'execution_groups': None,
        'execution_sequence': [],
        'count': 1,
        'options': {'delay':0,'max_seconds':30,'precision':'Normal','speed':'Fast','brush_px':3,
                    'paint_current_color':False,'strict_color_verification':False,
                    'canvas_polygon': [(0.5,0.0),(1.0,0.5),(0.5,1.0),(0.0,0.5)],
                    'canvas_polygon_space': 'normalized'},
        'colors': ((0,0,0),),
        'color_selectors': ({'kind':'palette','palette_index':0},),
    }


class CanvasPolygonV1048Tests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_normalized_polygon_becomes_screen_polygon(self):
        poly=normalize_canvas_polygon([(0,0),(1,0),(1,1),(0,1)], area=(100,200,21,11), coordinate_space='normalized')
        self.assertEqual(poly, ((100,200),(120,200),(120,210),(100,210)))

    def test_polygon_model_uses_polygon_not_rect_bounds(self):
        diamond=((110,100),(120,110),(110,120),(100,110))
        model=CanvasModel.from_polygon(diamond, brush_px=3, edge_margin_px=2)
        self.assertEqual(model.vertex_count,4)
        self.assertEqual(model.polygon_source,'canvas-polygon')
        self.assertTrue(point_in_polygon((110,110), model.safe_polygon))
        self.assertFalse(point_in_polygon((100,100), model.polygon))  # inside bbox, outside diamond
        self.assertFalse(point_in_polygon((100,100), model.safe_polygon))

    def test_guard_rejects_bbox_point_outside_polygon(self):
        guard=CanvasGuard.from_polygon(((110,100),(120,110),(110,120),(100,110)), brush_px=3, edge_margin_px=2)
        with self.assertRaises(CanvasSafetyStop):
            guard.protect_point((100,100),'bbox corner outside real polygon')

    def test_execute_plan_uses_custom_polygon(self):
        plan=base_plan();mouse=Mouse();events=[]
        execute_plan(plan,(100,100,20,20),[(10,10)],mouse,Stop(),threading.Event(),lambda *e: events.append(e),dry_run=True)
        meta=plan['options']['canvas_guard_meta']
        self.assertEqual(meta['vertex_count'],4)
        self.assertEqual(meta['polygon_source'],'normalized')
        # every drawing move into the target area must be within the safe diamond polygon
        safe_poly=meta['safe_polygon']
        target_moves=[a for a in mouse.actions if a[0]=='move' and a[1]>=100 and a[2]>=100]
        self.assertTrue(target_moves)
        for _,x,y in target_moves:
            self.assertTrue(point_in_polygon((x,y), safe_poly), (x,y,safe_poly))
        self.assertTrue(any(e[0]=='status' and 'polygon vertices=4' in e[1] for e in events))


if __name__=='__main__':unittest.main()
