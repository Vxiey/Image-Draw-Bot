"""Visibility, resource limits and dialog ownership for subject selection."""
from contextlib import ExitStack
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock,patch

import numpy as np
from PIL import Image,ImageDraw,ImageOps

from DrawBot import DrawBotApp
import SubjectFocus as focus
import SubjectSelector as selector
from test_v148_ui_lifecycle_batch02 import ui_app


class SubjectMaskTests(unittest.TestCase):
    def test_fully_transparent_colours_cannot_become_an_automatic_subject(self):
        image=Image.new('RGBA',(60,40),(255,255,255,0))
        ImageDraw.Draw(image).rectangle((20,10,39,29),fill=(255,0,0,0))
        with self.assertRaisesRegex(ValueError,'No visible subject'):focus.subject_mask(image)

    def test_partial_alpha_analysis_matches_the_visible_white_composite(self):
        image=Image.new('RGBA',(60,40),(0,0,0,5))
        ImageDraw.Draw(image).rectangle((20,10,39,29),fill=(0,0,0,255))
        visible=Image.new('RGBA',image.size,'white');visible.alpha_composite(image)
        actual,_=focus.subject_mask(image);expected,_=focus.subject_mask(visible)
        np.testing.assert_array_equal(actual,expected)
        self.assertEqual(int(actual.sum()),400)

    def test_partial_palette_alpha_preserves_the_same_subject_as_rgba(self):
        palette=Image.new('P',(60,40),0)
        palette.putpalette([0,0,0,5,0,0,0,255]+[255,255,255,255]*254,rawmode='RGBA')
        ImageDraw.Draw(palette).rectangle((20,10,39,29),fill=1)
        expected,_=focus.subject_mask(palette.convert('RGBA'))
        actual,_=focus.subject_mask(palette)
        np.testing.assert_array_equal(actual,expected)

    def test_invalid_rectangles_and_dimensions_fail_before_mask_allocation(self):
        with patch.object(focus.np,'zeros') as allocate:
            for size,region in (((0,2),(0,0,1,1)),((True,4),(0,0,1,1)),((8001,8000),(0,0,1,1)),
                                ((2,2),(0,0,float('nan'),1)),((2,2),(0,0,True,1)),((2,2),None),
                                ((np.int64(2**32),np.int64(2**32)),(0,0,1,1))):
                with self.subTest(size=size,region=region),self.assertRaises(ValueError):focus.rectangle_mask(size,region)
        allocate.assert_not_called()

    def test_alpha_mask_decoding_is_tiled_and_can_stop_midway(self):
        image=Image.new('RGBA',(80,60),'red');image.putpixel((0,0),(0,0,0,0))
        sizes=[];convert=Image.Image.convert;stop=threading.Event()
        def traced(part,*args,**kwargs):
            sizes.append(part.size)
            if len(sizes)==2:stop.set()
            return convert(part,*args,**kwargs)
        with patch.object(focus,'_ALPHA_STRIP_PIXELS',400),patch.object(Image.Image,'convert',traced),self.assertRaises(InterruptedError):
            focus.subject_mask(image,cancelled=stop.is_set)
        self.assertEqual(sizes,[(80,5),(80,5)])
        self.assertEqual(image.size,(80,60))

    def test_explicit_region_stop_after_allocation_is_not_reported_as_success(self):
        image=Image.new('RGB',(40,30),'white');stop=threading.Event();original=focus.rectangle_mask
        def allocated(*args):
            result=original(*args);stop.set();return result
        with patch.object(focus,'rectangle_mask',side_effect=allocated),self.assertRaises(InterruptedError):
            focus.subject_mask(image,(.1,.1,.8,.8),stop.is_set)

    def test_large_opaque_analysis_converts_only_the_bounded_sample(self):
        image=Image.new('RGB',(2000,1500),'white')
        ImageDraw.Draw(image).rectangle((600,400,1399,1099),fill='red')
        sizes=[];convert=Image.Image.convert
        def traced(part,*args,**kwargs):
            sizes.append(part.size);return convert(part,*args,**kwargs)
        with patch.object(Image.Image,'convert',traced):mask,_=focus.subject_mask(image)
        self.assertTrue(sizes);self.assertTrue(all(max(size)<=384 for size in sizes))
        self.assertEqual(mask.shape,(1500,2000));self.assertTrue(mask[700,1000]);self.assertFalse(mask[0,0])


class SubjectDialogTests(unittest.TestCase):
    def parent(self):
        parent=Mock();parent.winfo_screenwidth.return_value=1200;parent.winfo_screenheight.return_value=800
        return parent

    def test_preview_reduces_before_rotation_and_preserves_exif_and_caller(self):
        image=Image.new('RGB',(1600,1200),'red');image.getexif()[274]=6
        transpose=ImageOps.exif_transpose;sizes=[]
        def traced(part):
            sizes.append(part.size);return transpose(part)
        with patch.object(ImageOps,'exif_transpose',side_effect=traced):preview=selector._preview_rgba(image,(200,100))
        self.assertEqual(preview.size,(75,100));self.assertEqual(sizes,[(100,75)])
        self.assertEqual(image.size,(1600,1200));self.assertEqual(image.getexif()[274],6)
        self.assertEqual(preview.getpixel((0,0)),(255,0,0,255))

    def test_selector_shows_transparent_pixels_on_white_and_closes_failed_dialog(self):
        image=Image.new('RGBA',(10,10),(200,0,0,0));pixels=[]
        with patch('UiCompatibility.scoped_toplevel') as top,patch('customtkinter.CTkLabel'),\
             patch('customtkinter.CTkButton',side_effect=RuntimeError('cannot build button')),\
             patch('tkinter.Canvas'),patch('PIL.ImageTk.PhotoImage',side_effect=lambda flat:pixels.append(flat.getpixel((0,0))) or Mock()):
            with self.assertRaisesRegex(RuntimeError,'cannot build button'):selector.select_subject(self.parent(),image,Mock())
            top.return_value.destroy.assert_called_once()
        self.assertEqual(pixels,[(255,255,255,255)])
        self.assertEqual(image.getpixel((0,0)),(200,0,0,0))

    def test_selection_cannot_apply_twice_or_apply_an_invalid_rectangle(self):
        bindings={};buttons=[];callback=Mock()
        with patch('UiCompatibility.scoped_toplevel') as top,patch('customtkinter.CTkLabel'),\
             patch('customtkinter.CTkButton',side_effect=lambda *args,**kwargs:buttons.append(kwargs) or Mock()),\
             patch('tkinter.Canvas') as canvas,patch('PIL.ImageTk.PhotoImage'):
            canvas.return_value.bind.side_effect=lambda name,fn:bindings.__setitem__(name,fn)
            selector.select_subject(self.parent(),Image.new('RGB',(20,10),'red'),callback)
            self.assertEqual(buttons[0]['state'],'disabled');buttons[0]['command']();callback.assert_not_called()
            bindings['<Button-1>'](SimpleNamespace(x=2,y=1))
            bindings['<B1-Motion>'](SimpleNamespace(x=12,y=9))
            buttons[0]['command']();buttons[0]['command']()
            callback.assert_called_once_with((.1,.1,.6,.9));top.return_value.destroy.assert_called_once()

    def test_mask_overlay_remains_alive_until_its_own_dialog_is_destroyed(self):
        image=Image.new('RGBA',(10,10),(255,0,0,0));image.putpixel((5,5),(255,0,0,255))
        bindings={};overlays=[]
        with patch('UiCompatibility.scoped_toplevel') as top,patch('customtkinter.CTkLabel'),\
             patch('customtkinter.CTkImage',side_effect=lambda **kwargs:overlays.append(kwargs['light_image']) or Mock()):
            top.return_value.bind.side_effect=lambda name,fn,**kwargs:bindings.__setitem__(name,fn)
            selector.show_mask(self.parent(),image)
            self.assertEqual(overlays[0].getpixel((5,5)),(255,0,0))
            bindings['<Destroy>'](SimpleNamespace(widget=object()))
            self.assertEqual(overlays[0].getpixel((5,5)),(255,0,0))
            bindings['<Destroy>'](SimpleNamespace(widget=top.return_value))
            with self.assertRaises(ValueError):overlays[0].getpixel((5,5))
        self.assertEqual(image.getpixel((5,5)),(255,0,0,255))

    def test_late_subject_result_cannot_change_a_different_image_or_busy_operation(self):
        for action in ('image','busy','closing'):
            app=ui_app();app.subject_region=None;app.subject_hint=Mock();app.subject_focus=Mock();app.subject_focus_changed=Mock()
            with patch.object(selector,'select_subject') as dialog:DrawBotApp.mark_subject(app)
            callback=dialog.call_args.args[2]
            if action=='image':app.original=Image.new('RGBA',(3,2),'blue')
            elif action=='busy':app.activity='draw'
            else:app.closing=True
            callback((0,0,1,1))
            self.assertIsNone(app.subject_region);app.subject_focus_changed.assert_not_called()


if __name__=='__main__':unittest.main()
