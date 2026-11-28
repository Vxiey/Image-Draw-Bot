import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw

from BrowserAutoCalibration import detect_browser_canvas, detect_browser_setup, auto_calibrate_browser, SUPPORTED_BROWSER_PROFILES
from BrowserAutoCalibration import _largest_light_component, _skribbl_palette_frame
from PaletteMaps import SKRIBBL, GARTIC_PHONE
from SketchfulPalette import find_sketchful_grid
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
            ('skribbl', self._skribbl_image, (190, 140, 901, 611), (-1008, 191, -299, 660)),
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

    def test_sketch_profiles_need_both_a_bounded_surface_and_a_palette(self):
        missing = {'canvas_box': None, 'canvas_confidence': 0.0}
        for profile in ('sketchheads', 'sketchful'):
            with self.subTest(profile=profile), self._sketchheads_image() as palette_only:
                setup = detect_browser_setup(profile, palette_only)
                self.assertGreaterEqual(len(setup['positions']), 8)
                self.assertIsNone(setup['canvas_box'])
                self.assertEqual(detect_browser_canvas(profile, palette_only), missing)
            # Reuse the existing framed browser layout. The paper and the
            # detached toolbar are separate, independently visible landmarks.
            with self.subTest(profile=profile), self._skribbl_image() as bordered:
                origin = (-1200, 50)
                guided = detect_browser_canvas(profile, bordered, screen_origin=origin)
                setup = detect_browser_setup(profile, bordered, screen_origin=origin)
                self.assertEqual(guided['canvas_box'], (-1010, 190, -299, 661))
                self.assertGreater(guided['canvas_confidence'], .70)
                self.assertEqual(setup['canvas_box'], guided['canvas_box'])
                with bordered.crop((0, 0, bordered.width, 630)) as paper_only:
                    self.assertEqual(detect_browser_canvas(profile, paper_only), missing)
                with bordered.crop((0, 130, bordered.width, bordered.height)) as shifted:
                    self.assertEqual(detect_browser_canvas(profile, shifted)['canvas_box'], (190, 10, 901, 481))

    def test_sketch_profiles_reject_unrelated_shipped_images(self):
        root = Path(__file__).resolve().parent
        assets = ('assets/image-draw-bot-app-screenshot.png', 'tests/fixtures/paint-light-ribbon.png',
                  'golden-regression/red-bananas-texture.png')
        for name in assets:
            with Image.open(root / name) as source:
                for profile in ('sketchheads', 'sketchful'):
                    with self.subTest(profile=profile, image=name):
                        self.assertEqual(detect_browser_canvas(profile, source),
                                         {'canvas_box': None, 'canvas_confidence': 0.0})

    def test_skribbl_palette_hint_snaps_to_edges_and_requires_both_rows(self):
        with self._skribbl_image() as scene, self._sketchheads_image() as unbounded:
            positions = detect_browser_setup('skribbl-fast', scene)['positions']
            self.assertEqual(_skribbl_palette_frame(scene, positions, lambda: False), (190, 140, 901, 611))
            self.assertIsNone(_skribbl_palette_frame(unbounded, positions, lambda: False))
            one_row = [(x, positions[0][1]) for x, y in positions]
            self.assertIsNone(_skribbl_palette_frame(scene, one_row, lambda: False))
            with self.assertRaises(InterruptedError):
                _skribbl_palette_frame(scene, positions, lambda: True)
            # Exercise the occupied-board fallback entry point using the existing
            # fixture's real palette and frame after the blank-surface pass misses.
            with patch('BrowserAutoCalibration._largest_light_component', return_value=(None, 0)):
                self.assertEqual(detect_browser_canvas('skribbl', scene, screen_origin=(-200, 30))['canvas_box'],
                                 (-10, 170, 701, 641))
                self.assertIsNone(detect_browser_canvas('skribbl', unbounded)['canvas_box'])

    def test_sketchful_grid_needs_three_aligned_rows_of_progressive_shades(self):
        # Numeric measurements from the native blank Sketchful drawer capture.
        xs = [1871, 1900, 1928, 1957, 1985, 2014, 2043, 2071, 2100, 2128, 2157, 2186, 2214]
        ys = [511, 540, 568]
        shades = [
            ['ffffff','d3d1d2','f70f0f','ff7200','fce700','02cb00','01fe94','05b0ff','221ecd','a300bd','ff69b4','fdad88','9e5425'],
            ['514f54','a9a7a8','ae0b00','c84706','ec9e06','007612','049d6f','00579d','0f0b96','6e0083','ad487b','e38a5e','5e320d'],
            ['000000','827c80','57060c','8b2500','9e6600','003f00','00766a','003b75','0e0151','3c0350','56243d','d1754e','421e06'],
        ]
        for scale in (.5, 1., 2.):
            entries = [((round(x*scale)-2100, round(y*scale)), tuple(bytes.fromhex(shades[i][j])))
                       for i, y in enumerate(ys) for j, x in enumerate(xs) if (i, j) != (2, 0)]
            points, colors = zip(*entries)
            with self.subTest(scale=scale):
                cells, centers, rows, pitch = find_sketchful_grid(points, colors)
                self.assertEqual(len(cells), 38)
                self.assertNotIn((2, 0), cells)
                self.assertIsNone(find_sketchful_grid(points[:26], colors[:26]))
                self.assertIsNone(find_sketchful_grid(points, tuple(reversed(colors))))

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
