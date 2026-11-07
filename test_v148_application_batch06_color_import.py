"""Embedded ICC input must become the sRGB numbers used by the planner."""
from contextlib import ExitStack,closing
from io import BytesIO
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image,ImageCms
from DrawBot import DrawBotApp
from ImageColorManagement import MAX_ICC_BYTES,srgb_source
from ImageImport import read_image
from test_v148_ui_lifecycle_batch02 import ui_app, paste_and_deliver_bitmap


def swapped_primaries_profile():
    # Valid matrix RGB profile with identical sRGB transfer curves, but red
    # and blue colorants exchanged. The independent expected mapping is BGR.
    profile=bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    count=struct.unpack_from('>I',profile,128)[0]
    changed=0
    for index in range(count):
        offset=132+12*index;tag=bytes(profile[offset:offset+4])
        if tag==b'rXYZ':profile[offset:offset+4]=b'bXYZ';changed+=1
        elif tag==b'bXYZ':profile[offset:offset+4]=b'rXYZ';changed+=1
    assert changed==2
    return bytes(profile)


def gray_profile():
    # A generated matrix/TRC profile: retain the sRGB gray tone curve and
    # white point, declare GRAY and expose the curve through its gray tag.
    raw=bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    raw[16:20]=b'GRAY'
    for index in range(struct.unpack_from('>I',raw,128)[0]):
        offset=132+12*index
        if raw[offset:offset+4]==b'rTRC':raw[offset:offset+4]=b'kTRC'
    return bytes(raw)


class SourceProfileTests(unittest.TestCase):
    def test_file_import_applies_profile_and_retains_correct_srgb_tag(self):
        with TemporaryDirectory() as temporary,closing(Image.new('RGB',(3,2))) as image:
            pixels=[(220,40,10),(15,60,200),(0,0,0),(255,255,255),(50,100,150),(17,201,30)]
            image.putdata(pixels);image.info['icc_profile']=swapped_primaries_profile()
            path=Path(temporary)/'color.png';image.save(path)
            with closing(read_image(path)) as result:
                for actual,(r,g,b) in zip((result.getpixel((x,y)) for y in range(2) for x in range(3)),pixels):
                    self.assertTrue(all(abs(a-e)<=1 for a,e in zip(actual,(b,g,r,255))))
                self.assertEqual(ImageCms.ImageCmsProfile(BytesIO(result.info['icc_profile'])).profile.xcolor_space.strip(),'RGB')
                # A second round trip must not interpret the already converted
                # RGB values using the old, different embedded primaries.
                result.save(path)
                with closing(read_image(path)) as again:self.assertEqual(again.tobytes(),result.tobytes())
                self.assertEqual(result.info['draw_studio_format'],'PNG')

    def test_alpha_and_indexed_transparency_survive_color_conversion(self):
        for mode in ('RGBA','RGB','P'):
            with self.subTest(mode=mode),closing(Image.new('RGB',(2,1),(220,40,10))) as base:
                source=base.convert(mode)
                try:
                    if mode=='RGBA':source.putalpha(87)
                    elif mode=='RGB':source.info['transparency']=(220,40,10)
                    else:
                        source.putpalette([220,40,10]+[0]*765);source.putdata([0,0])
                        source.info['transparency']=0
                    source.info['icc_profile']=swapped_primaries_profile()
                    before=source.tobytes();info=dict(source.info)
                    with closing(srgb_source(source)) as result:
                        self.assertEqual(result.getpixel((0,0))[3],87 if mode=='RGBA' else 0)
                        self.assertTrue(all(abs(a-e)<=1 for a,e in zip(result.getpixel((0,0))[:3],(10,40,220))))
                        self.assertNotIn('transparency',result.info)
                    self.assertEqual(source.tobytes(),before);self.assertEqual(source.info,info)
                finally:source.close()

    def test_gray_profiles_keep_opaque_colorkey_and_explicit_alpha(self):
        for mode,transparent in (('L',False),('L',True),('LA',False)):
            with self.subTest(mode=mode,colorkey=transparent),TemporaryDirectory() as temporary:
                with closing(Image.new(mode,(2,1))) as source:
                    source.putdata([128,200] if mode=='L' else [(128,61),(200,172)])
                    source.info['icc_profile']=gray_profile()
                    if transparent:source.info['transparency']=128
                    path=Path(temporary)/'gray.png';source.save(path)
                    with closing(read_image(path)) as result:
                        expected=(61,172) if mode=='LA' else ((0,255) if transparent else (255,255))
                        self.assertEqual(tuple(result.getpixel((x,0))[3] for x in range(2)),expected)
                        for x,value in enumerate((128,200)):
                            self.assertTrue(all(abs(channel-value)<=1 for channel in result.getpixel((x,0))[:3]))

    def test_lab_profile_conversion_explicitly_keeps_source_opaque(self):
        profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB')).tobytes()
        with closing(Image.new('LAB',(2,1),(128,128,128))) as source:
            source.info['icc_profile']=profile
            before=source.tobytes()
            with closing(srgb_source(source)) as result:
                self.assertEqual([result.getpixel((x,0))[3] for x in range(2)],[255,255])
                r,g,b,_=result.getpixel((0,0))
                self.assertTrue(110<=r<=130 and abs(r-g)<=1 and abs(r-b)<=1)
            self.assertEqual(source.tobytes(),before)

    def test_clipboard_uses_the_same_color_contract_without_mutating_its_source(self):
        app=ui_app();self.addCleanup(app.original.close)
        with closing(Image.new('RGBA',(3,2),(220,40,10,100))) as source,ExitStack() as stack:
            source.info['icc_profile']=swapped_primaries_profile()
            stack.enter_context(patch('PIL.ImageGrab.grabclipboard',return_value=source))
            for name in ('_clear_render_resume','_queue_drop_in_start','_queue_browser_one_click_after_import','_manual_drop_in_armed'):
                stack.enter_context(patch.object(DrawBotApp,name,return_value=False))
            paste_and_deliver_bitmap(app)
            self.addCleanup(app.original.close)
            self.assertEqual(app.original.getpixel((0,0)),(10,40,220,100))
            self.assertEqual(source.getpixel((0,0)),(220,40,10,100))

    def test_bad_or_oversize_profile_fails_before_transforming_pixels(self):
        with closing(Image.new('RGBA',(3,2))) as source:
            for raw in (b'not an ICC profile',b'0'*(MAX_ICC_BYTES+1),'not bytes'):
                source.info['icc_profile']=raw
                with self.subTest(kind=type(raw).__name__),patch.object(ImageCms,'profileToProfile') as transform:
                    with self.assertRaisesRegex(ValueError,'color profile'):srgb_source(source)
                transform.assert_not_called()
                self.assertEqual(source.size,(3,2))

    def test_stop_after_transform_closes_output_without_closing_source(self):
        with closing(Image.new('RGBA',(3,2),(220,40,10,100))) as source:
            source.info['icc_profile']=swapped_primaries_profile()
            original=ImageCms.profileToProfile;outputs=[];stopped=False
            def transform(*args,**kwargs):
                nonlocal stopped
                result=original(*args,**kwargs);outputs.append(result);stopped=True;return result
            with patch.object(ImageCms,'profileToProfile',side_effect=transform):
                with self.assertRaises(InterruptedError):srgb_source(source,cancelled=lambda:stopped)
            with self.assertRaises(ValueError):outputs[0].getpixel((0,0))
            self.assertEqual(source.getpixel((0,0)),(220,40,10,100))

    def test_untagged_files_keep_exact_pixels_and_cannot_spoof_conversion_status(self):
        from PIL.PngImagePlugin import PngInfo
        from ImageFormatInfo import image_label
        with TemporaryDirectory() as temporary,closing(Image.new('RGBA',(3,2),(10,20,30,40))) as source:
            metadata=PngInfo();metadata.add_text('draw_studio_color_managed','fake')
            path=Path(temporary)/'plain.png';source.save(path,pnginfo=metadata)
            with closing(read_image(path)) as result:
                self.assertEqual(result.tobytes(),source.tobytes())
                self.assertNotIn('color profile',image_label(result,'plain'))


if __name__=='__main__':unittest.main()
