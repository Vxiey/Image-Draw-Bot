import unittest
from types import SimpleNamespace
import numpy as np

from AdaptiveRegionHybrid import _brush_pack_candidate, _choose_component
from ExecutionCostModel import build_cost_model


def options():
    return {
        'profile_key':'gartic','brush_px':2,'speed':'Balanced','delay':0.0,
        'browser_brush_plan':{
            'target_position':(1,1),'confidence':0.99,
            'nominal_sizes':[2,4,8,16,28],
            'verified_sizes':[2,4,8,16,28],
            'control_positions':[(1,1),(2,1),(3,1),(4,1),(5,1)],
            'safe_guard_px':4,
        },
    }


def rectangle_component(width=120,height=80,cid=7):
    cmap=np.full((height,width),cid,dtype=np.int32)
    h_runs=[(0,y,width-1,y) for y in range(height)]
    v_runs=[(x,0,x,height-1) for x in range(width)]
    comp=SimpleNamespace(component_id=cid,color_index=0,area=width*height,bbox=(0,0,width-1,height-1),
        width=width,height=height,importance_mean=.08,importance_max=.12,edge_mean=.08,contour_mean=.08,
        protected_pixels=0,protected_ratio=0.0,horizontal_runs=h_runs,vertical_runs=v_runs)
    return comp,cmap


class Rc6RegionBrushPackingTests(unittest.TestCase):
    def test_gartic_five_size_plan_can_pack_without_one_px(self):
        comp,cmap=rectangle_component()
        model=build_cost_model(options(),(120,80),(120,80))
        packed,reason=_brush_pack_candidate(comp,cmap,options(),model)
        self.assertIsNotNone(packed,reason)
        self.assertTrue(packed['exact'])
        used=tuple(packed['used_brush_sizes'])
        self.assertGreaterEqual(len(set(used)),2)
        self.assertIn(28,used)
        self.assertNotIn(1,used)
        self.assertEqual(packed['covered_pixels'],comp.area)

    def test_irregular_one_pixel_tail_rejects_pack_and_keeps_safe_fallback(self):
        cid=3;cmap=np.full((30,40),-1,dtype=np.int32)
        cmap[4:26,4:36]=cid;cmap[15,36:40]=cid
        area=int(np.count_nonzero(cmap==cid))
        h_runs=[]
        for y in range(30):
            xs=np.flatnonzero(cmap[y]==cid)
            if len(xs):h_runs.append((int(xs[0]),y,int(xs[-1]),y))
        v_runs=[]
        for x in range(40):
            ys=np.flatnonzero(cmap[:,x]==cid)
            if len(ys):v_runs.append((x,int(ys[0]),x,int(ys[-1])))
        comp=SimpleNamespace(component_id=cid,color_index=0,area=area,bbox=(4,4,39,25),width=36,height=22,
            importance_mean=.2,importance_max=.4,edge_mean=.3,contour_mean=.3,protected_pixels=4,
            protected_ratio=4/area,horizontal_runs=h_runs,vertical_runs=v_runs)
        model=build_cost_model(options(),(40,30),(40,30))
        packed,reason=_brush_pack_candidate(comp,cmap,options(),model)
        self.assertIsNone(packed)
        self.assertIn('residual',reason)
        choice,seq,meta=_choose_component(comp,cmap,area,model,options())
        self.assertTrue(seq)
        self.assertNotEqual(choice.method,'region-brush-pack')
        self.assertEqual(meta['base_brush_px'],2)

    def test_isolated_path_never_requests_nonexistent_one_px_control(self):
        cid=9;cmap=np.array([[cid]],dtype=np.int32)
        comp=SimpleNamespace(component_id=cid,color_index=0,area=1,bbox=(0,0,0,0),width=1,height=1,
            importance_mean=1.0,importance_max=1.0,edge_mean=1.0,contour_mean=1.0,protected_pixels=1,
            protected_ratio=1.0,horizontal_runs=[(0,0,0,0)],vertical_runs=[(0,0,0,0)])
        model=build_cost_model(options(),(1,1),(1,1))
        choice,seq,meta=_choose_component(comp,cmap,1,model,options())
        self.assertTrue(seq)
        self.assertTrue(all(int(e.get('brush_px',0))==2 for e in seq))
        self.assertEqual(meta['base_brush_px'],2)


if __name__=='__main__':
    unittest.main()
