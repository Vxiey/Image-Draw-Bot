"""Unsigned high-depth sources keep their tones instead of saturating at 255."""
from contextlib import ExitStack,closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from DrawBot import DrawBotApp
from ImageColorManagement import srgb_source
from ImageFormatInfo import image_label
from ImageImport import read_image
from SourcePixelDepth import grayscale_8bit
from test_v148_application_batch06_color_import import gray_profile
from test_v148_ui_lifecycle_batch02 import ui_app


class HighDepthSourceTests(unittest.TestCase):
    def test_real_png_and_both_tiff_byte_orders_use_full_unsigned_range(self):
        samples=[0,1,128,129,255,257,32768,65534,65535]
        expected=[round(value*255/65535) for value in samples]
        with TemporaryDirectory() as temporary:
            for dtype,suffix in (('<u2','.png'),('<u2','.tiff'),('>u2','.tiff')):
                with self.subTest(dtype=dtype,suffix=suffix):
                    path=Path(temporary)/('source'+suffix)
                    with closing(Image.fromarray(np.array([samples],dtype=dtype))) as source:source.save(path)
                    with closing(read_image(path)) as result:
                        self.assertEqual([result.getpixel((x,0)) for x in range(len(samples))],
                                         [(value,value,value,255) for value in expected])
                        self.assertIn('16-bit grayscale mapped to 8-bit',image_label(result,'source'))

    def test_all_unsigned_values_match_independent_nearest_full_range_quantization(self):
        values=np.arange(65536,dtype=np.uint16).reshape(256,256)
        with closing(Image.fromarray(values)) as source,closing(grayscale_8bit(source)) as result:
            expected=bytes(round(value*255/65535) for value in range(65536))
            self.assertEqual(result.tobytes(),expected)
            self.assertEqual(source.tobytes(),values.tobytes())

    def test_exact_transparency_key_precedes_rounding_and_gray_icc_conversion(self):
        for managed in (False,True):
            with self.subTest(managed=managed),TemporaryDirectory() as temporary:
                path=Path(temporary)/'key.png'
                with closing(Image.fromarray(np.array([[32768,32769,0,65535]],dtype=np.uint16))) as source:
                    source.info['transparency']=32768
                    if managed:source.info['icc_profile']=gray_profile()
                    source.save(path)
                with closing(read_image(path)) as result:
                    self.assertEqual([result.getpixel((x,0))[3] for x in range(4)],[0,255,255,255])
                    self.assertEqual([result.getpixel((x,0))[:3] for x in range(4)],
                                     [(128,128,128),(128,128,128),(0,0,0),(255,255,255)])
                    self.assertNotIn('transparency',result.info)

    def test_clipboard_source_uses_same_mapping_without_mutating_borrowed_pixels(self):
        app=ui_app();self.addCleanup(app.original.close)
        with closing(Image.fromarray(np.array([[0,257,32768,65535]],dtype=np.uint16))) as source,ExitStack() as stack:
            before=source.tobytes();info=dict(source.info)
            stack.enter_context(patch('PIL.ImageGrab.grabclipboard',return_value=source))
            for name in ('_clear_render_resume','_queue_drop_in_start','_queue_browser_one_click_after_import','_manual_drop_in_armed'):
                stack.enter_context(patch.object(DrawBotApp,name,return_value=False))
            DrawBotApp.paste_image(app);self.addCleanup(app.original.close)
            self.assertEqual([app.original.getpixel((x,0))[0] for x in range(4)],[0,1,128,255])
            self.assertEqual(source.tobytes(),before);self.assertEqual(source.info,info)

    def test_exif_rotation_precedes_unsigned_depth_mapping(self):
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'oriented.png'
            values=np.array([[0,257,32768],[65535,25700,51400]],dtype=np.uint16)
            with closing(Image.fromarray(values)) as source:
                exif=source.getexif();exif[274]=6;source.save(path,exif=exif)
            with closing(read_image(path)) as result:
                self.assertEqual(result.size,(2,3))
                self.assertEqual([[result.getpixel((x,y))[0] for x in range(2)] for y in range(3)],
                                 [[255,0],[100,1],[200,128]])
                self.assertNotIn(274,result.getexif())

    def test_tiles_are_bounded_and_interrupted_result_is_closed(self):
        with closing(Image.new('I;16',(2570,302),32768)) as source:
            original_new=Image.new;original_crop=Image.Image.crop;outputs=[];boxes=[]
            def create(*args,**kwargs):
                result=original_new(*args,**kwargs)
                if result.size==source.size:outputs.append(result)
                return result
            def crop(image,box):
                if image is source:boxes.append(box)
                return original_crop(image,box)
            with patch.object(Image,'new',side_effect=create),patch.object(Image.Image,'crop',crop):
                with self.assertRaises(InterruptedError):
                    grayscale_8bit(source,cancelled=lambda:len(boxes)>=1)
            self.assertEqual(len(outputs),1)
            with self.assertRaises(ValueError):outputs[0].getpixel((0,0))
            self.assertTrue(all((right-left)*(bottom-top)<=262144 for left,top,right,bottom in boxes))
            self.assertEqual(source.getpixel((0,0)),32768)

    def test_untagged_eight_bit_pixels_keep_exact_values_and_cannot_spoof_conversion(self):
        from PIL.PngImagePlugin import PngInfo
        with TemporaryDirectory() as temporary,closing(Image.new('RGBA',(3,2),(20,80,190,91))) as source:
            path=Path(temporary)/'plain.png';metadata=PngInfo()
            metadata.add_text('draw_studio_bit_depth','forged')
            source.save(path,pnginfo=metadata)
            with closing(read_image(path)) as result:
                self.assertEqual(result.tobytes(),source.tobytes())
                self.assertNotIn('16-bit',image_label(result,'plain'))

    def test_stop_after_final_untagged_conversion_closes_only_owned_output(self):
        with closing(Image.new('I;16',(3,2),32768)) as source:
            convert=Image.Image.convert;stopped=False;outputs=[]
            def converted(image,*args,**kwargs):
                nonlocal stopped
                result=convert(image,*args,**kwargs)
                if args and args[0]=='RGBA':outputs.append(result);stopped=True
                return result
            with patch.object(Image.Image,'convert',converted):
                with self.assertRaises(InterruptedError):srgb_source(source,cancelled=lambda:stopped)
            self.assertEqual(len(outputs),1)
            with self.assertRaises(ValueError):outputs[0].getpixel((0,0))
            self.assertEqual(source.getpixel((0,0)),32768)


if __name__=='__main__':unittest.main()
