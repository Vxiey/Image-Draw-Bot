import unittest
from PIL import Image, ImageDraw

from BrowserAutoCalibration import detect_browser_setup
from BrowserVisualPreflight import verify_browser_visual_preflight, _sample_indices
from PaletteMaps import GARTIC_PHONE
from Version import APP_VERSION, FILE_VERSION


class BrowserVisualPreflightTests(unittest.TestCase):
    @staticmethod
    def _gartic_image():
        im=Image.new('RGB',(1600,900),(190,45,80));d=ImageDraw.Draw(im)
        d.rectangle((470,280,1420,820),fill=(90,36,164))
        d.rectangle((480,290,1410,810),fill=(255,255,255))
        x0,y0=170,300
        for i,rgb in enumerate(GARTIC_PHONE.colors):
            row=i//6;col=i%6
            x=x0+col*24;y=y0+row*22
            d.rectangle((x,y,x+18,y+18),fill=rgb)
        return im

    @staticmethod
    def _setup(im):
        detected=detect_browser_setup('gartic-phone',im,screen_origin=(100,200))
        entries=list(zip(detected['positions'],detected['rgbs']))
        meta={'client_rect':(100,200,1700,1100),'rect':(90,170,1710,1110),'handle':123,'dpi':96}
        return detected,entries,meta

    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_verified_canvas_and_palette_pass(self):
        im=self._gartic_image();detected,entries,meta=self._setup(im)
        result=verify_browser_visual_preflight('gartic-phone',meta,detected['canvas_box'],entries,screenshot=im)
        self.assertTrue(result.passed)
        self.assertTrue(result.canvas_ok)
        self.assertGreaterEqual(result.palette_verified,5)

    def test_canvas_geometry_mismatch_blocks(self):
        im=self._gartic_image();detected,entries,meta=self._setup(im)
        l,t,r,b=detected['canvas_box']
        result=verify_browser_visual_preflight('gartic-phone',meta,(l+30,t,r+30,b),entries,screenshot=im)
        self.assertFalse(result.passed)
        self.assertFalse(result.canvas_ok)

    def test_palette_mismatch_blocks(self):
        im=self._gartic_image();detected,entries,meta=self._setup(im)
        wrong=[(pos,(0,255,0)) for pos,_rgb in entries]
        result=verify_browser_visual_preflight('gartic-phone',meta,detected['canvas_box'],wrong,screenshot=im)
        self.assertFalse(result.passed)
        self.assertLess(result.palette_verified,result.palette_tested)

    def test_one_transient_swatch_difference_is_tolerated(self):
        im=self._gartic_image();detected,entries,meta=self._setup(im)
        picked=list(_sample_indices(len(entries),6))
        changed=list(entries)
        changed[picked[0]]=(changed[picked[0]][0],(0,255,0))
        result=verify_browser_visual_preflight('gartic-phone',meta,detected['canvas_box'],changed,screenshot=im)
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.palette_verified,5)


if __name__=='__main__':unittest.main()
