"""Deterministic image/coordinate tests, using generated inputs only."""
import random
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image,ImageDraw,ImageFilter,ImageOps

import AnchorTransform as transform
import BrowserAutoCalibration as browser
import CanvasAnchorDetection as anchors
import PaletteMaps as palette
import PaintFullCalibration as paint
from test_canvas_anchor_detection_v1049 import triangle_image
import test_paint_full_v106 as paint_fixture


class TriangleRegressionTests(unittest.TestCase):
    def test_small_noise_does_not_starve_later_six_triangles(self):
        image=Image.new('RGB',(220,300),'white');image.paste(triangle_image(),(0,160))
        for i in range(130):image.putpixel((10+(i%20)*10,10+(i//20)*10),(0,0,0))
        self.assertEqual(len(anchors.detect_triangle_anchors(image)),6)

    def test_transparent_hidden_markers_cannot_become_anchors(self):
        image=triangle_image().convert('RGBA');image.putalpha(0)
        self.assertEqual(anchors.detect_triangle_anchors(image),())
        keyed=triangle_image();keyed.info['transparency']=(0,0,0)
        self.assertEqual(anchors.detect_triangle_anchors(keyed),())

    def test_zero_expected_avoids_analysis(self):
        with patch.object(anchors,'_binary_foreground') as scan:
            self.assertEqual(anchors.detect_triangle_anchors(triangle_image(),0),())
        scan.assert_not_called()

    def test_triangle_candidate_sample_is_really_bounded(self):
        points=[(x,y) for y in range(50) for x in range(y+1)]
        original=anchors._farthest;lengths=[]
        def farthest(points,origin):lengths.append(len(points));return original(points,origin)
        with patch.object(anchors,'_farthest',side_effect=farthest):
            anchors._candidate_from_component(points,200,200)
        self.assertTrue(lengths)
        self.assertLessEqual(max(lengths),700)

    def test_oversized_component_retains_no_candidate_points(self):
        mask=[bytearray([1]*60) for _ in range(60)]
        self.assertEqual(anchors._component_points(mask,max_side=20),[])

    def test_component_walk_is_cancellable(self):
        mask=[bytearray([1]*100) for _ in range(100)]
        cancelled=Mock(side_effect=[False,True])
        with self.assertRaises(InterruptedError):anchors._component_points(mask,cancelled=cancelled)

    def test_vector_mask_matches_scalar_reference(self):
        rng=np.random.default_rng(72)
        images=[Image.fromarray(rng.integers(0,256,size=(35,51,3),dtype=np.uint8)),triangle_image(),Image.new('RGB',(80,50),'white')]
        for image in images:
            bg=anchors._border_background(image);expected=[]
            with ImageOps.grayscale(image) as gray:
                with gray.filter(ImageFilter.FIND_EDGES) as edges:
                    for y in range(image.height):
                        row=bytearray(image.width)
                        for x in range(image.width):
                            color=image.getpixel((x,y))
                            row[x]=int(sum(abs(color[i]-bg[i]) for i in range(3))>=95 or max(color)-min(color)>=55 or edges.getpixel((x,y))>=115)
                        expected.append(row)
            self.assertEqual(anchors._binary_foreground(image),expected)


class SwatchAndCanvasRegressionTests(unittest.TestCase):
    def test_tiled_scan_keeps_valid_swatches_when_other_tiles_are_empty(self):
        image=Image.new('RGB',(200,200),(240,240,240));draw=ImageDraw.Draw(image)
        colors=[(i*30,20,180-i*20) for i in range(6)]
        for i,color in enumerate(colors):draw.rectangle((8+i*30,8,27+i*30,27),fill=color)
        positions,rgbs,_=browser._palette_scan_tiles(image,(0,0,200,200),(0,0),max_pixels=10000)
        self.assertEqual(set(rgbs),set(colors))
        self.assertEqual(len(positions),6)

    def test_invalid_tile_budget_cannot_enter_nonterminating_loop(self):
        image=Image.new('RGB',(200,200),'white')
        for budget in (-1,0,True,1.5,1_000_001):
            with self.subTest(budget=budget),self.assertRaises(ValueError):
                browser._palette_scan_tiles(image,(0,0,200,200),(0,0),max_pixels=budget)

    def test_tile_cancellation_is_not_misreported_as_empty_palette(self):
        with self.assertRaises(InterruptedError):
            browser._palette_scan_tiles(Image.new('RGB',(200,200),'white'),(0,0,200,200),(0,0),max_pixels=10000,cancelled=lambda:True)

    def test_large_roi_does_not_allocate_an_unused_full_palette_crop(self):
        from types import SimpleNamespace
        image=SimpleNamespace(mode='RGB',size=(5000,4000),width=5000,height=4000,crop=Mock(side_effect=AssertionError('unexpected full crop')))
        points=[(500+i*80,3300) for i in range(10)];colors=[(i*20,20,150) for i in range(10)]
        with patch.object(browser,'_palette_scan_tiles',return_value=(points,colors,{})) as scan,patch.object(browser,'_row_cluster',return_value=[(*point,rgb) for point,rgb in zip(points,colors)]),patch.object(browser,'_canvas',return_value=((100,200,4500,3000),.9)):
            result=browser.detect_browser_setup('sketchheads',image)
        self.assertEqual(len(result['positions']),10);scan.assert_called_once();image.crop.assert_not_called()

    def test_empty_swatch_failure_has_distinct_type(self):
        with self.assertRaises(palette.NoColorSwatchesError):palette.detect_color_swatches(Image.new('RGB',(50,50),'white'))
        with self.assertRaises(ValueError) as error:palette.detect_color_swatches(Image.new('RGB',(2,2),'white'))
        self.assertNotIsInstance(error.exception,palette.NoColorSwatchesError)

    def test_span_components_match_independent_pixel_walk_and_order(self):
        rng=random.Random(81)
        for trial in range(25):
            image=Image.new('RGB',(70,50),'white');draw=ImageDraw.Draw(image)
            for _ in range(25):
                x,y=rng.randrange(64),rng.randrange(44);w,h=rng.randrange(2,15),rng.randrange(2,14)
                draw.rectangle((x,y,x+w,y+h),fill=rng.choice(['red','blue','white','black']))
            with self.subTest(trial=trial):
                self.assertEqual(palette._span_components(image,lambda:False),list(palette._pixel_components(image,lambda:False)))

    def test_noise_dispatch_does_not_build_large_span_union_table(self):
        rng=np.random.default_rng(19)
        image=Image.fromarray(rng.integers(0,256,size=(100,100,3),dtype=np.uint8))
        self.assertEqual(palette._span_components(image,lambda:False),[])
        ImageDraw.Draw(image).rectangle((20,20,40,40),fill='red')
        self.assertIsNone(palette._span_components(image,lambda:False))
        self.assertIn((255,0,0),palette.detect_color_swatches(image)[1])

    def test_light_component_cancellation_reaches_inner_analysis(self):
        image=Image.new('RGB',(1200,800),'white');calls=[0]
        def cancelled():calls[0]+=1;return calls[0]>=2
        with self.assertRaises(InterruptedError):browser._largest_light_component(image,cancelled=cancelled)

    def test_light_component_rejects_invalid_sampling_step(self):
        image=Image.new('RGB',(120,80),'white')
        for step in (0,-1,True,1.5):
            with self.subTest(step=step),self.assertRaises(ValueError):browser._largest_light_component(image,step=step)

    def test_paint_references_are_cached_and_immutable(self):
        paint._reference_templates.cache_clear()
        original=paint.Image.open
        with patch.object(paint.Image,'open',wraps=original) as opened:
            first=paint._reference_templates();second=paint._reference_templates()
        self.assertIs(first,second);self.assertEqual(opened.call_count,1)
        with self.assertRaises(TypeError):first['new']=None
        with self.assertRaises(ValueError):first['Pencil'][0][0,0,0]=0

    def test_paint_cancel_after_canvas_analysis_cannot_return_success(self):
        image=paint_fixture.PaintFullTests().screenshot();cancelled=[False];original=paint._detect_visible_canvas
        def finish(*args,**kwargs):
            result=original(*args,**kwargs);cancelled[0]=True;return result
        with patch.object(paint,'_detect_visible_canvas',side_effect=finish),self.assertRaises(InterruptedError):
            paint.detect_setup(image,cancelled=lambda:cancelled[0])

    def test_paint_manual_boundary_cannot_extend_one_pixel_outside_window(self):
        image=paint_fixture.PaintFullTests().screenshot()
        with self.assertRaises(ValueError):paint.detect_setup(image,canvas_box_override=(-1,300,800,700))


class AnchorTransformBoundaryTests(unittest.TestCase):
    def test_nonfinite_scale_threshold_cannot_disable_resize_limit(self):
        for threshold in (float('nan'),float('inf'),-1,True):
            with self.subTest(threshold=threshold),self.assertRaises(ValueError):
                transform.estimate_client_transform((0,0,800,600),(0,0,820,620),max_scale_delta=threshold)

    def test_nonfinite_and_native_overflow_geometry_is_rejected(self):
        for rect in ((0,0,float('inf'),600),(0,0,2**40,600),(False,0,800,600)):
            with self.subTest(rect=rect),self.assertRaises(ValueError):transform.estimate_client_transform(rect,(0,0,800,600))

    def test_rejected_or_invalid_transform_cannot_emit_coordinates(self):
        cases=[transform.AnchorTransformResult(0,0,accepted=False),transform.AnchorTransformResult(float('nan'),0),transform.AnchorTransformResult(0,0,sx=-1),transform.AnchorTransformResult(2**31-1,0)]
        for candidate in cases:
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):transform.transform_points([(2,3)],candidate)

    def test_canvas_rebase_requires_original_and_new_client_containment(self):
        with self.assertRaises(ValueError):transform.rebase_canvas_area((-1,50,200,200),(0,0,800,600),(50,50,850,650))
        self.assertEqual(transform.rebase_canvas_area((100,50,200,200),(0,0,800,600),(50,50,850,650))[0],(150,100,200,200))

    def test_negative_margin_cannot_expand_client_authority(self):
        with self.assertRaises(ValueError):transform.area_inside_client((-1,0,100,100),(0,0,100,100),margin=-1)

    def test_collapsed_transform_does_not_invent_one_pixel_area(self):
        with self.assertRaises(ValueError):transform.transform_area((0,0,1,1),transform.AnchorTransformResult(0,0,sx=.01,sy=.01))


def benchmark_checkpoint():
    """Opt-in paired CPU benchmark: python this_file.py --benchmark (never CI input)."""
    import importlib.util,json,platform,statistics,subprocess,sys,time
    from pathlib import Path
    import GarticOpacity as opacity
    import test_browser_auto_calibration_v1070 as browser_fixture
    checkpoint='1c09774ad22088c5c30a8f8220b6b451fdee9659'
    def previous(name):
        source=subprocess.check_output(['git','show',checkpoint+':'+name+'.py'],text=True)
        spec=importlib.util.spec_from_loader('_calibration_before_'+name,loader=None)
        module=importlib.util.module_from_spec(spec);sys.modules[module.__name__]=module
        exec(compile(source,name+'.py','exec'),module.__dict__)
        return module
    old_palette=previous('PaletteMaps');old_browser=previous('BrowserAutoCalibration')
    old_paint=previous('PaintFullCalibration');old_triangle=previous('CanvasAnchorDetection')
    old_opacity=previous('GarticOpacity')
    old_browser.detect_color_swatches=old_palette.detect_color_swatches
    old_paint.detect_color_swatches=old_palette.detect_color_swatches
    skribbl=browser_fixture.BrowserAutoCalibrationTests._skribbl_image()
    paint_image=paint_fixture.PaintFullTests().screenshot();tri=triangle_image()
    noise=Image.fromarray(np.random.default_rng(108).integers(0,256,size=(200,200,3),dtype=np.uint8))
    slider=Image.new('RGB',(1000,700),(245,245,245));ImageDraw.Draw(slider).line((480,561,740,561),fill=(50,50,50),width=4)
    colors=Image.new('RGB',(400,200),'white');draw=ImageDraw.Draw(colors)
    for i in range(10):draw.rectangle((8+38*i,30,32+38*i,60),fill=(i*20,20,180-i*15))
    row_points=[(40+i*24,650) for i in range(36)];row_rgbs=[(i*6,20,180-i*4) for i in range(36)]
    cases=[
        ('skribbl_setup',lambda:old_browser.detect_browser_setup('skribbl',skribbl),lambda:browser.detect_browser_setup('skribbl',skribbl)),
        ('paint_setup',lambda:old_paint.detect_setup(paint_image),lambda:paint.detect_setup(paint_image)),
        ('six_triangle_detection',lambda:[x.as_dict() for x in old_triangle.detect_triangle_anchors(tri)],lambda:[x.as_dict() for x in anchors.detect_triangle_anchors(tri)]),
        ('solid_palette_scan',lambda:old_palette.detect_color_swatches(colors),lambda:palette.detect_color_swatches(colors)),
        ('noisy_palette_rejection',lambda:old_palette.detect_color_swatches(noise),lambda:palette.detect_color_swatches(noise)),
        ('opacity_slider_contrast',lambda:old_opacity._slider_confidence(slider,(0,0,1000,700),(482,561),(746,561)),lambda:opacity._slider_confidence(slider,(0,0,1000,700),(482,561),(746,561))),
        ('palette_row_clustering',lambda:old_browser._row_cluster(row_points,row_rgbs,image_width=1200,image_height=800),lambda:browser._row_cluster(row_points,row_rgbs,image_width=1200,image_height=800)),
    ]
    def result(function):
        try:return function()
        except ValueError as error:return ('ValueError',str(error))
    def median(function):
        timings=[]
        for _ in range(7):
            started=time.perf_counter();result(function);timings.append((time.perf_counter()-started)*1000)
        return statistics.median(timings)
    rows=[]
    for name,before,after in cases:
        left,right=result(before),result(after)
        parity=abs(left-right)<1e-9 if isinstance(left,float) else left==right
        if not parity:raise AssertionError('Benchmark output changed: '+name)
        old,new=median(before),median(after)
        row={'case':name,'before_ms':round(old,4),'after_ms':round(new,4),'speedup':round(old/new,3),'equal_output':True}
        print(json.dumps(row),flush=True);rows.append(row)
    report={'baseline':checkpoint,'python':platform.python_version(),'platform':platform.platform(),'numpy':np.__version__,'repeats':7,
            'method':'Paired median warm perf_counter timings on one CPU environment. Generated/repository image fixtures. Float output comparison tolerance 1e-9. No GPU or native input.',
            'cases':rows}
    Path('docs/v148-batch02-calibration-benchmarks.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    import sys
    if sys.argv[1:]==['--benchmark']:benchmark_checkpoint()
    else:unittest.main()
