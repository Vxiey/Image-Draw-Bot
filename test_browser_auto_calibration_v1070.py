import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

from BrowserAutoCalibration import detect_browser_canvas, detect_browser_setup, auto_calibrate_browser, SUPPORTED_BROWSER_PROFILES
from BrowserAutoCalibration import _largest_light_component
from PaletteMaps import SKRIBBL, GARTIC_PHONE
from Colors import calibration_metadata
from Version import APP_VERSION, FILE_VERSION
from test_version_metadata import EXPECTED_APP_VERSION, EXPECTED_FILE_VERSION


class BrowserAutoCalibrationTests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(APP_VERSION,EXPECTED_APP_VERSION)
        self.assertEqual(FILE_VERSION,EXPECTED_FILE_VERSION)

    def test_supported_profiles(self):
        self.assertIn('gartic-phone', SUPPORTED_BROWSER_PROFILES)
        self.assertIn('skribbl-fast', SUPPORTED_BROWSER_PROFILES)
        self.assertIn('sketchheads', SUPPORTED_BROWSER_PROFILES)

    @staticmethod
    def _skribbl_image():
        im=Image.new('RGB',(1200,800),(39,91,166));d=ImageDraw.Draw(im)
        d.rectangle((190,140,900,610),fill=(255,255,255))
        # 13 columns x 2 rows near the lower toolbar.
        x0,y0=190,650
        for i,rgb in enumerate(SKRIBBL.colors):
            col=i//2;row=i%2
            x=x0+col*25;y=y0+row*25
            d.rectangle((x,y,x+20,y+20),fill=rgb)
        return im

    @staticmethod
    def _gartic_image():
        im=Image.new('RGB',(1600,900),(190,45,80));d=ImageDraw.Draw(im)
        # Purple framed wide white canvas.
        d.rectangle((470,280,1420,820),fill=(90,36,164))
        d.rectangle((480,290,1410,810),fill=(255,255,255))
        # 6x12 palette in expected left-side ROI.
        x0,y0=170,300
        for i,rgb in enumerate(GARTIC_PHONE.colors):
            row=i//6;col=i%6
            x=x0+col*24;y=y0+row*22
            d.rectangle((x,y,x+18,y+18),fill=rgb)
        return im

    @staticmethod
    def _sketchheads_image():
        im=Image.new('RGB',(1260,700),(250,250,248));d=ImageDraw.Draw(im)
        colors=[(52,52,52),(190,194,202),(230,74,79),(186,126,73),(255,144,54),(255,224,55),
                (80,188,62),(31,190,121),(43,172,211),(99,89,231),(220,113,231),(80,220,210)]
        y=660
        for i,rgb in enumerate(colors):
            x=350+i*32
            d.ellipse((x-11,y-11,x+11,y+11),fill=rgb)
        return im

    def test_skribbl_palette_and_canvas(self):
        r=detect_browser_setup('skribbl-fast',self._skribbl_image())
        self.assertGreaterEqual(len(r['positions']),18)
        self.assertGreaterEqual(r['palette_confidence'],.75)
        self.assertIsNotNone(r['canvas_box'])

    def test_largest_ineligible_component_does_not_hide_a_smaller_one(self):
        with self._skribbl_image() as scene:
            box, _ = _largest_light_component(scene, step=1, min_ratio=0,
                                               accept=lambda bounds: bounds[1] > 610)
        self.assertEqual(box, (190, 650, 211, 671))

    def test_gartic_palette_and_canvas(self):
        r=detect_browser_setup('gartic-phone',self._gartic_image())
        self.assertEqual(len(r['positions']),72)
        self.assertGreaterEqual(r['palette_confidence'],.95)
        self.assertIsNotNone(r['canvas_box'])

    def test_canvas_only_finds_bounded_surfaces_at_a_negative_monitor_origin(self):
        layouts = (
            ('skribbl', self._skribbl_image, (190, 140, 901, 611), (-1008, 191, -297, 662)),
            ('gartic-phone', self._gartic_image, (480, 290, 1410, 810), (-720, 340, 212, 862)),
        )
        for profile, fixture, canvas_interior, expected in layouts:
            with self.subTest(profile=profile), fixture() as scene:
                found = detect_browser_canvas(profile, scene, screen_origin=(-1200, 50))
                self.assertEqual(found['canvas_box'], expected)
                self.assertGreater(found['canvas_confidence'], .9)
                l, t, r, b = canvas_interior
                for top in (t, t-20):
                    with scene.crop((l, top, r, b)) as unbounded:
                        self.assertEqual(detect_browser_canvas(profile, unbounded),
                                         {'canvas_box': None, 'canvas_confidence': 0.0})

    def test_sketchheads_palette_and_safe_canvas(self):
        r=detect_browser_setup('sketchheads',self._sketchheads_image())
        self.assertGreaterEqual(len(r['positions']),8)
        self.assertIsNotNone(r['canvas_box'])
        self.assertLess(r['canvas_box'][3],660)

    def test_save_is_anchored_and_read_only(self):
        image=self._skribbl_image()
        meta={'client_rect':(100,200,1300,1000),'rect':(90,170,1310,1010),'handle':123,'dpi':96}
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'cal.json'
            result=auto_calibrate_browser('skribbl-fast',meta,path,screenshot=image)
            self.assertGreaterEqual(result.palette_count,18)
            info=calibration_metadata(path)
            self.assertEqual(info['version'],4)
            self.assertIsNotNone(info['anchor'])

if __name__=='__main__':
    unittest.main()
