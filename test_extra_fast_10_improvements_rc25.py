import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

import AdaptiveRegionHybrid as ar
from AdaptiveRegionHybrid import RegionChoice
from ExecutionCostModel import build_cost_model
from TimeBudgetEngine import automatic_reserve
from Version import APP_VERSION


def opts(limit=60.0):
    return {'profile_key':'gartic','brush_px':2,'speed':'Balanced','delay':0.0,
            'time_budget_active':True,'time_budget_mode':'Custom','max_seconds':limit,
            'manual_max_seconds':limit,'deadline_safety_reserve':'Auto','paint_current_color':False,
            'adaptive_color_verification':False,'fill_tool_available':False,
            'browser_brush_plan':{'target_position':(10,10),'confidence':.99,
                'nominal_sizes':[2,4,8,16,28],'verified_sizes':[2,4,8,16,28],
                'control_positions':[(1,1),(2,1),(3,1),(4,1),(5,1)],'safe_guard_px':4}}


def choice(cid,color,phase='structure',cost=.2,gain=.1,brush=2,protected=0,importance=.3):
    return RegionChoice(cid,color,'test',phase,100,importance,.2,protected,cost,gain,
                        gain/max(.001,cost*1000),1,brush,True,'test')


def entry(cid,color,x,brush=2,fake_cost=None,phase='structure'):
    row={'component_id':cid,'color_index':color,'brush_px':brush,'path':((x,10),(x+5,10)),'phase':phase}
    if fake_cost is not None:row['fake_cost']=float(fake_cost)
    return [row]


class FakeBreakdown:
    def __init__(self,total):
        self.total_seconds=float(total);self.palette_switches=0;self.brush_switches=0
        self.tool_switches=0;self.palette_seconds=0.0;self.brush_seconds=0.0
    def as_dict(self):return {'total_seconds':self.total_seconds,'palette_switches':0,'brush_switches':0}


class FakeModel:
    scale_x=1.0;scale_y=1.0;multiplier=1.0;uncertainty_multiplier=1.0
    def switch_cost(self,kind):return {'palette_change':.1,'brush_change':.2,'verification':.1,'fill':.1}.get(kind,.1)
    def fixed_overhead(self,**kwargs):return FakeBreakdown(0.0)
    def risk_adjusted_seconds(self,value):return float(value)
    def sequence_cost(self,sequence,**kwargs):
        return FakeBreakdown(sum(float(e.get('fake_cost',.1)) for e in sequence))


class ExtraFastTenImprovementTests(unittest.TestCase):
    def test_canonical_deadline_reserve_is_used_once(self):
        o=opts(60);m=build_cost_model(o,(200,100),(200,100))
        active,usable,meta,reserve,total=ar._budget_seconds(o,m,[],[],(200,100),(200,100))
        self.assertTrue(active);self.assertEqual(total,60.0)
        self.assertAlmostEqual(reserve,automatic_reserve(60.0),places=6)
        self.assertAlmostEqual(meta['deadline']['render_budget_seconds'],60.0-reserve,places=6)
        self.assertLess(usable,meta['deadline']['render_budget_seconds'])

    def test_fill_order_batches_colors_large_first(self):
        rows=[{'color_index':1,'area_pixels':20,'seed_pixel':(50,50)},
              {'color_index':0,'area_pixels':10,'seed_pixel':(5,5)},
              {'color_index':1,'area_pixels':100,'seed_pixel':(20,20)},
              {'color_index':0,'area_pixels':80,'seed_pixel':(8,8)}]
        ordered,meta=ar._order_fill_regions_for_execution(rows)
        colors=[r['color_index'] for r in ordered]
        self.assertEqual(len(meta['batches']),2)
        self.assertLessEqual(sum(a!=b for a,b in zip(colors,colors[1:])),1)
        for color in set(colors):
            batch=[r for r in ordered if r['color_index']==color]
            self.assertEqual(batch[0]['area_pixels'],max(r['area_pixels'] for r in batch))

    def test_schedule_reserves_protected_and_phase_components(self):
        o=opts(30);m=build_cost_model(o,(200,120),(200,120))
        cs=[choice(1,0,'foundation',.1,.4),choice(2,0,'structure',.1,.3),
            choice(3,1,'detail',.1,.2,protected=8,importance=.9),choice(4,1,'correction',.1,.1)]
        seqs={c.component_id:entry(c.component_id,c.color_index,c.component_id*20,c.brush_px,phase=c.phase) for c in cs}
        _g,_s,meta=ar._schedule(cs,seqs,(200,120),m,o,[])
        self.assertGreaterEqual(meta['protected_seed_components'],1)
        self.assertGreaterEqual(meta['phase_seed_components'],2)
        self.assertTrue(meta['risk_adjusted_budget_guard'])
        self.assertGreaterEqual(meta['risk_adjusted_path_cost_seconds'],meta['selected_path_cost_seconds'])

    def test_transition_ordering_prefers_near_component(self):
        o=opts(30);m=build_cost_model(o,(400,100),(400,100))
        cs=[choice(1,0,gain=.9),choice(2,0,gain=.2),choice(3,0,gain=.19)]
        seqs={1:entry(1,0,0),2:entry(2,0,300),3:entry(3,0,20)}
        _g,s,meta=ar._schedule(cs,seqs,(400,100),m,o,[])
        ids=[]
        for e in s:
            if e['component_id'] not in ids:ids.append(e['component_id'])
        self.assertEqual(ids[:3],[1,3,2])
        self.assertTrue(meta['transition_cost_ordering'])

    def test_transition_ordering_accounts_for_brush_switch(self):
        o=opts(30);m=build_cost_model(o,(150,100),(150,100))
        cs=[choice(1,0,gain=.9,brush=2),choice(2,0,gain=.2,brush=28),choice(3,0,gain=.19,brush=2)]
        seqs={1:entry(1,0,0,2),2:entry(2,0,10,28),3:entry(3,0,18,2)}
        _g,s,meta=ar._schedule(cs,seqs,(150,100),m,o,[])
        ids=[]
        for e in s:
            if e['component_id'] not in ids:ids.append(e['component_id'])
        self.assertEqual(ids[:3],[1,3,2]);self.assertTrue(meta['brush_aware_ordering'])

    def test_wide_brush_searches_native_and_half_stride(self):
        target=np.ones((24,40),dtype=np.bool_);residual=target.copy();seen=[]
        comp=SimpleNamespace(component_id=1,color_index=0,area=int(target.size),bbox=(0,0,39,23),
            width=40,height=24,importance_mean=.1,importance_max=.1,edge_mean=.1,contour_mean=.1,
            protected_pixels=0,protected_ratio=0.0)
        m=build_cost_model(opts(30),(40,24),(40,24));real=ar._runs_from_mask
        def spy(mask,row_stride=1,row_offset=0,orientation='horizontal'):
            seen.append(int(row_stride));return real(mask,row_stride,row_offset,orientation)
        with patch.object(ar,'_runs_from_mask',side_effect=spy):
            paths,painted,_cost=ar._candidate_paths_for_brush(target,residual,8,model=m,comp=comp,phase='foundation',final_size=False)
        self.assertTrue(paths);self.assertTrue(np.any(painted));self.assertIn(8,seen);self.assertIn(4,seen)

    def test_brush_pack_prunes_oversized_controls_and_tests_ladders(self):
        eligible,pruned=ar._eligible_brush_sizes_for_roi((28,16,8,4,2),(12,12))
        self.assertEqual(eligible,(8,4,2));self.assertEqual(pruned,(28,16))

        cmap=np.full((80,120),7,dtype=np.int32)
        h_runs=[(0,y,119,y) for y in range(80)]
        v_runs=[(x,0,x,79) for x in range(120)]
        comp=SimpleNamespace(component_id=7,color_index=0,area=120*80,bbox=(0,0,119,79),width=120,height=80,
            importance_mean=.08,importance_max=.12,edge_mean=.08,contour_mean=.08,protected_pixels=0,
            protected_ratio=0.0,horizontal_runs=h_runs,vertical_runs=v_runs)
        o=opts(30);m=build_cost_model(o,(120,80),(120,80));packed,reason=ar._brush_pack_candidate(comp,cmap,o,m)
        self.assertIsNotNone(packed,reason)
        self.assertGreaterEqual(packed['ladder_candidates_evaluated'],2)
        self.assertGreaterEqual(packed['exact_ladder_candidates'],1)
        self.assertGreaterEqual(len(set(packed['used_brush_sizes'])),2)

    def test_exact_swap_replaces_lower_value_component_when_refill_cannot_fit(self):
        cs=[choice(1,0,cost=.5,gain=10),choice(2,0,cost=.5,gain=1),choice(3,0,cost=10,gain=9)]
        seqs={1:entry(1,0,0,fake_cost=2),2:entry(2,0,180,fake_cost=2),3:entry(3,0,5,fake_cost=2)}
        with patch.object(ar,'_budget_seconds',return_value=(True,4.1,{},0.0,5.0)):
            _g,s,meta=ar._schedule(cs,seqs,(200,100),FakeModel(),{'brush_px':2,'paint_current_color':False},[])
        ids={e['component_id'] for e in s}
        self.assertIn(1,ids);self.assertIn(3,ids);self.assertNotIn(2,ids)
        self.assertGreaterEqual(meta['budget_swapped_components'],1)

    def test_version_stays_rc25(self):self.assertEqual(APP_VERSION,'1.0.146-rc2')

if __name__=='__main__':unittest.main()
