import unittest
from pathlib import Path
from PIL import Image,ImageDraw
from BackgroundRemoval import remove_background,png_export_ready
from PixelData import build_strokes
from Version import APP_VERSION

class Rc28BackgroundRemovalTests(unittest.TestCase):
    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc1')
    def test_white_border_becomes_transparent_but_internal_white_survives(self):
        im=Image.new('RGBA',(100,100),'white');d=ImageDraw.Draw(im);d.rectangle((20,20,80,80),fill=(20,20,20,255));d.rectangle((40,40,60,60),fill='white')
        r=remove_background(im)
        self.assertEqual(r.image.getpixel((0,0))[3],0)
        self.assertGreater(r.image.getpixel((50,50))[3],200)
        self.assertGreater(r.metadata['estimated_work_reduction_percent'],20)
    def test_transparency_reduces_planner_strokes(self):
        im=Image.new('RGBA',(80,80),'white');ImageDraw.Draw(im).rectangle((30,30,50,50),fill='black')
        out=remove_background(im).image
        groups=build_strokes(out,lines=True,skip_white=False)
        count=sum(len(g) for g in groups)
        self.assertLess(count,40)
    def test_all_one_colour_fails_closed(self):
        im=Image.new('RGBA',(80,80),'white');r=remove_background(im)
        self.assertIsNotNone(r.metadata['no_op_reason']);self.assertEqual(r.image.getpixel((0,0))[3],255)
    def test_png_export_is_rgba(self):self.assertEqual(png_export_ready(Image.new('RGB',(2,2))).mode,'RGBA')
    def test_ui_and_worker_hooks_present(self):
        ui=Path('StudioUI.py').read_text(encoding='utf-8');core=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('Remove BG',ui);self.assertIn('save_png_copy',core);self.assertIn("begin_worker('background-remove'",core)
        self.assertIn("elif kind=='background_removed'",core)

if __name__=='__main__':unittest.main()
