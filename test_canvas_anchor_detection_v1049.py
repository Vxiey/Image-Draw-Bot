import threading
import unittest
from PIL import Image, ImageDraw

from CanvasAnchorDetection import detect_canvas_anchors, detect_triangle_anchors
from CanvasGuard import CanvasModel, normalize_canvas_anchors
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


def triangle_image():
    im=Image.new('RGB',(220,140),'white')
    draw=ImageDraw.Draw(im)
    tris=[
        [(18,18),(34,18),(26,34)],
        [(102,14),(118,14),(110,31)],
        [(186,18),(202,18),(194,34)],
        [(18,106),(34,122),(18,122)],
        [(102,108),(118,108),(110,125)],
        [(186,122),(202,106),(202,122)],
    ]
    for pts in tris:
        draw.polygon(pts, fill=(0,0,0))
    return im


def base_plan_with_anchors(options):
    return {
        'image': Image.new('RGBA',(10,10),'black'),
        'fitted': (10,10),
        'groups': [[(1,1,8,8)]],
        'execution_groups': None,
        'execution_sequence': [],
        'count': 1,
        'options': {'delay':0,'max_seconds':30,'precision':'Normal','speed':'Fast','brush_px':3,
                    'paint_current_color':False,'strict_color_verification':False, **options},
        'colors': ((0,0,0),),
        'color_selectors': ({'kind':'palette','palette_index':0},),
    }


class CanvasAnchorDetectionV1049Tests(unittest.TestCase):
    def test_version_bumped(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_blank_canvas_still_produces_corner_anchors(self):
        result=detect_canvas_anchors(Image.new('RGB',(80,50),'white'))
        self.assertEqual(result.corner_count,4)
        self.assertEqual(result.triangle_count,0)
        self.assertEqual(result.polygon,((0.0,0.0),(1.0,0.0),(1.0,1.0),(0.0,1.0)))
        self.assertGreaterEqual(result.confidence,.78)

    def test_detects_six_triangle_anchors_deterministically(self):
        triangles=detect_triangle_anchors(triangle_image())
        self.assertEqual(len(triangles),6)
        self.assertTrue(all(t.confidence >= .50 for t in triangles))
        result=detect_canvas_anchors(triangle_image())
        self.assertEqual(result.corner_count,4)
        self.assertEqual(result.triangle_count,6)
        self.assertEqual(len(result.anchors),10)
        self.assertGreaterEqual(result.confidence,.99)

    def test_normalized_anchors_convert_to_screen_space(self):
        result=detect_canvas_anchors(triangle_image())
        anchors=normalize_canvas_anchors(result.as_options()['canvas_anchors'], area=(100,200,221,141), coordinate_space='normalized')
        self.assertEqual(len(anchors),10)
        self.assertEqual(anchors[0].center,(100.0,200.0))
        self.assertEqual(anchors[2].center,(320.0,340.0))
        self.assertTrue(all(a.center[0] >= 100 and a.center[1] >= 200 for a in anchors))

    def test_canvas_model_keeps_anchor_items(self):
        result=detect_canvas_anchors(triangle_image())
        anchors=normalize_canvas_anchors(result.as_options()['canvas_anchors'], area=(50,60,220,140), coordinate_space='normalized')
        model=CanvasModel.from_area_or_polygon((50,60,220,140), polygon=result.polygon, coordinate_space='normalized', anchors=anchors, confidence=result.confidence)
        self.assertEqual(len(model.anchors),10)
        self.assertEqual(sum(1 for a in model.anchors if a.kind=='corner'),4)
        self.assertEqual(sum(1 for a in model.anchors if a.kind=='triangle'),6)
        self.assertAlmostEqual(model.confidence,1.0)

    def test_execute_plan_reports_anchor_counts(self):
        result=detect_canvas_anchors(triangle_image())
        plan=base_plan_with_anchors(result.as_options())
        mouse=Mouse();events=[]
        execute_plan(plan,(100,100,80,50),[(10,10)],mouse,Stop(),threading.Event(),lambda *e: events.append(e),dry_run=True)
        meta=plan['options']['canvas_guard_meta']
        self.assertEqual(meta['anchors'],10)
        self.assertEqual(len(meta['anchor_items']),10)
        self.assertTrue(any(e[0]=='status' and 'anchors=4 corners/6 triangles' in e[1] for e in events))


if __name__=='__main__':unittest.main()
