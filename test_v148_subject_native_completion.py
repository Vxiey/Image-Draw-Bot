"""Subject-only masks constrain real signed, half-pixel native brush footprints."""
from contextlib import ExitStack, closing
import copy
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import SubjectFocus
from DrawBot import make_plan
from NativeBrushProjection import NativeBrushProjection
from test_pixel_stroke_engine_v1087 import pixelmap_from_index
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch09_subject import settings, BLUE
from test_v148_rendering_batch10_physical import desired_native_labels, replay_executor


class NativeSubjectFootprintTests(unittest.TestCase):
    def public_plan(self, stack, origin, area, **changes):
        source=stack.enter_context(closing(Image.new('RGB',(64,64),BLUE)))
        captured=[];original=SubjectFocus.focused_stroke_plan
        def observe(*args,**kwargs):
            result=original(*args,**kwargs)
            captured.append(result[0])
            return result
        stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
        options=settings(browser_brush_plan=None,brush_px=4,
            corners=(origin,(origin[0]+area[0],origin[1]+area[1])),**changes)
        with patch.object(SubjectFocus,'focused_stroke_plan',side_effect=observe):
            plan=make_plan(source,area,options)
        stack.callback(close_plan,plan,source)
        self.assertEqual(len(captured),1)
        return plan,captured[0]

    def assert_native_result(self,plan,pixel_map,origin,area,*,full_canvas=True):
        actual,_=replay_executor(plan,origin,area)
        target=desired_native_labels(pixel_map,plan['fitted'],area)
        drawable=target>=0;covered=actual>=0
        missing=int(np.count_nonzero(drawable&~covered))
        spill=int(np.count_nonzero(~drawable&covered))
        wrong=int(np.count_nonzero(drawable&covered&(actual!=target)))
        metadata=plan['options']['pixel_accuracy_meta']
        self.assertEqual(spill,0,'Actual native brush must never paint outside the subject.')
        self.assertEqual((metadata['missing_pixels'],metadata['spill_pixels'],metadata['wrong_color_pixels']),
                         (missing,spill,wrong))
        self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'],0)
        expected=np.full((*target.shape,3),(20,25,32),dtype=np.uint8)
        expected[drawable&covered]=(45,180,120)
        expected[drawable&~covered]=(240,175,55)
        expected[~drawable&covered]=(220,70,75)
        np.testing.assert_array_equal(np.asarray(plan['options']['_pixel_coverage_preview']),expected)
        np.testing.assert_array_equal(np.asarray(plan['ui_previews']['coverage']),expected)
        if full_canvas:self.assertEqual(metadata['coverage_coordinate_space'],'full physical canvas')
        # PreviewSafety samples the native ink into the fitted crop independently
        # of the full-canvas diagnostic extent.
        rgb=np.full((*target.shape,3),255,dtype=np.uint8)
        rgb[covered]=np.asarray(plan['colors'],dtype=np.uint8)[actual[covered]]
        left=(area[0]-plan['fitted'][0])/2;top=(area[1]-plan['fitted'][1])/2
        with closing(Image.fromarray(rgb,'RGB')) as raster, closing(raster.transform(
                plan['preview'].size,Image.Transform.EXTENT,
                (left,top,left+plan['fitted'][0],top+plan['fitted'][1]),Image.Resampling.NEAREST)) as preview:
            np.testing.assert_array_equal(np.asarray(plan['preview']),np.asarray(preview))
        return missing

    def test_actual_half_pixel_letterbox_has_no_spill_at_signed_native_origins(self):
        for origin in ((100,100),(-200,-100),(-40,-32)):
            with self.subTest(origin=origin),ExitStack() as stack:
                plan,pixel_map=self.public_plan(stack,origin,(81,64))
                missing=self.assert_native_result(plan,pixel_map,origin,(81,64))
                self.assertEqual(missing,0)
                self.assertEqual(plan['options']['pixel_accuracy_meta']['coverage_percent'],100.)
                self.assertEqual({entry['brush_px'] for entry in plan['execution_sequence']},{4})
                self.assertEqual(plan['options']['pixel_accuracy_meta']['native_subject_roi'],(24,16,32,32))

    def test_tall_half_pixel_letterbox_and_narrow_unreachable_subject_report_actual_coverage(self):
        for area,region,expected_missing in (((64,81),(.25,.25,.75,.75),0),
                ((81,64),(15/64,8/64,16/64,24/64),16)):
            with self.subTest(area=area,region=region),ExitStack() as stack:
                origin=(-90,-90)
                plan,pixel_map=self.public_plan(stack,origin,area,subject_region=region)
                self.assertEqual(self.assert_native_result(plan,pixel_map,origin,area),expected_missing)
                if expected_missing:self.assertEqual(plan['execution_sequence'],[])

    def test_coincident_canvas_uses_the_same_guarded_square_preview(self):
        with ExitStack() as stack:
            origin=(-30,-30);area=(64,64)
            plan,pixel_map=self.public_plan(stack,origin,area)
            self.assertEqual(self.assert_native_result(plan,pixel_map,origin,area,full_canvas=False),0)

    def test_native_erosion_and_connectors_preserve_holes_with_readonly_source_mask(self):
        indices=np.full((24,28),-1,dtype=np.int16)
        indices[3:22,2:26]=1;indices[8:13,10:15]=-1
        pixel_map=pixelmap_from_index(indices)
        original=pixel_map.drawable_mask.copy();pixel_map.drawable_mask.flags.writeable=False
        projection=NativeBrushProjection((28,24),(28,24),dict(
            _planning_canvas_size=(29,25),planner_max_pixels=29*25,corners=((-15,-13),(14,12))))
        target=desired_native_labels(pixel_map,(28,24),(29,25))>=0
        for brush in (1,2,3,4):
            sequence=[{'color_index':1,'brush_px':brush,'path':((0,y),(27,y)),
                       'phase':'subject/cleanup','serial':y} for y in range(24)]
            before=copy.deepcopy(sequence)
            actual,metadata=SubjectFocus.clip_subject_brush_sequence(sequence,pixel_map.drawable_mask,
                default_brush_px=brush,projection=projection)
            with closing(Image.new('1',(29,25))) as ink:
                draw=ImageDraw.Draw(ink);a,b=(brush-1)//2,brush//2
                for entry in actual:
                    native=projection.native_path(entry['path'])
                    for start,end in zip(native,native[1:]) if len(native)>1 else ((native[0],native[0]),):
                        self.assertTrue(start[0]==end[0] or start[1]==end[1])
                        draw.rectangle((min(start[0],end[0])-a,min(start[1],end[1])-a,
                                        max(start[0],end[0])+b,max(start[1],end[1])+b),fill=1)
                self.assertFalse(np.any(np.asarray(ink)&~target))
            self.assertEqual(sequence,before)
            self.assertEqual(metadata['maximum_cached_footprint_masks'],2)
        np.testing.assert_array_equal(pixel_map.drawable_mask,original)

    def test_stop_during_diagnostic_publication_closes_every_owned_image(self):
        pixel_map=pixelmap_from_index([[1]*12 for _ in range(10)])
        projection=NativeBrushProjection((12,10),(12,10),dict(
            _planning_canvas_size=(13,10),planner_max_pixels=130,corners=((0,0),(13,10))))
        sequence=[{'color_index':1,'path':((0,y),(11,y)),'brush_px':1} for y in range(10)]
        sequence,_=SubjectFocus.clip_subject_brush_sequence(sequence,pixel_map.drawable_mask,projection=projection)
        original=SubjectFocus._subject_diagnostic_canvas;images=[]
        def stop_second(*args):
            images.append(args[0])
            if len(images)>2:raise InterruptedError('Stop during error view')
            result=original(*args);images.append(result)
            return result
        with patch.object(SubjectFocus,'_subject_diagnostic_canvas',side_effect=stop_second),self.assertRaises(InterruptedError):
            SubjectFocus.evaluate_native_subject_plan(pixel_map,sequence,((255,255,255),BLUE),projection)
        self.assertEqual(len(images),3)
        for image in images:
            with self.assertRaises(ValueError):image.getpixel((0,0))

    def test_scaled_diagonal_reuses_only_its_proven_native_connectors(self):
        indices=np.full((12,12),-1,dtype=np.int16)
        # Literal source raster for the line (2,2)->(9,6), independent of the
        # production clipper. Its long native chord cuts across two empty cells.
        for x,y in ((2,2),(3,3),(4,3),(5,4),(6,4),(7,5),(8,5),(9,6)):
            indices[y,x]=1
        pixel_map=pixelmap_from_index(indices)
        projection=NativeBrushProjection((12,12),(19,19),dict(
            _planning_canvas_size=(19,19),planner_max_pixels=361))
        source=[{'color_index':1,'path':((2,2),(9,6)),'brush_px':1,'serial':8}]
        sequence,meta=SubjectFocus.clip_subject_brush_sequence(source,pixel_map.drawable_mask,projection=projection)
        self.assertGreater(meta['unsafe_native_connectors'],0)
        self.assertEqual(source[0]['path'],((2,2),(9,6)))
        target=desired_native_labels(pixel_map,(19,19),(19,19))>=0
        with closing(Image.new('1',(19,19))) as ink:
            draw=ImageDraw.Draw(ink)
            for entry in sequence:
                native=projection.native_path(entry['path'])
                if len(native)==1:draw.point(native[0],fill=1)
                else:draw.line(native,fill=1)
                self.assertEqual(entry['serial'],8)
            self.assertFalse(np.any(np.asarray(ink)&~target))

    def test_empty_entries_cannot_select_a_brush_and_omitted_paths_preserve_later_widths(self):
        mask=np.zeros((24,24),bool);mask[4:20,4:20]=True
        cases=(
            ([{'color_index':1,'brush_px':5,'path':((10,10),)},
              {'color_index':1,'brush_px':1,'path':()},
              {'color_index':1,'path':((4,10),)}], [5]),
            ([{'color_index':1,'brush_px':3,'path':((0,0),)},
              {'color_index':1,'path':((10,10),)}], [3]),
        )
        for source,widths in cases:
            with self.subTest(source=source):
                before=copy.deepcopy(source)
                sequence,_=SubjectFocus.clip_subject_brush_sequence(source,mask,default_brush_px=5)
                self.assertEqual([entry['brush_px'] for entry in sequence if entry.get('path')],widths)
                self.assertEqual(source,before)

    def test_native_preview_keeps_guard_skips_and_exact_square_widths(self):
        from PreviewSafety import build_preview_safety_plan
        sequence=[{'color_index':1,'brush_px':4,'path':((0,0),(3,0))},
                  {'color_index':1,'brush_px':4,'path':((4,4),(7,4))}]
        options=dict(_planning_canvas_size=(20,20),planner_max_pixels=400,
                     brush_px=4,edge_behavior='Hard Clip',profile_name='Gartic Phone')
        safe=build_preview_safety_plan((12,12),(19,19),[[],[]],None,options,
                                      execution_sequence=sequence)
        self.assertEqual(len(safe.sequence),1)
        with closing(SubjectFocus.render_native_subject_preview(safe,(19,19),(19,19),
                ((255,255,255),BLUE))) as preview, closing(Image.new('RGB',(20,20),'white')) as native:
            draw=ImageDraw.Draw(native)
            for entry in safe.sequence:
                (x0,y0),(x1,y1)=entry['path']
                draw.rectangle((min(x0,x1)-1,min(y0,y1)-1,max(x0,x1)+2,max(y0,y1)+2),fill=BLUE)
            with closing(native.transform((19,19),Image.Transform.EXTENT,(.5,.5,19.5,19.5),
                    Image.Resampling.NEAREST)) as expected:
                np.testing.assert_array_equal(np.asarray(preview),np.asarray(expected))


if __name__=='__main__':
    unittest.main()
