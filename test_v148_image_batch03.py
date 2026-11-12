"""Memory, visibility and interruption contracts for local image processing."""
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import BackgroundRemoval as br
from ImageUpscale import upscale_image
from ImageFormatInfo import _has_transparency, image_label
from DrawingStyleProfiles import _metrics


class BackgroundWorkTests(unittest.TestCase):
    def subject(self, size=(80, 60)):
        image = Image.new('RGBA', size, 'white')
        ImageDraw.Draw(image).rectangle((20, 15, 59, 44), fill='red')
        return image

    def test_proxy_keeps_one_pixel_axes_and_never_exceeds_limits(self):
        for size in ((1,1500),(1500,1),(1201,20),(949,949)):
            with self.subTest(size=size):
                source=Image.new('RGB',size)
                result=br._proxy(source)
                self.assertLessEqual(max(result.size),1200)
                self.assertLessEqual(result.width*result.height,900_000)
                self.assertEqual(min(result.size),1 if min(size)==1 else min(result.size))
                self.assertEqual(source.size,size)
                result.close();source.close()

    def test_cluster_minima_match_independent_stacked_reference(self):
        rng=np.random.default_rng(908)
        a=rng.integers(0,256,(35,47,3)).astype(np.float32)
        centers=rng.integers(0,256,(4,3)).astype(np.float32)
        spreads=np.array([5,10,40,80],np.float32)
        distances=np.stack([br._distance(a,c) for c in centers])
        norms=distances/np.maximum(6.,spreads)[:,None,None]
        for mode in br.MODES:
            for strength in br.STRENGTHS:
                with self.subTest(mode=mode,strength=strength),patch.object(br.np,'stack',side_effect=AssertionError('full cluster stack')):
                    candidate,dist,norm=br._candidate_maps(a,centers,spreads,strength,mode)
                np.testing.assert_array_equal(dist,distances.min(axis=0))
                np.testing.assert_array_equal(norm,norms.min(axis=0))
                self.assertEqual(candidate.shape,a.shape[:2])

    def test_definite_background_does_not_compute_scalar_neighbor_distances(self):
        a=np.full((30,40,3),255,np.float32)
        with patch.object(br,'_distance',wraps=br._distance) as distance:
            mask,_,_,processed,_=br._grow(a,np.array([[255]*3],np.float32),np.array([10]),'Balanced','Auto',np.zeros((30,40)),lambda:False)
        self.assertEqual(processed,1200)
        self.assertTrue(np.all(mask))
        self.assertTrue(all(call.args[0].ndim>1 for call in distance.call_args_list))

    def test_largest_component_uses_bounded_row_seeds_and_row_major_ties(self):
        mask=np.zeros((50,70),np.uint8)
        mask[2:7,3:9]=1;mask[20:25,40:46]=1
        original=np.flatnonzero
        observed=[]
        def seeds(values):
            observed.append(values.shape)
            return original(values)
        with patch.object(br.np,'flatnonzero',side_effect=seeds):
            size,box=br._largest_component(mask,lambda:False)
        self.assertEqual((size,box),(30,(3,2,9,7)))
        self.assertTrue(all(shape==(70,) for shape in observed))

    def test_empty_component_scan_can_be_cancelled_without_a_flood_queue(self):
        calls=0
        def cancelled():
            nonlocal calls
            calls+=1
            return calls==2
        with self.assertRaises(InterruptedError):
            br._largest_component(np.zeros((1000,8),np.uint8),cancelled)
        self.assertEqual(calls,2)

    def test_stop_is_observed_between_cluster_distance_planes(self):
        with patch.object(br,'_distance',wraps=br._distance) as distance:
            with self.assertRaises(InterruptedError):
                br._candidate_maps(np.zeros((40,40,3),np.float32),np.zeros((4,3)),np.ones(4),'Balanced','Auto',lambda:distance.call_count>=1)
        self.assertEqual(distance.call_count,1)

    def test_invisible_rgb_does_not_change_segmentation(self):
        images=[]
        for hidden in ('black','blue'):
            source=self.subject()
            ImageDraw.Draw(source).rectangle((0,0,79,3),fill=hidden)
            alpha=source.getchannel('A');ImageDraw.Draw(alpha).rectangle((0,0,79,3),fill=0)
            source.putalpha(alpha);alpha.close()
            images.append(source)
        left=br.remove_background(images[0]);right=br.remove_background(images[1])
        self.assertEqual(left.image.getchannel('A').tobytes(),right.image.getchannel('A').tobytes())
        self.assertEqual(left.metadata,right.metadata)
        self.assertEqual(left.image.getpixel((40,30))[3],255)
        self.assertEqual(left.image.getpixel((0,20))[3],0)

    def test_analysis_rgb_conversion_occurs_after_proxy_reduction(self):
        source=self.subject((200,150));sizes=[]
        convert=Image.Image.convert
        def traced(image,mode,*args,**kwargs):
            if mode=='RGB':sizes.append(image.size)
            return convert(image,mode,*args,**kwargs)
        with patch.object(br,'_PROXY_MAX_DIMENSION',40),patch.object(Image.Image,'convert',traced):
            br.remove_background(source)
        self.assertTrue(sizes)
        self.assertTrue(all(max(size)<=40 for size in sizes))

    def test_alpha_product_matches_all_65536_pairs_with_small_strips(self):
        new=np.repeat(np.arange(256,dtype=np.uint8)[:,None],256,axis=1)
        old=np.repeat(np.arange(256,dtype=np.uint8)[None,:],256,axis=0)
        expected=((new.astype(np.uint16)*old.astype(np.uint16)+127)//255).astype(np.uint8)
        with patch.object(br,'_ALPHA_STRIP_PIXELS',512):
            result=br._multiply_alpha(Image.fromarray(new),old.tobytes())
        np.testing.assert_array_equal(np.asarray(result),expected)

    def test_alpha_product_cancellation_releases_partial_result(self):
        new=Image.new('L',(20,20),255);results=[]
        create=Image.new
        def traced(*args,**kwargs):
            result=create(*args,**kwargs);results.append(result);return result
        with patch.object(br.Image,'new',side_effect=traced),self.assertRaises(InterruptedError):
            br._multiply_alpha(new,bytes([255])*400,lambda:True)
        with self.assertRaises(ValueError):results[0].getpixel((0,0))
        self.assertEqual(new.getpixel((0,0)),255)

    def test_preservation_counts_alpha_threshold_without_exporting_full_bytes(self):
        source=Image.new('RGBA',(4,1))
        source.putdata([(10,20,30,a) for a in (0,8,9,255)])
        with patch.object(Image.Image,'tobytes',side_effect=AssertionError('full byte copy')):
            result=br._preserve(source,'Auto','Balanced','unchanged')
        self.assertEqual(result.metadata['drawable_after_percent'],50)
        self.assertIs(result.image,source)

    def test_invalid_resource_inputs_fail_before_transpose(self):
        for feather in (float('nan'),float('inf'),True,'0.6',10**1000):
            with self.subTest(feather=str(feather)[:20]),patch.object(br.ImageOps,'exif_transpose') as transpose:
                with self.assertRaises(ValueError):br.remove_background(self.subject(),feather_px=feather)
                transpose.assert_not_called()
        for size in ((0,2),(25_000_001,1)):
            source=Image.new('RGB',(1,1));source._size=size
            with self.subTest(size=size),patch.object(br.ImageOps,'exif_transpose') as transpose:
                with self.assertRaises(ValueError):br.remove_background(source)
                transpose.assert_not_called()

    def test_failure_releases_oriented_source_and_keeps_caller_alive(self):
        source=self.subject();owned=[];orient=br._oriented_rgba
        def traced(image):
            output=orient(image);owned.append(output);return output
        with patch.object(br,'_oriented_rgba',side_effect=traced),patch.object(br,'_grow',side_effect=RuntimeError('segmentation failed')):
            with self.assertRaisesRegex(RuntimeError,'segmentation failed'):br.remove_background(source)
        with self.assertRaises(ValueError):owned[0].getpixel((0,0))
        self.assertEqual(source.getpixel((0,0)),(255,255,255,255))

    def test_preserved_owned_source_remains_usable_after_success(self):
        source=Image.new('RGBA',(5,4),(10,20,30,0))
        result=br.remove_background(source)
        self.assertIsNot(result.image,source)
        self.assertEqual(result.image.tobytes(),source.tobytes())


class ImageDescriptionTests(unittest.TestCase):
    def test_alpha_extrema_do_not_allocate_a_channel_image(self):
        source=Image.new('RGBA',(40,30),'white');source.putpixel((39,29),(1,2,3,254))
        with patch.object(Image.Image,'getchannel',side_effect=AssertionError('channel copy')):
            self.assertTrue(_has_transparency(source))
        self.assertEqual(source.getpixel((39,29)),(1,2,3,254))

    def test_premultiplied_alpha_is_not_mislabeled_opaque(self):
        for mode in ('RGBa','La'):
            with self.subTest(mode=mode):
                self.assertIn('transparent pixels',image_label(Image.new(mode,(2,2)),'image'))

    def test_palette_embedded_alpha_counts_only_used_entries(self):
        source=Image.new('P',(2,1),0)
        source.putpalette([10,20,30,255,50,60,70,0]+[0,0,0,255]*254,rawmode='RGBA')
        self.assertFalse(_has_transparency(source))
        source.putpixel((1,0),1)
        self.assertTrue(_has_transparency(source))

    def test_palette_transparency_table_matches_pillow_without_full_image_conversion(self):
        source=Image.new('P',(100,80),0)
        source.putpalette([value for i in range(256) for value in (i,i,i)])
        source.info['transparency']=bytes([255,0]);source.putpixel((99,79),1)
        convert=Image.Image.convert;sizes=[]
        def traced(image,*args,**kwargs):
            sizes.append(image.size);return convert(image,*args,**kwargs)
        with patch.object(Image.Image,'convert',traced):self.assertTrue(_has_transparency(source))
        self.assertEqual(sizes,[(256,1)])

    def test_rgb_key_scan_is_bounded_and_finds_the_last_row(self):
        source=Image.new('RGB',(40,30),'white');source.info['transparency']=(1,2,3)
        source.putpixel((39,29),(1,2,3));sizes=[];convert=Image.Image.convert
        def traced(image,*args,**kwargs):
            sizes.append(image.size);return convert(image,*args,**kwargs)
        with patch('ImageFormatInfo._ALPHA_SCAN_PIXELS',120),patch.object(Image.Image,'convert',traced):
            self.assertTrue(_has_transparency(source))
        self.assertTrue(all(w*h<=120 for w,h in sizes));self.assertEqual(len(sizes),10)

    def test_drawing_style_ignores_rgb_hidden_under_zero_alpha(self):
        left=Image.new('RGBA',(80,60),'white');right=left.copy()
        for image,hidden in ((left,(0,0,255,0)),(right,(200,20,10,0))):
            ImageDraw.Draw(image).rectangle((0,0,79,30),fill=hidden)
        self.assertEqual(_metrics(left),_metrics(right))
        self.assertEqual(_metrics(left)['white'],1)
        self.assertGreater(_metrics(left)['alpha_empty'],.5)

    def test_style_analysis_never_copies_full_source(self):
        source=Image.new('RGB',(4000,3000),'red');copy=Image.Image.copy
        def bounded(image):
            self.assertLessEqual(max(image.size),160)
            return copy(image)
        with patch.object(Image.Image,'copy',bounded):
            result=_metrics(source)
        self.assertEqual(result['chroma'],1)
        self.assertEqual(source.size,(4000,3000))

    def test_style_sampling_preserves_thumbnail_geometry_on_extreme_aspects(self):
        resize=Image.Image.resize;targets=[]
        for size in ((4000,9),(9,4000),(355,160),(160,355),(417,321)):
            source=Image.new('RGB',size,'red');reference=source.copy();reference.thumbnail((160,160),Image.Resampling.NEAREST)
            def traced(image,target,*args,**kwargs):
                if image is source:targets.append(target)
                return resize(image,target,*args,**kwargs)
            with patch.object(Image.Image,'resize',traced):_metrics(source)
            self.assertEqual(targets[-1],reference.size)


class UpscaleOwnershipTests(unittest.TestCase):
    def test_stop_after_orientation_prevents_larger_resize(self):
        from PIL import ImageOps
        source=Image.new('RGBA',(8,6),'red');stop=threading.Event();owned=[]
        source.getexif()[274]=6  # Exercise the remaining owned orientation transform.
        transpose=ImageOps.exif_transpose
        def interrupted(image):
            result=transpose(image);owned.append(result);stop.set();return result
        with patch('ImageUpscale.ImageOps.exif_transpose',side_effect=interrupted),patch.object(Image.Image,'resize') as resize:
            with self.assertRaises(InterruptedError):upscale_image(source,4,cancelled=stop.is_set)
        resize.assert_not_called()
        with self.assertRaises(ValueError):owned[0].getpixel((0,0))
        self.assertEqual(source.getpixel((0,0)),(255,0,0,255))

    def test_smooth_resize_failure_closes_owned_images_but_preserves_borrowed_source(self):
        source=Image.new('RGBA',(8,6),'red');images=[]
        convert=Image.Image.convert
        def traced(image,*args,**kwargs):
            result=convert(image,*args,**kwargs)
            if image is not source:images.append(image)
            images.append(result);return result
        with patch.object(Image.Image,'convert',traced),patch.object(Image.Image,'resize',side_effect=RuntimeError('resample failed')):
            with self.assertRaisesRegex(RuntimeError,'resample failed'):upscale_image(source)
        for image in images:
            with self.assertRaises(ValueError):image.getpixel((0,0))
        self.assertEqual(source.getpixel((0,0)),(255,0,0,255))

    def test_oriented_transparent_pixel_art_output_and_metadata_survive_cleanup(self):
        source=Image.new('RGBA',(3,2),(10,30,50,0));source.putpixel((0,0),(255,0,0,255))
        source.getexif()[274]=6
        result=upscale_image(source,2,method='Pixel art')
        self.assertEqual(result.size,(4,6))
        self.assertEqual(result.getpixel((3,0)),(255,0,0,255))
        self.assertEqual(result.info['draw_studio_upscale']['source_size'],(2,3))
        self.assertEqual(source.getexif()[274],6)


if __name__=='__main__':unittest.main()
