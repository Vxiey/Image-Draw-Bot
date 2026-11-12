"""Pixel admission and corrections use actual delivery cost on existing sources."""
from contextlib import ExitStack,closing
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import weakref

from PIL import Image

import Colors
from AdaptiveBrushEngine import assign_adaptive_brushes
from DrawBot import make_plan
from ExecutionCostModel import build_cost_model
from PixelAccuratePlanner import build_pixel_map
from PixelStrokeEngine import build_pixel_stroke_plan
import PixelAccuracyEngine as accuracy
from test_v148_rendering_batch38_prepared_paths import close_plan
from test_v148_rendering_batch39_pixel_runs import public_options
from test_v148_rendering_batch40_region_work import PALETTE
from test_v148_rendering_batch41_mask_runs import controls

ROOT=Path(__file__).resolve().parent


class PixelDeliveryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.previous_palette=list(Colors.allColors);Colors.reset_palette()

    def tearDown(self):
        Colors.allColors[:]=self.previous_palette
        from PixelData import closest_color
        closest_color.cache_clear()

    def mapped_sequence(self,**changes):
        options=public_options(brush_px=1,pixel_accurate=True,profile_key='gartic-phone',
            browser_brush_plan=controls(),adaptive_color_verification=True,
            exact_color_available=True,color_selectors=tuple({'kind':'custom','rgb':rgb} for rgb in PALETTE),
            _execution_cost_calibration_override={'samples':5,'ratio':1.,'operation_runtime':{
                'palette_change':{'average_seconds':.2,'count':5},
                'brush_change':{'average_seconds':.3,'count':5},
                'verification':{'average_seconds':.4,'count':5}}})
        options.update(changes)
        with Image.open(ROOT/'golden-regression/small-detail-preservation.png') as source, \
                source.resize((96,64)) as reduced:
            mapped=build_pixel_map(reduced,PALETTE,gpu_mode='CPU')
        plan=build_pixel_stroke_plan(mapped,len(PALETTE),options=options)
        sequence=assign_adaptive_brushes(plan['execution_sequence'],profile_key='gartic-phone',
            default_brush_px=1,browser_brush_plan=controls())['execution_sequence']
        sequence=[dict(row,occurrence=i) for i,row in enumerate(sequence)]
        return mapped,sequence,options

    def test_actual_thirty_second_plans_keep_complete_cheap_source_quality(self):
        for filename in ('small-detail-preservation.png','red-bananas-texture.png'):
            with self.subTest(source=filename),ExitStack() as stack:
                original=stack.enter_context(closing(Image.open(ROOT/'golden-regression'/filename)))
                source=stack.enter_context(closing(original.resize((96,64))))
                before=source.tobytes()
                options=public_options(brush_px=1,delay=0,speed='Fast',
                    adaptive_color_verification=False,strict_color_verification=False)
                unlimited=make_plan(source,source.size,options)
                stack.callback(close_plan,unlimited,source)
                timed=make_plan(source,source.size,dict(options,time_budget_mode='30 sec',
                    unlimited_time=False,max_seconds=30,manual_max_seconds=30))
                stack.callback(close_plan,timed,source)
                meta=timed['options']['pixel_accuracy_meta'];budget=meta['progressive_time_budget']
                self.assertEqual(meta['error_pixels'],0)
                self.assertEqual(meta['pixel_accuracy_percent'],100.)
                self.assertEqual(unlimited['options']['pixel_accuracy_meta']['pixel_accuracy_percent'],100.)
                self.assertEqual(budget['paths_omitted'],0)
                self.assertEqual(budget['source'],'progressive-execution-cost-budget')
                self.assertLess(timed['estimate'],budget['render_budget_seconds'])
                self.assertEqual(source.tobytes(),before)

    def test_tight_budget_prices_custom_colors_brushes_verification_and_original_order(self):
        mapped,source,options=self.mapped_sequence()
        # Exercise the verified native brush states on the actual source paths.
        # Geometry, occurrence order and component/phase membership stay intact.
        source=[dict(row,brush_px=(1,2,4)[i%3]) for i,row in enumerate(source)]
        model=build_cost_model(options,(mapped.width,mapped.height),(mapped.width,mapped.height))
        full=model.sequence_cost(source,initial_brush=1,include_color_verification=True)
        self.assertGreater(full.custom_color_seconds,0)
        self.assertGreater(full.brush_seconds,0)
        self.assertGreater(full.verification_seconds,0)
        options['deadline_render_budget_seconds']=model.fixed_overhead().total_seconds+full.total_seconds*.55
        model=build_cost_model(options,(mapped.width,mapped.height),(mapped.width,mapped.height))
        before=copy.deepcopy(source)
        result=accuracy.progressive_time_budget(source,active=True,seconds=30,cost_model=model)
        selected=result['execution_sequence']
        self.assertTrue(selected)
        self.assertLess(len(selected),len(source))
        self.assertEqual(source,before)
        self.assertEqual([row['occurrence'] for row in selected],sorted(row['occurrence'] for row in selected))
        self.assertTrue(any(row['protected'] for row in selected))
        complete=model.sequence_cost(selected,initial_brush=1,include_color_verification=True)
        self.assertAlmostEqual(complete.total_seconds,result['selected_sequence_seconds'],places=12)
        self.assertLessEqual(model.risk_adjusted_seconds(complete.total_seconds),result['base_sequence_budget_seconds']+1e-9)
        self.assertGreater(result['correction_reserve_seconds'],0)

    def test_no_path_is_forced_when_fixed_work_already_exceeds_timer(self):
        mapped,sequence,options=self.mapped_sequence(deadline_render_budget_seconds=1.)
        model=build_cost_model(options,(mapped.width,mapped.height),(mapped.width,mapped.height))
        result=accuracy.progressive_time_budget(sequence,active=True,seconds=5,cost_model=model)
        self.assertEqual(result['execution_sequence'],[])
        self.assertTrue(result['fixed_overhead_exceeds_budget'])
        self.assertEqual(result['selected_sequence_seconds'],0.)

    def test_retained_paths_keep_inherited_brush_width_when_carriers_are_omitted(self):
        mapped,source,options=self.mapped_sequence()
        intended={};brush=1
        for index,row in enumerate(source):
            row.pop('brush_px',None)
            if index%5==0:
                brush=(1,2,4)[(index//5)%3]
                row['brush_px']=brush
            intended[row['occurrence']]=brush
        before=copy.deepcopy(source)
        model=build_cost_model(options,(mapped.width,mapped.height),(mapped.width,mapped.height))
        total=model.sequence_cost(source,initial_brush=1,include_color_verification=True).total_seconds
        options['deadline_render_budget_seconds']=model.fixed_overhead().total_seconds+total*.4
        model=build_cost_model(options,(mapped.width,mapped.height),(mapped.width,mapped.height))
        selected=accuracy.progressive_time_budget(source,active=True,seconds=30,
                                                  cost_model=model)['execution_sequence']
        self.assertTrue(selected)
        self.assertLess(len(selected),len(source))
        self.assertTrue(any('brush_px' not in before[row['occurrence']] for row in selected))
        self.assertEqual([row['brush_px'] for row in selected],
                         [intended[row['occurrence']] for row in selected])
        self.assertEqual(source,before)

    def test_corrections_fit_remaining_real_cost_and_still_improve_existing_target(self):
        mapped,sequence,options=self.mapped_sequence(adaptive_color_verification=False,
            exact_color_available=False,_execution_cost_calibration_override={})
        source=[dict(row,brush_px=1) for row in sequence[::5]]
        model=build_cost_model(options,(mapped.width,mapped.height),(mapped.width,mapped.height))
        base=model.sequence_cost(source,initial_brush=1,include_color_verification=True).total_seconds
        limit=base+1.0
        unlimited=accuracy.refine_with_corrections(mapped,source,PALETTE,brush_px=1,
            correction_brush_px=1,max_passes=1,gpu_mode='CPU')
        result=accuracy.refine_with_corrections(mapped,source,PALETTE,brush_px=1,
            correction_brush_px=1,max_passes=1,gpu_mode='CPU',cost_model=model,max_execution_seconds=limit)
        final=model.sequence_cost(result['execution_sequence'],initial_brush=1,include_color_verification=True)
        self.assertLessEqual(model.risk_adjusted_seconds(final.total_seconds),limit+1e-9)
        self.assertGreater(result['metadata']['final_accuracy_percent'],result['metadata']['initial_accuracy_percent'])
        self.assertGreater(result['metadata']['correction_paths_added'],0)
        self.assertLess(result['metadata']['correction_paths_added'],unlimited['metadata']['correction_paths_added'])
        self.assertEqual(result['execution_sequence'][:len(source)],source)
        self.assertTrue(result['metadata']['correction_delivery_budget']['attempts'])

    def test_late_stop_in_cost_preparation_does_not_publish_a_partial_sequence(self):
        mapped,sequence,options=self.mapped_sequence(deadline_render_budget_seconds=5.)
        model=build_cost_model(options,(mapped.width,mapped.height),(mapped.width,mapped.height))
        prepare=model.prepare_path_cost;count=0;prepared=[];failure=None
        def complete(*args,**kwargs):
            nonlocal count
            result=prepare(*args,**kwargs);count+=1
            prepared.append(weakref.ref(result))
            return result
        with patch.object(model,'prepare_path_cost',new=complete):
            try:
                accuracy.progressive_time_budget(sequence,active=True,seconds=5,cost_model=model,
                    cancelled=lambda:count>=3)
            except InterruptedError as error:
                failure=error
        self.assertIsNotNone(failure)
        self.assertEqual(count,3)
        self.assertTrue(all(ref() is None for ref in prepared))


if __name__=='__main__':unittest.main()
