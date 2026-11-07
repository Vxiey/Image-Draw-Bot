"""Brush alternatives keep bounded live rasters and preserve exact selection."""
from contextlib import closing
from itertools import groupby
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image,ImageDraw

import AdaptiveRegionHybrid as regional
from DrawBot import make_plan
from ExecutionCostModel import build_cost_model
from test_rc6_region_brush_packing import options as brush_options
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch07_transparency import standard_options
from test_v148_rendering_batch09_subject import BLUE,sequence_raster


def component(shape):
    h,w=shape
    return SimpleNamespace(component_id=1,color_index=0,area=h*w,bbox=(0,0,w-1,h-1),
        width=w,height=h,importance_mean=.1,importance_max=.1,edge_mean=.1,
        contour_mean=.1,protected_pixels=0,protected_ratio=0.)


def scalar_candidate_oracle(target,residual,brush_px,*,model,comp,phase,final_size,
                            origin=(0,0),cancelled=lambda:False,maximize_gain=False):
    """Literal footprint tests and Pillow axis sweeps, independent of NumPy morphology."""
    h,w=target.shape;brush=max(1,int(brush_px));before,after=(brush-1)//2,brush//2
    centers=np.zeros((h,w),bool)
    for y in range(before,h-after):
        if cancelled():raise InterruptedError()
        for x in range(before,w-after):
            cells=[(yy,xx) for yy in range(y-before,y+after+1) for xx in range(x-before,x+after+1)]
            centers[y,x]=all(target[yy,xx] for yy,xx in cells) and any(residual[yy,xx] for yy,xx in cells)
    rows=[]
    strides=(1,) if final_size else tuple(dict.fromkeys((brush,max(1,brush//2))))
    for stride in strides:
        for orientation in ('horizontal','vertical'):
            view=centers if orientation=='horizontal' else centers.T
            for offset in range(stride):
                local=[]
                for axis in range(offset,len(view),stride):
                    indices=[i for i,inside in enumerate(view[axis]) if inside]
                    for _,run in groupby(enumerate(indices),key=lambda pair:pair[1]-pair[0]):
                        points=[i for _,i in run]
                        a,b=points[0],points[-1]
                        path=((a,axis),) if a==b else ((a,axis),(b,axis))
                        if orientation=='vertical':path=tuple((y,x) for x,y in path)
                        local.append(path)
                if not local:continue
                with closing(Image.new('1',(w,h))) as image:
                    draw=ImageDraw.Draw(image)
                    for path in local:
                        x0,y0=path[0];x1,y1=path[-1]
                        draw.rectangle((min(x0,x1)-before,min(y0,y1)-before,
                                        max(x0,x1)+after,max(y0,y1)+after),fill=1)
                    painted=np.asarray(image).copy()
                gain=int(np.count_nonzero(painted&residual))
                if not gain or np.any(painted&~target):continue
                paths=[tuple((x+origin[0],y+origin[1]) for x,y in path) for path in local]
                sequence=[{'path':path,'color_index':comp.color_index,'brush_px':brush,'phase':phase} for path in paths]
                cost=max(.000001,float(model.sequence_cost(sequence,initial_color=comp.color_index,initial_brush=brush).total_seconds))
                rows.append((gain,cost,len(paths),stride,orientation,offset,paths,painted))
    if not rows:return [],np.zeros_like(target),0.
    maximum_gain=max(row[0] for row in rows)
    minimum_gain=maximum_gain if maximize_gain else max(1,int(maximum_gain*.90))
    chosen=min((row for row in rows if row[0]>=minimum_gain),
               key=lambda row:(row[1]/row[0],row[1],row[2],-row[0],row[3],row[4],row[5]))
    return chosen[6],chosen[7],chosen[1]


class CandidateWorkspaceTests(unittest.TestCase):
    def test_selected_geometry_mask_and_cost_match_literal_footprint_oracle(self):
        rng=np.random.default_rng(902)
        target=np.ones((19,25),bool);target[7:11,9:14]=False;target[0,:3]=False
        residual=target&(rng.random(target.shape)<.55)
        for final in (False,True):
            for brush in (1,2,3,4,7,30):
                with self.subTest(brush=brush,final=final):
                    a=target.copy();b=residual.copy();a.flags.writeable=False;b.flags.writeable=False
                    model=build_cost_model(dict(brush_options(),_execution_cost_calibration_override={}),
                                           (25,19),(37,30))
                    kwargs=dict(model=model,comp=component(target.shape),phase='foundation',final_size=final,origin=(17,11))
                    expected=scalar_candidate_oracle(a,b,brush,**kwargs)
                    actual=regional._candidate_paths_for_brush(a,b,brush,**kwargs)
                    self.assertEqual(actual[0],expected[0])
                    np.testing.assert_array_equal(actual[1],expected[1])
                    self.assertAlmostEqual(actual[2],expected[2],places=12)
                    self.assertFalse(np.any(actual[1]&~a))
                    np.testing.assert_array_equal(a,target);np.testing.assert_array_equal(b,residual)

    def test_alternative_count_does_not_multiply_live_candidate_planes(self):
        target=np.ones((96,128),bool);residual=target.copy();refs=[];peaks=[]
        original_zeros=np.zeros_like
        def tracked(*args,**kwargs):
            result=original_zeros(*args,**kwargs)
            if result.shape==target.shape and result.dtype==np.bool_:
                refs.append(weakref.ref(result));peaks.append(sum(ref() is not None for ref in refs))
            return result
        model=build_cost_model(dict(brush_options(),_execution_cost_calibration_override={}),
                               (128,96),(128,96))
        with patch.object(regional.np,'zeros_like',side_effect=tracked):
            paths,painted,_=regional._candidate_paths_for_brush(target,residual,16,model=model,
                comp=component(target.shape),phase='foundation',final_size=False)
        self.assertTrue(paths);self.assertGreater(len(refs),40)
        self.assertLessEqual(max(peaks),2)
        self.assertEqual(sum(ref() is not None for ref in refs),1)
        np.testing.assert_array_equal(painted,target)

    def test_stop_during_winner_reconstruction_never_returns_partial_output(self):
        target=np.ones((24,32),bool);original=target.copy();calls=[];stop=[]
        real=regional._runs_from_mask
        def record(*args,**kwargs):
            calls.append(1)
            result=real(*args,**kwargs)
            # Width4 searches 2*(4+2) layouts. The next call reconstructs the
            # selected layout; Stop here must be observed before publication.
            if len(calls)==13:stop.append(True)
            return result
        model=build_cost_model(dict(brush_options(),_execution_cost_calibration_override={}),
                               (32,24),(32,24))
        with patch.object(regional,'_runs_from_mask',side_effect=record),self.assertRaises(InterruptedError):
            regional._candidate_paths_for_brush(target,target,4,model=model,comp=component(target.shape),
                phase='foundation',final_size=False,cancelled=lambda:bool(stop))
        self.assertEqual(len(calls),13);np.testing.assert_array_equal(target,original)

    def test_actual_multibrush_planner_matches_scalar_alternative_oracle(self):
        with closing(Image.new('RGB',(64,48),'white')) as image, \
                patch('DrawTimeCalibration.load_profile',return_value=None):
            ImageDraw.Draw(image).rectangle((8,8,54,38),fill=BLUE)
            controls={'profile_key':'gartic-phone','target_position':(10,10),'confidence':.99,
                'nominal_sizes':[2,4,8],'verified_sizes':[2,4,8],
                'control_positions':[(10,10),(20,10),(30,10)],'safe_guard_px':8}
            options=standard_options(extra_fast=True,extra_fast_v2=True,brush_px=2,skip_white=True,
                profile_key='gartic-phone',profile_name='Gartic Phone',browser_brush_plan=controls,delay=.02,
                _execution_cost_calibration_override={})
            with patch.object(regional,'_candidate_paths_for_brush',wraps=regional._candidate_paths_for_brush) as calls:
                actual=make_plan(image,image.size,options)
            try:
                self.assertGreater(calls.call_count,0)
                with patch.object(regional,'_candidate_paths_for_brush',side_effect=scalar_candidate_oracle):
                    expected=make_plan(image,image.size,options)
                try:
                    self.assertEqual(actual['execution_sequence'],expected['execution_sequence'])
                    self.assertEqual(actual['execution_groups'],expected['execution_groups'])
                    self.assertEqual(actual['options']['adaptive_hybrid_meta']['quality'],expected['options']['adaptive_hybrid_meta']['quality'])
                    self.assertEqual(actual['options']['adaptive_hybrid_meta']['region_choices'],expected['options']['adaptive_hybrid_meta']['region_choices'])
                    self.assertEqual(actual['options']['adaptive_hybrid_meta']['candidate_diagnostics'],expected['options']['adaptive_hybrid_meta']['candidate_diagnostics'])
                    self.assertEqual(actual['preview'].tobytes(),expected['preview'].tobytes())
                    self.assertIn('region-brush-pack',actual['options']['adaptive_hybrid_meta']['methods'])
                    target=np.zeros((48,64),bool);target[8:39,8:55]=True
                    np.testing.assert_array_equal(sequence_raster(actual['execution_sequence'],image.size),target)
                finally:close_plan(expected,image)
            finally:close_plan(actual,image)


if __name__=='__main__':unittest.main()
