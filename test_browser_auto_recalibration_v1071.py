import unittest
from types import SimpleNamespace
from unittest.mock import patch

from BrowserAutoRecalibration import make_layout_state, compare_layout_states
from DrawBot import DrawBotApp
from Version import APP_VERSION, FILE_VERSION


class Value:
    def __init__(self,value=None): self.value=value
    def get(self): return self.value
    def set(self,value): self.value=value


class BrowserAutoRecalibrationTests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_window_translation_is_not_layout_reflow(self):
        old=make_layout_state((100,100,1100,800),96,(200,180,900,650),[(150,700),(180,700),(210,700)])
        new=make_layout_state((300,250,1300,950),96,(400,330,1100,800),[(350,850),(380,850),(410,850)])
        delta=compare_layout_states(old,new)
        self.assertFalse(delta.changed)
        self.assertEqual(delta.reason,'layout unchanged')

    def test_browser_zoom_is_detected_even_when_window_size_is_unchanged(self):
        old=make_layout_state((100,100,1100,800),96,(200,180,900,650),[(150,700),(180,700),(210,700)])
        new=make_layout_state((100,100,1100,800),96,(220,195,930,665),[(165,686),(198,686),(231,686)])
        delta=compare_layout_states(old,new)
        self.assertTrue(delta.changed)
        self.assertIn('canvas reflow/zoom',delta.reason)
        self.assertIn('palette reflow/zoom',delta.reason)

    def test_resize_and_dpi_change_are_detected(self):
        old=make_layout_state((0,0,1000,700),96,(100,100,900,600),[(50,650)])
        new=make_layout_state((0,0,1200,840),120,(120,120,1080,720),[(60,780)])
        delta=compare_layout_states(old,new)
        self.assertTrue(delta.changed)
        self.assertIn('client resize',delta.reason)
        self.assertIn('DPI 96→120',delta.reason)

    def test_browser_target_refresh_uses_visual_recalibration_before_input(self):
        app=SimpleNamespace(
            game=Value('Gartic Phone'),
            target_window=(123,(0,0,1000,700)),target_client_rect=(0,0,1000,700),target_dpi=96,
            corners=[(100,100),(900,600)],saved_area=[(100,100),(900,600)],canvas_anchor_detection=None,
            canvas_anchor_transform_meta=None,target_lock_passed=False,target_lock_fingerprint=None,
        )
        app.area=lambda:(app.corners[0][0],app.corners[0][1],app.corners[1][0]-app.corners[0][0],app.corners[1][1]-app.corners[0][1])
        meta={'handle':123,'rect':(0,0,1200,840),'client_rect':(0,0,1200,840),'dpi':120}
        def recalibrate(obj,meta,reason=''):
            obj.target_window=(123,tuple(meta['rect']));obj.target_client_rect=tuple(meta['client_rect']);obj.target_dpi=meta['dpi']
            obj.corners=[(120,120),(1080,720)];obj.saved_area=list(obj.corners)
            obj.canvas_anchor_transform_meta={'method':'browser-visual-recalibration','changed':True}
            return True
        with patch('TargetCapture.probe_handle_isolated',return_value=meta), \
             patch.object(DrawBotApp,'_auto_recalibrate_browser_from_meta',side_effect=recalibrate) as scan:
            current=DrawBotApp._refresh_target_for_draw(app,update_target_lock=False)
        self.assertEqual(current,(0,0,1200,840))
        self.assertEqual(app.target_dpi,120)
        self.assertEqual(app.corners,[(120,120),(1080,720)])
        self.assertEqual(app.canvas_anchor_transform_meta['method'],'browser-visual-recalibration')
        scan.assert_called_once()

if __name__=='__main__':
    unittest.main()
