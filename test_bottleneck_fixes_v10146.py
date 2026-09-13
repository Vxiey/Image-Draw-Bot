import unittest

from AdaptiveBrushEngine import assign_adaptive_brushes, _collapse_transient_upshifts
from DrawTimeEstimate import estimate_from_plan
from ExtraFast import select_fast_regions
from RegionFillEngine import _decision_fill_cost, estimate_fill_execution_seconds
from StatefulFillSimulation import filter_stateful_fill_regions
from Version import APP_VERSION, FILE_VERSION


def closed_region(x0=20, y0=20, x1=60, y1=60, color=1):
    spans=[(y,x0,x1) for y in range(y0,y1+1)]
    contour=[(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)]
    return {
        'color_index':color,
        'row_spans':spans,
        'contour':contour,
        'seed_pixel':((x0+x1)//2,(y0+y1)//2),
        'guard_pixels':[(x0-2,(y0+y1)//2),(x1+2,(y0+y1)//2)],
        'area_pixels':(x1-x0+1)*(y1-y0+1),
        'safety_score':.98,
        'bbox_density':1.0,
        'perimeter_pixels':2*((x1-x0+1)+(y1-y0+1)),
    }


def brush_plan(guard=28):
    return {
        'profile_key':'gartic-phone',
        'nominal_sizes':[2,4,8,16,28],
        'control_positions':[[10,10],[20,10],[30,10],[40,10],[50,10]],
        'target_position':[20,10],
        'confidence':.95,
        'effective_px':4,
        'safe_guard_px':guard,
    }


def entry(phase='foundation', *, width=100, height=100, area=10000, importance=.1, brush=None):
    out={
        'color_index':1,
        'path':((10,10),(90,10)),
        'phase':phase,
        'protected':False,
        'importance':importance,
        'component_width':width,
        'component_height':height,
        'component_area':area,
    }
    if brush is not None:
        out['brush_px']=brush
    return out


class BottleneckFixesV10146Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual((APP_VERSION,FILE_VERSION),('1.0.146-rc1','1.0.146'))

    def test_fill_simulation_uses_bounded_roi_not_full_canvas_per_region(self):
        regions=[closed_region(40,40,80,80),closed_region(160,140,205,185,color=2)]
        # This test validates the allocation strategy only. A 2 px square brush
        # intentionally extends one diagonal corner pixel beyond this synthetic
        # contour and is correctly rejected by the existing safety rule.
        accepted,meta=filter_stateful_fill_regions(regions,(1200,900),brush_px=1)
        self.assertEqual(len(accepted),2)
        self.assertEqual(meta['full_canvas_state_copies_per_region'],0)
        self.assertLess(meta['peak_roi_percent_of_canvas'],2.0)
        self.assertEqual(meta['allocation_strategy'],'one global state + bounded per-region ROI masks')

    def test_large_safe_foundation_can_use_upper_verified_brush_levels(self):
        sequence=[entry(width=180,height=150,area=27000) for _ in range(6)]
        result=assign_adaptive_brushes(sequence,profile_key='gartic-phone',default_brush_px=4,
                                       browser_brush_plan=brush_plan(28))
        used=result['metadata']['used_brush_sizes']
        self.assertTrue(any(size in used for size in (16,28)),used)
        self.assertTrue(all(size<=28 for size in used))

    def test_transient_large_brush_upshift_is_collapsed(self):
        rows=[entry('structure',brush=4),entry('foundation',brush=16),entry('structure',brush=4)]
        changed=_collapse_transient_upshifts(rows)
        self.assertEqual(changed,1)
        self.assertEqual([row['brush_px'] for row in rows],[4,4,4])
        self.assertIn('switch-hysteresis',rows[1]['brush_reason'])

    def test_region_fill_extra_fast_gate_uses_core_cost_before_batch_check(self):
        self.assertEqual(_decision_fill_cost(1.0,.72,{'extra_fast':True}),.72)
        self.assertEqual(_decision_fill_cost(1.0,.72,{'extra_fast':False}),1.0)

    def test_region_fill_estimate_removes_per_region_switch_then_batches_once(self):
        regions=[]
        for offset in (0,70):
            r=closed_region(10+offset,10,55+offset,55,color=3)
            r.update(fill_cost_seconds=.52,fill_core_cost_seconds=.42,
                     fill_batchable_overhead_seconds=.10)
            regions.append(r)
        meta=estimate_fill_execution_seconds(
            regions,(200,100),(200,100),
            {'fill_tool_available':True,'fill_tool_actions':[('fill',(1,1))],
             'fill_restore_actions':[('brush',(2,2))],'ui_control_delay':.10})
        self.assertTrue(meta['batch_aware'])
        self.assertEqual(meta['fill_color_batches'],1)
        self.assertAlmostEqual(meta['fill_contour_and_click_seconds'],.84,places=2)
        # RegionFill uses the same resolved StrokeDelivery timing as execution.
        # Generic delivery is 0.20 s per UI action: Fill + restore = 0.40 s once
        # for the entire same-colour batch, not once per region.
        self.assertAlmostEqual(meta['fill_tool_switch_seconds'],.40,places=2)
        self.assertAlmostEqual(meta['total_seconds'],1.24,places=2)
        self.assertAlmostEqual(meta['per_region_tool_switch_seconds_removed'],.20,places=2)

    def test_extra_fast_charges_shared_fill_controls_once_per_color_batch(self):
        regions=[]
        for offset in (0,70):
            r=closed_region(10+offset,10,55+offset,55,color=3)
            r.update(stroke_cost_seconds=1.25,fill_cost_seconds=.72,
                     fill_core_cost_seconds=.42,fill_batchable_overhead_seconds=.30)
            regions.append(r)
        accepted,meta=select_fast_regions(
            regions,(200,100),(200,100),
            {'fill_tool_available':True,'fill_tool_actions':[('fill',(1,1))],
             'fill_restore_actions':[('brush',(2,2))],'ui_control_delay':.10})
        self.assertEqual(len(accepted),2)
        self.assertEqual(meta['fill_color_batches'],1)
        self.assertFalse(meta['per_region_tool_switch_double_charge'])
        self.assertAlmostEqual(meta['fill_estimated_seconds'],1.04,places=2)

    def test_estimator_prefers_final_execution_sequence(self):
        plan={
            'estimate':999.0,
            'count':2,
            'image':type('ImageStub',(),{'size':(100,100)})(),
            'fitted':(100,100),
            'plan_area':(100,100),'preview_area':(100,100),'target_area':(100,100),
            'execution_sequence':[
                {'color_index':0,'brush_px':4,'path':((10,10),(70,10))},
                {'color_index':1,'brush_px':8,'path':((70,20),(20,20))},
            ],
            'options':{
                'profile_key':'v146-sequence-estimator-test','speed':'Fast','precision':'Normal',
                'delay':.003,'brush_px':4,'fill_tool_available':False,
                '_hybrid_cost_calibration_override':{'samples':0},
            },
            'path_stats':{},
        }
        meta=estimate_from_plan(plan)
        self.assertTrue(meta['sequence_model_used'])
        self.assertNotEqual(meta['preview_seconds'],999.0)
        self.assertEqual(meta['sequence_operation_model']['stroke_sequence_paths'],2)
        self.assertEqual(meta['sequence_operation_model']['color_changes'],2)
        self.assertEqual(meta['sequence_operation_model']['brush_changes'],1)
        self.assertLess(meta['preview_seconds'],999.0)


if __name__=='__main__':
    unittest.main()
