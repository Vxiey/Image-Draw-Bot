import unittest
from types import SimpleNamespace
from unittest.mock import patch

from SmartDropInCanvas import (
    EXPERIMENTAL_WARNING, SmartCanvasCandidate, canvas_inside_client,
    canvas_relative_box, choose_candidate, event_screen_point,
    overlay_geometry, point_in_canvas, score_candidate,
)
from Version import APP_VERSION, FILE_VERSION


class SmartCanvasDropTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_warning_is_explicitly_experimental_and_early_stage(self):
        lowered = EXPERIMENTAL_WARNING.lower()
        self.assertIn('experimental', lowered)
        self.assertIn('early stage', lowered)
        self.assertIn('may not work as planned', lowered)

    def test_canvas_geometry_and_drop_point(self):
        client=(100,100,1100,900);canvas=(250,180,950,760)
        self.assertTrue(canvas_inside_client(canvas,client))
        self.assertEqual(canvas_relative_box(canvas,client),(150,80,850,660))
        self.assertTrue(point_in_canvas((500,400),canvas))
        self.assertFalse(point_in_canvas((120,400),canvas))
        self.assertFalse(point_in_canvas((250,180),canvas))
        self.assertEqual(overlay_geometry(client),'1000x800+100+100')

    def test_negative_monitor_geometry(self):
        self.assertEqual(overlay_geometry((-1920,-20,0,1060)),'1920x1080-1920-20')

    def test_title_hint_and_confidence_choose_intended_canvas(self):
        client=(0,0,1600,900);box=(350,130,1450,800)
        a=SmartCanvasCandidate(1,(0,0,1600,900),client,96,11,'Gartic Phone - Chrome',box,.80,
            score_candidate('gartic-phone',confidence=.80,canvas_box=box,client_rect=client,title='Gartic Phone - Chrome'))
        b=SmartCanvasCandidate(2,(0,0,1600,900),client,96,12,'Other tab',box,.78,
            score_candidate('gartic-phone',confidence=.78,canvas_box=box,client_rect=client,title='Other tab'))
        self.assertEqual(choose_candidate([b,a]).handle,1)

    def test_ambiguous_candidates_fail_closed(self):
        base=dict(rect=(0,0,1600,900),client_rect=(0,0,1600,900),dpi=96,pid=1,title='Browser',canvas_box=(300,150,1400,800),canvas_confidence=.82)
        a=SmartCanvasCandidate(handle=1,score=.86,**base)
        b=SmartCanvasCandidate(handle=2,score=.84,**base)
        with self.assertRaisesRegex(ValueError,'more than one plausible'):
            choose_candidate([a,b])

    def test_event_point_uses_root_coordinates(self):
        event=SimpleNamespace(x_root=444,y_root=555)
        self.assertEqual(event_screen_point(event),(444,555))

    @patch('SmartDropInCanvas.cursor_position', return_value=(7,8))
    def test_event_point_cursor_fallback(self,_cursor):
        self.assertEqual(event_screen_point(SimpleNamespace()),(7,8))


if __name__=='__main__':
    unittest.main()
