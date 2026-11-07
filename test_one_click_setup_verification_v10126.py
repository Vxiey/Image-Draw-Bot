import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from Colors import save_calibration
from OneClickSetupVerification import (
    SetupVerificationResult, canvas_shift, format_verification, load_verified_palette,
    setup_mode, validate_canvas, verify_browser_live, verify_paint_live,
)


class FakeImage:
    def __init__(self,size):self.size=size
    def convert(self,_mode):return self


class OneClickSetupVerificationTests(unittest.TestCase):
    def test_target_modes_keep_step_28_independent(self):
        self.assertEqual(setup_mode('microsoft-paint'),'paint')
        self.assertEqual(setup_mode('gartic-phone'),'browser')
        self.assertEqual(setup_mode('skribbl'),'browser')
        self.assertEqual(setup_mode('generic'),'manual')

    def test_canvas_must_be_contained(self):
        self.assertEqual(validate_canvas((0,0,1000,700),(100,100,900,600)),(100,100,900,600))
        with self.assertRaises(ValueError):validate_canvas((0,0,1000,700),(-1,100,900,600))

    def test_canvas_must_not_be_tiny(self):
        with self.assertRaises(ValueError):validate_canvas((0,0,1000,700),(100,100,120,120))

    def test_canvas_shift_is_max_edge_delta(self):
        self.assertEqual(canvas_shift((10,20,100,200),(12,18,105,199)),5)

    def test_verified_palette_required(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'palette.json'
            save_calibration([(10,10)],[(255,0,0)],path,profile_key='gartic-phone',state='calibrated')
            with self.assertRaises(ValueError):load_verified_palette(path,'gartic-phone')

    def test_verified_palette_owner_required(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'palette.json'
            save_calibration([(10,10)],[(255,0,0)],path,profile_key='skribbl',state='verified',verification={'confidence':.9})
            with self.assertRaises(ValueError):load_verified_palette(path,'gartic-phone')

    def test_browser_live_verification_passes_only_with_visual_palette(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'palette.json'
            points=[(100+i*20,650) for i in range(6)]
            colors=[(i*30,40,200-i*20) for i in range(6)]
            save_calibration(points,colors,path,profile_key='skribbl',state='verified',verification={'confidence':.93})
            visual=SimpleNamespace(passed=True,canvas_ok=True,palette_verified=5,palette_tested=6,
                                   confidence=.91,reasons=(),max_palette_error=10.0)
            with patch('BrowserVisualPreflight.verify_browser_visual_preflight',return_value=visual):
                result=verify_browser_live('skribbl',{'client_rect':(0,0,1200,800)},(100,100,900,600),path,screenshot=FakeImage((1200,800)))
            self.assertTrue(result.passed)
            self.assertEqual(result.palette_verified,5)
            self.assertGreaterEqual(result.confidence,.9)

    def test_browser_live_verification_blocks_weak_palette(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'palette.json'
            points=[(100+i*20,650) for i in range(6)]
            colors=[(i*30,40,200-i*20) for i in range(6)]
            save_calibration(points,colors,path,profile_key='skribbl',state='verified',verification={'confidence':.95})
            visual=SimpleNamespace(passed=False,canvas_ok=True,palette_verified=3,palette_tested=6,
                                   confidence=.70,reasons=('palette mismatch',),max_palette_error=90.0)
            with patch('BrowserVisualPreflight.verify_browser_visual_preflight',return_value=visual):
                result=verify_browser_live('skribbl',{'client_rect':(0,0,1200,800)},(100,100,900,600),path,screenshot=FakeImage((1200,800)))
            self.assertFalse(result.passed)
            self.assertFalse(result.palette_ok)

    def test_paint_live_requires_20_colors_tools_and_second_detection(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'palette.json'
            points=[(20+i*20,50+(i//10)*20) for i in range(20)]
            colors=[(i*10%256,i*20%256,i*30%256) for i in range(20)]
            anchor={'version':1,'client_rect':[0,0,1200,800]}
            save_calibration(points,colors,path,profile_key='microsoft-paint',state='verified',verification={'confidence':.90},anchor=anchor)
            tools={'version':3,'tools':{'Pencil':[10,10],'Fill':[20,20]},'anchor':anchor}
            detected={'canvas_box':(102,102,898,598),'palette_count':20,'confidence':.90,'positions':points,'rgbs':colors,'tools':tools['tools']}
            with patch('PaintTools.load_tool_calibration',return_value=tools), patch('PaintFullCalibration.detect_setup',return_value=detected):
                result=verify_paint_live({'client_rect':(0,0,1200,800)},(100,100,900,600),path,screenshot=FakeImage((1200,800)))
            self.assertTrue(result.passed)
            self.assertTrue(result.tool_ok)
            self.assertEqual(result.palette_verified,20)

    def test_paint_live_blocks_canvas_reflow(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'palette.json'
            points=[(20+i*20,50+(i//10)*20) for i in range(20)]
            colors=[(i*10%256,i*20%256,i*30%256) for i in range(20)]
            anchor={'version':1,'client_rect':[0,0,1200,800]}
            save_calibration(points,colors,path,profile_key='microsoft-paint',state='verified',verification={'confidence':.90},anchor=anchor)
            tools={'version':3,'tools':{'Pencil':[10,10],'Fill':[20,20]},'anchor':anchor}
            detected={'canvas_box':(130,100,930,600),'palette_count':20,'confidence':.90,'positions':points,'rgbs':colors,'tools':tools['tools']}
            with patch('PaintTools.load_tool_calibration',return_value=tools), patch('PaintFullCalibration.detect_setup',return_value=detected):
                result=verify_paint_live({'client_rect':(0,0,1200,800)},(100,100,900,600),path,screenshot=FakeImage((1200,800)))
            self.assertFalse(result.passed)
            self.assertFalse(result.canvas_ok)

    def test_status_text_is_compact_and_explicit(self):
        result=SetupVerificationResult(True,'skribbl','browser',.91,True,True,5,6,True,())
        text=format_verification(result)
        self.assertIn('verified',text)
        self.assertIn('canvas OK',text)
        self.assertIn('palette 5/6',text)
        self.assertIn('91%',text)


if __name__=='__main__':unittest.main()
