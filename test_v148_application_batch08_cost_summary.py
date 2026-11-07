"""Final ETA and planner summaries use the executor's retained controls (RP28)."""
from contextlib import closing
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from DrawTimeEstimate import _sequence_operation_estimate, estimate_from_plan
from ExecutionCostModel import build_cost_model
from test_v148_rendering_batch08_costs import brush_plan, phase_sequence
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch07_transparency import standard_options


class RetainedCostSummaryTests(unittest.TestCase):
    def test_control_only_summary_skips_geometry_and_observes_stop(self):
        model=build_cost_model(dict(brush_px=5,profile_key='gartic-phone',
            browser_brush_plan=brush_plan(),_execution_cost_calibration_override={}),
            (40,80),(40,80))
        sequence=phase_sequence()
        with patch.object(model,'path_cost',side_effect=AssertionError('geometry recomputed')):
            cost=model.sequence_cost(sequence,initial_brush=5,include_geometry=False)
            self.assertEqual((cost.palette_switches,cost.brush_switches),(5,1))
            checks=iter([False,False,True])
            with self.assertRaises(InterruptedError):
                model.sequence_cost(sequence,include_geometry=False,cancelled=lambda:next(checks))

    def test_learned_fill_cache_cannot_enter_a_cold_visible_or_raw_summary(self):
        from DrawBot import make_plan
        from test_v148_rendering_batch08_fill import fixture, fill_options
        snapshots=[]
        with closing(fixture()) as image, patch('DrawTimeCalibration.load_profile',return_value=None):
            for calibration in ({},{'samples':5,'ratio':2.,'operation_runtime':{}}):
                plan=make_plan(image,image.size,fill_options(_execution_cost_calibration_override=calibration))
                try:
                    regions=plan['options']['fill_regions']
                    self.assertEqual(len(regions),1)
                    before=[dict(row) for row in regions]
                    raw,meta=_sequence_operation_estimate(plan)
                    self.assertEqual(regions,before)
                    snapshots.append((raw,meta['fill_seconds'],
                        plan['options']['operation_timing_meta']['fill_seconds'],
                        regions[0]['fill_core_cost_seconds'],plan['execution_sequence']))
                finally:
                    close_plan(plan,image)
        self.assertEqual(snapshots[0][4],snapshots[1][4])
        self.assertGreater(snapshots[1][3],snapshots[0][3])
        for index in range(3):
            self.assertAlmostEqual(snapshots[0][index],snapshots[1][index],places=5)

    def test_canonical_eta_keeps_custom_operation_whole_and_learning_out_of_raw(self):
        options = dict(profile_key='gartic-phone', brush_px=5, delay=0,
            exact_color_available=True, color_selectors=[{'kind':'custom'}, {'kind':'palette'}],
            adaptive_color_verification=True, browser_brush_plan=brush_plan(),
            _execution_cost_calibration_override={'samples':20,'ratio':4.,
                'operation_runtime':{'color_change':{'average_seconds':7.}}})
        sequence = phase_sequence()
        sequence.insert(1, {'color_index':31,'phase':'unexecuted','path':()})
        with closing(Image.new('RGB',(40,80))) as image:
            plan = dict(options=options, image=image, fitted=image.size, execution_sequence=sequence)
            raw, meta = _sequence_operation_estimate(plan)
            cold = build_cost_model(dict(options, _execution_cost_calibration_override={}),image.size,image.size)
            cursor = None
            geometry = 0.
            for entry in sequence:
                if entry['path']:
                    geometry += cold.path_cost(entry['path'],cursor=cursor,
                                               brush_px=entry.get('brush_px')).total_seconds
                    cursor=entry['path'][-1]
            # The actual fake-native executor test observes four red selections
            # (start, phase, brush, return) and one green palette selection.
            self.assertAlmostEqual(raw, geometry + 5*cold.delivery.palette_click_delay
                + 4*.78 + cold.switch_cost('brush_change') + 2*cold.switch_cost('verification'))
            self.assertEqual(meta['color_changes'],5)
            self.assertEqual(meta['operation_counts']['color_change'],4)
            self.assertEqual(meta['operation_counts']['palette_change'],1)
            self.assertEqual(meta['operation_counts']['verification'],2)
            self.assertAlmostEqual(meta['operation_model_average_seconds']['color_change'],
                                   cold.delivery.palette_click_delay+.78,places=6)
            with patch('DrawTimeEstimate._apply_measured_correction',
                       return_value=(raw,'test',0,1.,None,{})) as correction:
                estimate_from_plan(plan)
            correction.assert_called_once()
            self.assertAlmostEqual(correction.call_args.args[1],raw)

    def test_fill_prelude_selects_its_colour_separately_from_retained_strokes(self):
        options = dict(brush_px=1, exact_color_available=True,
            color_selectors=[{'kind':'custom'}], fill_tool_available=True,
            fill_regions=[{'color_index':0}], paint_current_color=False)
        with closing(Image.new('RGB',(10,10))) as image, patch(
                'RegionFillEngine.estimate_fill_execution_seconds',return_value={
                    'fill_regions':1,'fill_color_batches':1,'total_seconds':2.,
                    'fill_contour_and_click_seconds':1.5,'fill_tool_switch_seconds':.5}):
            plan=dict(options=options,image=image,fitted=image.size,
                execution_sequence=[{'color_index':0,'path':((3,3),)}])
            seconds, meta=_sequence_operation_estimate(plan)
            self.assertEqual(meta['color_changes'],2)
            self.assertEqual(meta['custom_color_changes'],2)
            self.assertGreater(meta['fill_selection_seconds'],.78)
            self.assertAlmostEqual(seconds,meta['sequence_seconds']+2.+meta['fill_selection_seconds'],places=4)
            options['paint_current_color']=True
            _, current=_sequence_operation_estimate(plan)
            self.assertEqual(current['color_changes'],0)
            self.assertEqual(current['fill_selection_seconds'],0.)

    def test_actual_hybrid_summary_and_visible_eta_keep_same_retained_controls(self):
        from DrawBot import make_plan
        options = standard_options(extra_fast=True,extra_fast_v2=True,
            time_budget_mode='Custom',manual_max_seconds=30,max_seconds=30,
            unlimited_time=False,deadline_safety_reserve='Off',profile_name='Microsoft Paint',
            profile_key='microsoft-paint',paint_profile=True,exact_color_available=True,
            adaptive_color_verification=True,skip_white=True,gpu_mode='CPU',
            custom_color_workflow='Exact custom + palette fallback',exact_color_limit='32',
            color_fidelity='Faithful',_execution_cost_calibration_override={})
        with closing(Image.new('RGB',(48,32),'white')) as image, \
                patch('DrawTimeCalibration.load_profile',return_value=None):
            draw=ImageDraw.Draw(image)
            draw.rectangle((3,3,28,25),fill=(73,117,181))
            draw.rectangle((31,5,44,23),fill=(181,73,117))
            plan=make_plan(image,(48,32),options)
            try:
                retained=plan['options']['adaptive_hybrid_meta']['schedule']['selected_operation_cost']
                summary=plan['options']['operation_timing_meta']
                visible=plan['draw_time_estimate']['sequence_operation_model']['breakdown']
                for key in ('palette_seconds','custom_color_seconds','verification_seconds'):
                    self.assertAlmostEqual(summary[key],retained[key],places=3)
                    self.assertAlmostEqual(visible[key],retained[key],places=5)
            finally:
                close_plan(plan,image)


if __name__=='__main__':
    unittest.main()
