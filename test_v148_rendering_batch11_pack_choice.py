"""Finished exact brush packs compete on total cost, without replacing cheaper greediness."""
from contextlib import ExitStack,closing
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw

import AdaptiveRegionHybrid as regional
from DrawBot import make_plan
from ExecutionCostModel import build_cost_model
from NativeBrushProjection import NativeBrushProjection
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch10_candidates import component,scalar_candidate_oracle
from test_v148_rendering_batch10_physical import physical_options,replay_executor


BLUE=(0,80,205)
FIXTURES={
    'cheaper_complete_pack':((200,150),(400,300),(48,40,143,103)),
    'cheaper_original_pack':((128,96),(128,96),(8,8,118,86)),
}


def force_policy(helper,maximum_gain):
    """Counterfactual geometry oracle, not the performance baseline.

    The outer selector evaluates both slots, but each gets the same original
    local policy. This needs no historical Git objects in a shallow CI checkout.
    """
    def call(*args,**kwargs):
        kwargs['maximize_gain']=maximum_gain
        return helper(*args,**kwargs)
    return call


def packing_metadata(plan):
    return plan['options']['adaptive_hybrid_meta']['candidate_diagnostics'][0]['brush_packing']


class CompletePackChoiceTests(unittest.TestCase):
    def public_variants(self,stack,fixture):
        size,area,box=FIXTURES[fixture];origin=(100,100)
        stack.enter_context(patch('DrawTimeCalibration.load_profile',return_value=None))
        source=stack.enter_context(closing(Image.new('RGB',size,'white')))
        ImageDraw.Draw(source).rectangle(box,fill=BLUE)
        helper=regional._candidate_paths_for_brush;variants={};rasters={}
        for name,policy in (('original',False),('maximum',True),('selected',None)):
            with ExitStack() as local:
                if policy is not None:
                    local.enter_context(patch.object(regional,'_candidate_paths_for_brush',force_policy(helper,policy)))
                plan=make_plan(source,area,physical_options(origin,area))
            stack.callback(close_plan,plan,source)
            variants[name]=plan
            actual,selected=replay_executor(plan,origin,area);rasters[name]=actual
            # Independent axis-aligned physical paint expectation. Both
            # fixtures have exact integral source-cell scaling, so this does
            # not use the planner's projection, morphology or simulation.
            color=plan['colors'].index(BLUE)
            target=np.full((area[1],area[0]),-1,dtype=np.int32)
            sx,sy=area[0]//size[0],area[1]//size[1]
            target[box[1]*sy:(box[3]+1)*sy,box[0]*sx:(box[2]+1)*sx]=color
            np.testing.assert_array_equal(actual,target)
            self.assertTrue(set(selected)<={2,4,8,16})
            self.assertTrue({entry['brush_px'] for entry in plan['execution_sequence']}<={2,4,8,16})
            runtime=plan['options']['runtime_path_counts']
            self.assertEqual(runtime['guard_skipped'],0)
            self.assertEqual(runtime['sent'],len(plan['execution_sequence']))
            quality=plan['options']['adaptive_hybrid_meta']['quality']
            self.assertEqual((quality['coverage_percent'],quality['missing_pixels'],quality['spill_pixels']),
                             (100.,0,0))
            model=build_cost_model(plan['options'],plan['image'].size,plan['fitted'])
            cost=model.sequence_cost(plan['execution_sequence'],initial_color=color,initial_brush=2).total_seconds
            choice=plan['options']['adaptive_hybrid_meta']['region_choices'][0]
            self.assertEqual(choice['method'],'region-brush-pack')
            self.assertAlmostEqual(choice['estimated_seconds'],cost,places=6)
        for name in ('maximum','selected'):
            np.testing.assert_array_equal(rasters[name],rasters['original'])
            self.assertEqual(variants[name]['preview'].tobytes(),variants['original']['preview'].tobytes())
            self.assertEqual(variants[name]['ui_previews']['coverage'].tobytes(),
                             variants['original']['ui_previews']['coverage'].tobytes())
        return variants

    def test_actual_scaled_plan_selects_cheaper_finished_pack_and_preserves_native_pixels(self):
        with ExitStack() as stack:
            plans=self.public_variants(stack,'cheaper_complete_pack')
            original,selected=plans['original'],plans['selected']
            self.assertEqual(len(original['execution_sequence']),47)
            self.assertEqual(len(selected['execution_sequence']),12)
            self.assertEqual(selected['execution_sequence'],plans['maximum']['execution_sequence'])
            packing=packing_metadata(selected)
            self.assertEqual(packing['packing_policy'],'maximum-gain')
            costs=packing['policy_candidates']
            self.assertLess(costs['maximum-gain']['best_seconds'],costs['gain-per-cost']['best_seconds'])
            self.assertAlmostEqual(costs['gain-per-cost']['best_seconds'],10.576773842074575)
            self.assertAlmostEqual(costs['maximum-gain']['best_seconds'],8.546752857069972)
            self.assertLessEqual(sum(row['evaluated'] for row in costs.values()),12)
            self.assertEqual(packing['used_brush_sizes'],[16])

    def test_actual_counterexample_retains_the_original_cheaper_complete_geometry(self):
        with ExitStack() as stack:
            plans=self.public_variants(stack,'cheaper_original_pack')
            selected=plans['selected'];packing=packing_metadata(selected)
            self.assertEqual(packing['packing_policy'],'gain-per-cost')
            self.assertEqual(len(selected['execution_sequence']),32)
            self.assertEqual(len(plans['maximum']['execution_sequence']),54)
            self.assertEqual(selected['execution_sequence'],plans['original']['execution_sequence'])
            self.assertEqual(selected['execution_groups'],plans['original']['execution_groups'])
            costs=packing['policy_candidates']
            self.assertLess(costs['gain-per-cost']['best_seconds'],costs['maximum-gain']['best_seconds'])
            self.assertAlmostEqual(costs['gain-per-cost']['best_seconds'],4.851547335954672)
            self.assertAlmostEqual(costs['maximum-gain']['best_seconds'],7.333242709276697)

    def test_exact_complete_cost_tie_retains_original_even_when_alternative_has_fewer_paths(self):
        size=(96,64);area=(192,128)
        options=physical_options((100,100),area,_planning_canvas_size=area,planner_max_pixels=30000)
        model=build_cost_model(options,size,area);real_cost=model.sequence_cost
        complete_calls=[]
        def tied_complete_cost(sequence,**kwargs):
            result=real_cost(sequence,**kwargs)
            # The real local candidate estimator starts at its own brush.
            # Only finished multi-size packs start at the default2px brush.
            if sequence and kwargs.get('initial_brush')==2 and sequence[0]['brush_px']!=2:
                complete_calls.append(len(sequence))
                return replace(result,total_seconds=100.)
            return result
        labels=np.ones((64,96),np.int32);labels.flags.writeable=False
        projection=NativeBrushProjection(size,area,options)
        helper=regional._candidate_paths_for_brush
        with patch.object(model,'sequence_cost',side_effect=tied_complete_cost):
            with patch.object(regional,'_candidate_paths_for_brush',force_policy(helper,False)):
                original,_=regional._brush_pack_candidate(component(labels.shape),labels,options,model,projection=projection)
            selected,_=regional._brush_pack_candidate(component(labels.shape),labels,options,model,projection=projection)
        self.assertGreater(len(complete_calls),0)
        self.assertEqual(selected['packing_policy'],'gain-per-cost')
        self.assertEqual(selected['sequence'],original['sequence'])
        self.assertEqual(selected['cost'],100.)
        self.assertEqual(selected['packing_policy_candidates']['maximum-gain']['best_seconds'],100.)
        self.assertGreater(len(selected['sequence']),min(complete_calls))

    def test_stop_in_second_policy_does_not_publish_the_first_completed_pack(self):
        size=(48,32);labels=np.ones((32,48),np.int32);saved=labels.copy();stop=[];seen=[]
        options=physical_options((100,100),size);model=build_cost_model(options,size,size)
        helper=regional._candidate_paths_for_brush
        def stop_in_alternative(*args,**kwargs):
            seen.append(bool(kwargs.get('maximize_gain')))
            if kwargs.get('maximize_gain'):stop.append(True)
            return helper(*args,**kwargs)
        with patch.object(regional,'_candidate_paths_for_brush',side_effect=stop_in_alternative), \
                self.assertRaises(InterruptedError):
            regional._brush_pack_candidate(component(labels.shape),labels,options,model,
                                            cancelled=lambda:bool(stop))
        self.assertIn(False,seen);self.assertEqual(seen.count(True),1)
        np.testing.assert_array_equal(labels,saved)

    def test_both_local_policies_match_literal_hole_and_residual_oracle(self):
        target=np.ones((19,25),bool);target[5:9,7:12]=False
        residual=target.copy();residual[::3,::2]=False
        model=build_cost_model(physical_options((100,100),(25,19)),(25,19),(25,19))
        for maximum_gain in (False,True):
            for final in (False,True):
                for brush in (2,3,4,7):
                    with self.subTest(maximum_gain=maximum_gain,final=final,brush=brush):
                        kwargs=dict(model=model,comp=component(target.shape),phase='foundation',
                            final_size=final,origin=(17,11),maximize_gain=maximum_gain)
                        expected=scalar_candidate_oracle(target,residual,brush,**kwargs)
                        actual=regional._candidate_paths_for_brush(target,residual,brush,**kwargs)
                        self.assertEqual(actual[0],expected[0])
                        np.testing.assert_array_equal(actual[1],expected[1])
                        self.assertAlmostEqual(actual[2],expected[2],places=12)
                        self.assertFalse(np.any(actual[1]&~target))

    def test_historical_retention_benchmark_rejects_new_policy_before_loading_or_timing(self):
        import benchmark_v148_rendering_batch10 as historical
        with patch.object(historical,'previous_function',side_effect=AssertionError('must not load baseline')), \
                patch.object(historical,'measured_pair',side_effect=AssertionError('must not start timing')), \
                self.assertRaisesRegex(RuntimeError,'requires the frozen batch10 caller'):
            historical.measure(repeats=1)


if __name__=='__main__':unittest.main()
