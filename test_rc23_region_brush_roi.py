\
import unittest
from types import SimpleNamespace
import numpy as np

from AdaptiveRegionHybrid import _brush_pack_candidate,_paint_path
from ExecutionCostModel import build_cost_model
from Version import APP_VERSION


def options():
    return {'profile_key':'gartic','brush_px':2,'speed':'Balanced','delay':0.0,
            'browser_brush_plan':{'target_position':(10,10),'confidence':.99,
                'nominal_sizes':[2,4,8,16,28],'verified_sizes':[2,4,8,16,28],
                'control_positions':[(1,1),(2,1),(3,1),(4,1),(5,1)],'safe_guard_px':4}}


def offset_rectangle(canvas=(1400,900),origin=(900,610),size=(120,80),cid=7):
    w,h=canvas;ox,oy=origin;rw,rh=size
    cmap=np.full((h,w),-1,dtype=np.int32);cmap[oy:oy+rh,ox:ox+rw]=cid
    h_runs=[(ox,y,ox+rw-1,y) for y in range(oy,oy+rh)]
    v_runs=[(x,oy,x,oy+rh-1) for x in range(ox,ox+rw)]
    comp=SimpleNamespace(component_id=cid,color_index=0,area=rw*rh,
        bbox=(ox,oy,ox+rw-1,oy+rh-1),width=rw,height=rh,
        importance_mean=.08,importance_max=.12,edge_mean=.08,contour_mean=.08,
        protected_pixels=0,protected_ratio=0.0,horizontal_runs=h_runs,vertical_runs=v_runs)
    return comp,cmap


class Rc23RegionBrushRoiTests(unittest.TestCase):
    def test_far_offset_component_emits_global_paths_and_exact_full_canvas_coverage(self):
        comp,cmap=offset_rectangle();opts=options()
        model=build_cost_model(opts,(cmap.shape[1],cmap.shape[0]),(cmap.shape[1],cmap.shape[0]))
        packed,reason=_brush_pack_candidate(comp,cmap,opts,model)
        self.assertIsNotNone(packed,reason);self.assertTrue(packed['exact'])
        x0,y0,x1,y1=comp.bbox
        self.assertTrue(all(x0<=x<=x1 and y0<=y<=y1 for e in packed['sequence'] for x,y in e['path']))
        painted=np.zeros(cmap.shape,dtype=np.bool_)
        for e in packed['sequence']:_paint_path(painted,e['path'],int(e['brush_px']))
        self.assertTrue(np.array_equal(painted,cmap==comp.component_id))

    def test_workspace_is_component_bbox_not_full_canvas(self):
        comp,cmap=offset_rectangle(canvas=(2000,1200),origin=(1500,850),size=(100,60));opts=options()
        model=build_cost_model(opts,(2000,1200),(2000,1200))
        packed,reason=_brush_pack_candidate(comp,cmap,opts,model)
        self.assertIsNotNone(packed,reason)
        self.assertEqual(packed['packing_workspace_pixels'],100*60)
        self.assertEqual(packed['packing_canvas_pixels'],2000*1200)
        self.assertGreater(packed['packing_workspace_reduction_percent'],99.0)
        self.assertEqual(tuple(packed['packing_roi_bbox']),comp.bbox)

    def test_roi_keeps_verified_multibrush_ladder(self):
        comp,cmap=offset_rectangle();opts=options();model=build_cost_model(opts,(1400,900),(1400,900))
        packed,reason=_brush_pack_candidate(comp,cmap,opts,model)
        self.assertIsNotNone(packed,reason)
        used=set(packed['used_brush_sizes'])
        self.assertIn(28,used);self.assertGreaterEqual(len(used),2);self.assertNotIn(1,used)

    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc2')


if __name__=='__main__':unittest.main()
