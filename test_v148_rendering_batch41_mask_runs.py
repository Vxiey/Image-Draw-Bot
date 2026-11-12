"""Brush-packing center runs from existing source geometry, without pixel loops."""
from contextlib import closing
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import AdaptiveRegionHybrid as hybrid
from PixelAccuratePlanner import build_pixel_map
from test_v148_rendering_batch39_pixel_runs import public_options
from test_v148_rendering_batch40_region_work import PALETTE

ROOT=Path(__file__).resolve().parent


def scalar_runs(mask,row_stride=1,row_offset=0,orientation='horizontal',**_unused):
    view=mask.T if orientation=='vertical' else mask
    stride=max(1,int(row_stride));offset=int(row_offset)%stride
    result=[]
    for y in range(offset,view.shape[0],stride):
        start=None
        for x in range(view.shape[1]+1):
            present=x<view.shape[1] and bool(view[y,x])
            if present and start is None:start=x
            elif not present and start is not None:
                points=((y,start),(y,x-1)) if orientation=='vertical' else ((start,y),(x-1,y))
                result.append(points[:1] if start==x-1 else points)
                start=None
    return result


def controls():
    return {'profile_key':'gartic-phone','target_position':(10,10),'target_index':0,
        'effective_px':1,'confidence':.99,'nominal_sizes':[1,2,4,8],
        'verified_sizes':[1,2,4,8],'control_positions':[(10,10),(20,10),(30,10),(40,10)],
        'safe_guard_px':8}


class CenterRunTests(unittest.TestCase):
    def mask(self):
        with Image.open(ROOT/'golden-regression/small-detail-preservation.png') as source, \
                source.convert('L') as gray:
            return np.asarray(gray)<120

    def test_truth_values_seams_offsets_views_and_orientation_match_scalar(self):
        # Keep this seam/stride matrix small; the separate wide-mask case covers
        # the production block bound with the same existing raster source.
        original=self.mask()[::5,::5]
        for mask in (original,original[:,::-1],original.T,original[:1],original[:,:1],
                     original[:0],original[:,:0],original.astype(np.int16)*7):
            before=mask.tobytes();mask.flags.writeable=False
            for orientation in ('horizontal','vertical'):
                for stride,offset in ((1,0),(2,1),(3,-1),(5,12)):
                    expected=scalar_runs(mask,stride,offset,orientation)
                    for block in (3,31,16_384):
                        with self.subTest(shape=mask.shape,orientation=orientation,stride=stride,block=block), \
                                patch.object(hybrid,'_MASK_RUN_BLOCK',block):
                            self.assertEqual(hybrid._runs_from_mask(mask,stride,offset,orientation),expected)
            self.assertEqual(mask.tobytes(),before)

    def test_wide_existing_mask_limits_transition_workspace(self):
        with Image.open(ROOT/'golden-regression/small-detail-preservation.png') as source, \
                source.resize((33_001,4)) as wide, wide.convert('L') as gray:
            mask=np.asarray(gray)<120
        empty=np.empty;shapes=[]
        def allocate(shape,*args,**kwargs):
            value=empty(shape,*args,**kwargs)
            shapes.append(value.shape)
            return value
        with patch.object(np,'empty',new=allocate):
            actual=hybrid._runs_from_mask(mask)
        self.assertEqual(actual,scalar_runs(mask))
        self.assertTrue(shapes)
        self.assertTrue(all(np.prod(shape)<=16_386 for shape in shapes),shapes)

    def test_stop_after_a_completed_transition_block_has_no_partial_result(self):
        mask=self.mask();calls=0;nonzero=np.flatnonzero
        def search(*args,**kwargs):
            nonlocal calls
            result=nonzero(*args,**kwargs);calls+=1
            return result
        with patch.object(hybrid,'_MASK_RUN_BLOCK',16),patch.object(np,'flatnonzero',new=search):
            with self.assertRaises(InterruptedError):
                hybrid._runs_from_mask(mask,cancelled=lambda:calls>=2)
        self.assertEqual(calls,2)

    def test_existing_mask_removes_python_pixel_reads(self):
        class CountedMask(np.ndarray):
            reads=0
            def __getitem__(self,key):
                CountedMask.reads+=1
                return super().__getitem__(key)
        mask=self.mask().view(CountedMask)
        expected=scalar_runs(mask)
        old_reads=CountedMask.reads;CountedMask.reads=0
        self.assertEqual(hybrid._runs_from_mask(mask),expected)
        self.assertGreaterEqual(old_reads,mask.size)
        self.assertLess(CountedMask.reads,old_reads//100)

    def test_real_brush_candidate_search_and_complete_plan_match_scalar_runs(self):
        with Image.open(ROOT/'assets/image-draw-bot-icon.png') as original,original.resize((64,64)) as source:
            mapped=build_pixel_map(source,PALETTE,gpu_mode='CPU')
        options=public_options(brush_px=1,profile_key='gartic-phone',browser_brush_plan=controls())
        result=hybrid.build_adaptive_execution(mapped,PALETTE,options,(64,64))
        with patch.object(hybrid,'_runs_from_mask',new=scalar_runs):
            expected=hybrid.build_adaptive_execution(mapped,PALETTE,options,(64,64))
        try:
            for key in ('execution_groups','execution_sequence','metrics'):
                self.assertEqual(result[key],expected[key])
            self.assertEqual({k:v for k,v in result['metadata'].items() if k!='timings'},
                             {k:v for k,v in expected['metadata'].items() if k!='timings'})
            for key in ('coverage_preview','error_preview'):
                self.assertEqual(result[key].tobytes(),expected[key].tobytes())
            self.assertTrue(any((row.get('brush_packing') or {}).get('covered_pixels',0)>0
                for row in result['metadata']['candidate_diagnostics']))
        finally:
            for plan in (result,expected):
                plan['coverage_preview'].close();plan['error_preview'].close()


if __name__=='__main__':unittest.main()
