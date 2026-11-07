import unittest
from PIL import Image
from ImageUpscale import upscale_image,upscale_size,suggested_factor

class UpscaleTests(unittest.TestCase):
    def test_dimensions_and_source_unchanged(self):
        image=Image.new('RGB',(31,17),'red')
        self.assertEqual(upscale_image(image,4).size,(124,68))
        self.assertEqual(image.size,(31,17))
    def test_limit_before_allocation(self):
        with self.assertRaises(ValueError):upscale_size((4000,3000),2)
    def test_factor_validation(self):
        for f in (0,1,3,-2):
            with self.assertRaises(ValueError):upscale_size((10,10),f)
    def test_suggestions(self):
        self.assertEqual(suggested_factor((128,256)),4)
        self.assertEqual(suggested_factor((640,480)),2)
        self.assertEqual(suggested_factor((1920,1080)),1)
    def test_pixel_art_exact_colours(self):
        image=Image.new('RGBA',(2,1),'red');image.putpixel((1,0),(0,0,255,255))
        result=upscale_image(image,4,'Pixel art')
        self.assertEqual(set(result.getdata()),set(image.getdata()))
    def test_no_hidden_colour_fringe(self):
        image=Image.new('RGBA',(2,1),(0,255,0,0));image.putpixel((0,0),(255,0,0,255))
        result=upscale_image(image,4)
        for r,g,b,a in result.getdata():
            if a: self.assertEqual((g,b),(0,0))
    def test_cancel_before_and_after_resize(self):
        with self.assertRaises(InterruptedError):upscale_image(Image.new('RGB',(3,3)),cancelled=lambda:True)
        calls=iter((False,True))
        with self.assertRaises(InterruptedError):upscale_image(Image.new('RGB',(3,3)),cancelled=lambda:next(calls))
    def test_format_metadata(self):
        image=Image.new('RGBA',(3,3),'red');image.info['draw_studio_format']='PNG'
        result=upscale_image(image)
        self.assertEqual(result.info['draw_studio_format'],'PNG')
        self.assertNotIn('draw_studio_upscale',image.info)
    def test_result_event_does_not_queue_drawing(self):
        from DrawBot import DrawBotApp
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        image=Image.new('RGBA',(3,3),'red')
        app=SimpleNamespace(original=image,stop=SimpleNamespace(is_set=lambda:False),color_session_cache={},file_label=Mock(),
            _mark_plan_stale=Mock(),status=Mock(),show_previews=Mock(),_schedule_recovery_checkpoint=Mock())
        with patch.object(DrawBotApp,'_clear_render_resume'),patch.object(DrawBotApp,'_queue_drop_in_start') as drop,patch.object(DrawBotApp,'_queue_browser_one_click_after_import') as browser:
            DrawBotApp._handle_event(app,'upscaled',(image,image))
            drop.assert_not_called();browser.assert_not_called()
        self.assertIs(app.original,image)
