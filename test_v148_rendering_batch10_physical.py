"""Native brush footprints, reachable source centers and physical quality reports."""
from contextlib import ExitStack,closing
from fractions import Fraction
import math
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw

import AdaptiveRegionHybrid as regional
from DrawBot import make_plan,execute_plan
from NativeBrushProjection import NativeBrushProjection
from test_drawbot import Mouse,NoWait
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch10_single_brush import options


def physical_options(origin,area,**changes):
    value=options(corners=(origin,(origin[0]+area[0],origin[1]+area[1])))
    controls=dict(value['browser_brush_plan'])
    controls['control_positions']=[(-1000+i*10,-1000) for i in range(4)]
    controls['target_position']=controls['control_positions'][0]
    value['browser_brush_plan']=controls
    value.update(changes)
    return value


def desired_native_labels(pixel_map,fitted,area):
    """Independent inverse pixel-cell mapping; no production projection helpers."""
    width,height=area
    offset_x=(width-fitted[0])/2;offset_y=(height-fitted[1])/2
    # Fractions retain the supplied geometry exactly, including a coordinate
    # arbitrarily close to a cell boundary. This scalar oracle neither builds
    # nor reuses the production axis coefficients/vectorization.
    x_indices=[math.floor((Fraction(x)+Fraction(1,2)-Fraction(offset_x))*pixel_map.width/Fraction(fitted[0]))
               for x in range(width)]
    y_indices=[math.floor((Fraction(y)+Fraction(1,2)-Fraction(offset_y))*pixel_map.height/Fraction(fitted[1]))
               for y in range(height)]
    target=np.full((height,width),-1,dtype=np.int16)
    for y,sy in enumerate(y_indices):
        if not 0<=sy<pixel_map.height:continue
        for x,sx in enumerate(x_indices):
            if 0<=sx<pixel_map.width and pixel_map.drawable_mask[sy,sx]:
                target[y,x]=pixel_map.palette_index[sy,sx]
    return target


def replay_executor(plan,origin,area):
    """Paint only recorded native actions, with widths changed by actual controls."""
    with ExitStack() as stack:
        stack.enter_context(patch('BrowserBrushSize.verify_brush_selection',return_value=True))
        stack.enter_context(patch('DrawBot.log_event'))
        stack.enter_context(patch('DrawBot.save_runtime_safety_report',side_effect=lambda state:state.as_dict()))
        for name in ('RealSpeedBudget.record_runtime_sample','DrawTimeEstimate.record_completed_draw',
                     'CompletedDrawingAnalysis.record_completed_drawing','AutoTunerFeedback.record_completed_feedback',
                     'CorrectionHistory.record_correction_history'):
            stack.enter_context(patch(name,return_value={}))
        palette=[(-900+5*i,-1000) for i in range(len(plan['colors']))]
        mouse=Mouse()
        execute_plan(plan,(*origin,*area),palette,mouse,NoWait(),threading.Event(),lambda *args:None,clock=lambda:0)
        image=stack.enter_context(closing(Image.new('I',area,-1)));draw=ImageDraw.Draw(image)
        brush=int(plan['options']['brush_px']);color=None;position=(0,0);held=False;selected=[]
        evidence=plan['options'].get('browser_brush_plan') or {}
        controls=dict(zip(evidence.get('control_positions') or (),evidence.get('verified_sizes') or ()))
        colors={point:index for index,point in enumerate(palette)}
        def paint(a,b):
            assert color is not None
            assert a[0]==b[0] or a[1]==b[1]
            before,after=(brush-1)//2,brush//2
            draw.rectangle((min(a[0],b[0])-origin[0]-before,min(a[1],b[1])-origin[1]-before,
                            max(a[0],b[0])-origin[0]+after,max(a[1],b[1])-origin[1]+after),fill=color)
        for action in mouse.actions:
            if action[0]=='move':
                next_position=action[1:]
                if held:paint(position,next_position)
                position=next_position
            elif action[0]=='press':held=True;paint(position,position)
            elif action[0]=='release':held=False
            elif action[0]=='click':
                if position in controls:brush=controls[position];selected.append(brush)
                elif position in colors:color=colors[position]
                elif origin[0]<=position[0]<origin[0]+area[0] and origin[1]<=position[1]<origin[1]+area[1]:
                    paint(position,position)
        assert not held and not mouse.held
        return np.asarray(image).copy(),selected


class PhysicalBrushProjectionTests(unittest.TestCase):
    def assert_report_matches_native_actions(self,plan,reference,actual,area):
        target=desired_native_labels(reference,plan['fitted'],area)
        drawable=target>=0;painted=actual>=0
        quality=plan['options']['adaptive_hybrid_meta']['quality']
        self.assertEqual(quality['coordinate_space'],'physical canvas pixels before CanvasGuard')
        self.assertEqual(quality['missing_pixels'],int(np.count_nonzero(drawable&~painted)))
        self.assertEqual(quality['spill_pixels'],int(np.count_nonzero(~drawable&painted)))
        self.assertEqual(quality['wrong_color_pixels'],int(np.count_nonzero(drawable&painted&(actual!=target))))
        self.assertAlmostEqual(quality['coverage_percent'],round(100*np.count_nonzero(drawable&painted)/np.count_nonzero(drawable),4))
        self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'],0)
        diagnostic=np.full((*target.shape,3),255,dtype=np.uint8)
        diagnostic[drawable&(actual==target)]=(225,225,225)
        diagnostic[drawable&~painted]=(255,80,80)
        diagnostic[drawable&painted&(actual!=target)]=(255,170,45)
        diagnostic[~drawable&painted]=(175,60,220)
        np.testing.assert_array_equal(np.asarray(plan['options']['_pixel_coverage_preview']),diagnostic)
        np.testing.assert_array_equal(np.asarray(plan['ui_previews']['coverage']),diagnostic)
        self.assertEqual(plan['ui_previews']['coverage'].size,area)
        # Pillow independently samples the recorded native raster's fractional
        # fitted crop. The main view and full-canvas Coverage have different,
        # explicit extents instead of squashing a letterbox into the source.
        rgb=np.full((*actual.shape,3),255,dtype=np.uint8)
        rgb[painted]=np.asarray(plan['colors'],dtype=np.uint8)[actual[painted]]
        left=(area[0]-plan['fitted'][0])/2;top=(area[1]-plan['fitted'][1])/2
        with closing(Image.fromarray(rgb,'RGB')) as native:
            with closing(native.transform(plan['preview'].size,Image.Transform.EXTENT,
                    (left,top,left+plan['fitted'][0],top+plan['fitted'][1]),Image.Resampling.NEAREST)) as expected:
                np.testing.assert_array_equal(np.asarray(plan['preview']),np.asarray(expected))
        return target

    def public_plan(self,stack,source,area,origin,**changes):
        references=[];real=regional.build_adaptive_execution
        def capture(pixel_map,*args,**kwargs):
            references.append(kwargs.get('reference_pixel_map') or pixel_map)
            return real(pixel_map,*args,**kwargs)
        with patch.object(regional,'build_adaptive_execution',side_effect=capture):
            plan=make_plan(source,area,physical_options(origin,area,**changes))
        stack.callback(close_plan,plan,source)
        self.assertTrue(plan['options']['adaptive_hybrid_meta']['enabled'])
        self.assertEqual(len(references),1)
        return plan,references[0]

    def test_public_two_times_plan_packs_actual_sixteen_pixel_brush_without_gaps(self):
        with ExitStack() as stack:
            stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
            source=stack.enter_context(closing(Image.new('RGB',(200,150),'white')))
            ImageDraw.Draw(source).rectangle((48,40,143,103),fill=(0,80,205))
            area=(400,300);origin=(100,100)
            plan,reference=self.public_plan(stack,source,area,origin)
            self.assertEqual(plan['image'].size,(200,150))
            self.assertEqual(plan['options']['adaptive_hybrid_meta']['methods'],{'region-brush-pack':1})
            actual,selected=replay_executor(plan,origin,area)
            target=self.assert_report_matches_native_actions(plan,reference,actual,area)
            np.testing.assert_array_equal(actual,target)
            self.assertIn(16,selected)
            expected=np.zeros((300,400),bool);expected[80:208,96:288]=True
            np.testing.assert_array_equal(actual>=0,expected)
            preview=np.asarray(plan['preview'])
            np.testing.assert_array_equal(np.any(preview!=255,axis=2),expected)
            widths={entry['brush_px'] for entry in plan['execution_sequence']}
            self.assertIn(16,widths)
            self.assertTrue(widths<={2,4,8,16})

    def test_noninteger_asymmetric_scales_and_signed_origin_match_real_delivery(self):
        with ExitStack() as stack:
            stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
            source=stack.enter_context(closing(Image.new('RGB',(197,151),'white')))
            ImageDraw.Draw(source).rectangle((30,30,165,120),fill=(0,80,205))
            area=(431,321);origin=(-210,-100)
            plan,reference=self.public_plan(stack,source,area,origin)
            sx,sy=(fit/size for fit,size in zip(plan['fitted'],plan['image'].size))
            self.assertNotEqual(sx,sy);self.assertNotEqual(sx,int(sx))
            actual,_=replay_executor(plan,origin,area)
            self.assert_report_matches_native_actions(plan,reference,actual,area)
            self.assertTrue(all(int(value)==value for entry in plan['execution_sequence'] for point in entry['path'] for value in point))

    def test_exact_inverse_cell_boundary_and_adjacent_floats_preserve_the_target_row(self):
        settings={'_planning_canvas_size':(216,217),'planner_max_pixels':75000}
        for fit,expected in ((math.nextafter(216.,-math.inf),(124,125,125)),
                             (216.,(124,125,125)),
                             (math.nextafter(216.,math.inf),(124,124,125))):
            with self.subTest(fitted=fit):
                projection=NativeBrushProjection((200,200),(216.,fit),settings)
                self.assertEqual(tuple(projection.y_source[134:137]),expected)
        with ExitStack() as stack:
            stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
            source=stack.enter_context(closing(Image.new('RGB',(200,200),'white')))
            ImageDraw.Draw(source).rectangle((30,125,169,174),fill=(0,80,205))
            area=(216,217);origin=(100,100)
            plan,reference=self.public_plan(stack,source,area,origin,
                browser_brush_plan=None,brush_px=1,canvas_guard_brush_px=1)
            actual,_=replay_executor(plan,origin,area)
            target=self.assert_report_matches_native_actions(plan,reference,actual,area)
            self.assertEqual(np.count_nonzero(target>=0),8208)
            self.assertEqual(plan['options']['adaptive_hybrid_meta']['quality']['missing_pixels'],605)

    def test_signed_letterbox_spill_is_scored_outside_the_fitted_image(self):
        for height,left_edge in ((200,150),(300,125)):
            with self.subTest(canvas_height=height),ExitStack() as stack:
                stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
                source=stack.enter_context(closing(Image.new('RGB',(100,200),'white')))
                ImageDraw.Draw(source).rectangle((0,40,63,159),fill=(0,80,205))
                area=(400,height);origin=(-300,-150)
                plan,reference=self.public_plan(stack,source,area,origin,
                    browser_brush_plan=None,brush_px=4,canvas_guard_brush_px=4)
                actual,_=replay_executor(plan,origin,area)
                target=self.assert_report_matches_native_actions(plan,reference,actual,area)
                self.assertGreater(np.count_nonzero((actual>=0)&(target<0)),0)
                self.assertTrue(np.any(actual[:,:left_edge]>=0))
                self.assertEqual(plan['options']['adaptive_hybrid_meta']['coverage_coordinate_space'],'full physical canvas')
                if height==200:
                    self.assertEqual(plan['options']['adaptive_hybrid_meta']['quality']['spill_pixels'],561)

    def test_oversized_native_roi_rejects_packing_but_scores_fallback_in_bounded_tiles(self):
        with ExitStack() as stack:
            stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
            source=stack.enter_context(closing(Image.new('RGB',(200,150),'white')))
            ImageDraw.Draw(source).rectangle((8,8,191,141),fill=(0,80,205))
            area=(400,300);origin=(100,100)
            plan,reference=self.public_plan(stack,source,area,origin)
            metadata=plan['options']['adaptive_hybrid_meta']
            self.assertNotIn('region-brush-pack',metadata['methods'])
            self.assertIn('exceeds planning pixel allowance',metadata['region_choices'][0]['reason'])
            self.assertFalse(metadata['region_choices'][0]['exact'])
            actual,_=replay_executor(plan,origin,area)
            self.assert_report_matches_native_actions(plan,reference,actual,area)
            projection=NativeBrushProjection(plan['image'].size,plan['fitted'],plan['options'])
            self.assertTrue(all((right-left)*(bottom-top)<=plan['options']['planner_max_pixels']
                for left,top,right,bottom in projection.tiles()))

    def test_half_pixel_letterbox_uses_contiguous_native_centers_at_unit_scale(self):
        settings={'_planning_canvas_size':(11,10),'corners':((-6,-5),(5,5)),'planner_max_pixels':100}
        projection=NativeBrushProjection.for_scaled_plan((10,10),(10,10),settings)
        self.assertIsNotNone(projection)
        self.assertEqual(projection.native_path(tuple((x,5) for x in range(10))),
                         tuple((x,5) for x in range(1,11)))
        self.assertIsNotNone(NativeBrushProjection.for_scaled_plan((10,10),(10,10),
            dict(settings,_planning_canvas_size=(12,10),corners=((-6,-5),(6,5)))))
        self.assertIsNone(NativeBrushProjection.for_scaled_plan((10,10),(10,10),
            dict(settings,_planning_canvas_size=(10,10),corners=((-6,-5),(4,5)))))

    def test_actual_unit_scale_signed_half_ties_deliver_contiguously_with_truthful_quality(self):
        with ExitStack() as stack:
            stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
            source=stack.enter_context(closing(Image.new('RGB',(130,130),'white')))
            ImageDraw.Draw(source).rectangle((50,60,80,69),fill=(0,80,205))
            area=(130,131);origin=(100,-65)
            plan,reference=self.public_plan(stack,source,area,origin,
                browser_brush_plan=None,brush_px=1,canvas_guard_brush_px=1)
            self.assertEqual(plan['image'].size,(130,130))
            self.assertEqual(plan['fitted'],(130.,130.))
            actual,_=replay_executor(plan,origin,area)
            target=self.assert_report_matches_native_actions(plan,reference,actual,area)
            self.assertTrue(np.all(target[65,50:81]>=0))
            expected=np.zeros((area[1],area[0]),dtype=np.bool_)
            expected[61:71,50:81]=True
            np.testing.assert_array_equal(actual>=0,expected)
            self.assertGreater(plan['options']['adaptive_hybrid_meta']['quality']['missing_pixels'],0)

    def test_reachable_roi_centers_match_literal_native_footprints_around_a_hole(self):
        component=np.full((11,15),-1,dtype=np.int32)
        component[1:10,1:14]=7;component[4:7,6:9]=-1
        original=component.copy();component.flags.writeable=False
        settings={'_planning_canvas_size':(38,31),'corners':((-20,-15),(18,16)),
                  'planner_max_pixels':3000}
        projection=NativeBrushProjection((15,11),(35.7,26.2),settings)
        roi,reason=projection.component_roi(component,7,(1,1,13,9))
        self.assertFalse(reason)
        for brush in (1,2,3,4,7):
            safe=roi.source_centers(regional._eroded_centers(roi.target,brush))
            expected=np.zeros(safe.shape,bool);before,after=(brush-1)//2,brush//2
            for y in range(len(roi.y_centers)):
                for x in range(len(roi.x_centers)):
                    nx,ny=int(roi.x_centers[x]),int(roi.y_centers[y])
                    cells=[(xx,yy) for yy in range(ny-before,ny+after+1)
                           for xx in range(nx-before,nx+after+1)]
                    expected[y,x]=all(0<=xx<roi.target.shape[1] and 0<=yy<roi.target.shape[0]
                                         and roi.target[yy,xx] for xx,yy in cells)
            np.testing.assert_array_equal(safe,expected)
        np.testing.assert_array_equal(component,original)

    def test_cancellation_during_native_simulation_closes_the_owned_preview(self):
        with closing(Image.new('RGB',(20,20),(0,80,205))) as source:
            reference=regional.pixel_map_from_groups(source,[[(0,y,19,y) for y in range(20)]],[(0,80,205)],gpu_mode='CPU')
            projection=NativeBrushProjection((20,20),(200,200),{'planner_max_pixels':1024})
            created=[];stopping=[];real_new=Image.new;real_tiles=projection.tiles
            def new(*args,**kwargs):
                result=real_new(*args,**kwargs);created.append(result);return result
            def tiles(**kwargs):
                for number,tile in enumerate(real_tiles(**kwargs)):
                    if number==1:stopping.append(True)
                    yield tile
            with patch.object(projection,'tiles',side_effect=tiles),patch.object(regional.Image,'new',side_effect=new):
                with self.assertRaises(InterruptedError):
                    regional.simulate_native_plan(reference,[{'color_index':0,'brush_px':4,'path':((0,10),(19,10))}],
                        projection,cancelled=lambda:bool(stopping))
            self.assertTrue(created)
            for image in created:
                with self.assertRaises(ValueError):image.getpixel((0,0))


if __name__=='__main__':unittest.main()
