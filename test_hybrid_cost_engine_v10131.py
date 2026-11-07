import unittest
from pathlib import Path
from PIL import Image,ImageDraw
from PixelAccuratePlanner import build_pixel_map
from PixelStrokeEngine import connected_components,build_component_paths,build_pixel_stroke_plan
from ExecutionCostModel import build_cost_model
from HybridBenchmark import CASES

PALETTE=((255,255,255),(0,0,0),(255,0,0),(0,0,255))

def opts(**kw):
    d=dict(profile_key='microsoft-paint',profile_name='Microsoft Paint',speed='Balanced',precision='High',brush_px=1,delay=.006,paint_tool='Pencil',effective_paint_tool='Pencil',custom_color_workflow='calibrated-palette',use_region_fill_engine=False,adaptive_hybrid_cost='Auto')
    d.update(kw);return d

class HybridCostEngineTests(unittest.TestCase):
    def test_cold_start_is_explicit_not_fake_calibrated(self):
        m=build_cost_model(opts(),(32,24),(32,24))
        self.assertIn(m.source,('deterministic profile model','measured local calibration','learning local calibration (1/3)','learning local calibration (2/3)'))
        self.assertGreater(m.path_fixed_seconds,0)
    def test_six_required_benchmark_cases_exist(self):
        self.assertEqual(len(CASES),6);self.assertEqual({n for n,_ in CASES},{'icon','line-art','text-small-detail','cartoon-large-colour','photo-gradient','fill-risk'})
    def test_cost_aware_plan_is_exact_and_reports_model(self):
        im=Image.new('RGBA',(28,22),'white');d=ImageDraw.Draw(im);d.rectangle((2,3,20,12),fill='red');d.line((24,2,24,19),fill='blue')
        pm=build_pixel_map(im,PALETTE,gpu_mode='CPU',skip_white=True)
        plan=build_pixel_stroke_plan(pm,len(PALETTE),options=opts())
        self.assertTrue(plan['metadata']['cost_aware']);self.assertIsInstance(plan['metadata']['cost_model'],dict)
        self.assertEqual(sum(len(g) for g in plan['execution_groups']),len(plan['execution_sequence']))
    def test_legacy_fallback_remains_available(self):
        im=Image.new('RGBA',(16,12),'red');pm=build_pixel_map(im,PALETTE,gpu_mode='CPU',skip_white=True)
        plan=build_pixel_stroke_plan(pm,len(PALETTE),options=opts(adaptive_hybrid_cost='Off'))
        self.assertFalse(plan['metadata']['cost_aware'])
    def test_component_candidate_never_paints_outside(self):
        im=Image.new('RGBA',(12,10),'white');d=ImageDraw.Draw(im);d.rectangle((1,1,8,6),fill='red');d.rectangle((4,3,5,4),fill='white')
        pm=build_pixel_map(im,PALETTE,gpu_mode='CPU',skip_white=True);comps,cmap,_=connected_components(pm)
        red=max((c for c in comps if c.color_index==2),key=lambda c:c.area)
        paths,meta=build_component_paths(red,cmap,cost_model=build_cost_model(opts(),(12,10),(12,10)))
        self.assertTrue(paths);self.assertIn(meta['selection'],('calibrated-time','legacy-run-count'))
        # Exact planner fallback/verification is authoritative for holes.
        self.assertTrue(meta['safe_verified'] or meta['fallback'])
    def test_drawbot_forwards_full_options_to_subject_planner(self):
        from contextlib import closing
        from unittest.mock import patch
        import DrawBot
        import SubjectFocus
        from test_v148_rendering_batch06_canvas import close_plan
        from test_v148_rendering_batch17_layered_diagnostics import calibrated
        from test_v148_rendering_batch24_component_queue import public_options
        original=SubjectFocus.focused_stroke_plan
        cancelled=lambda:False
        for policy in ('Auto','Off'):
            with self.subTest(adaptive_hybrid_cost=policy),calibrated(PALETTE),closing(Image.new('RGBA',(28,22),'white')) as image:
                draw=ImageDraw.Draw(image)
                draw.rectangle((2,3,20,12),fill='red')
                draw.line((24,2,24,19),fill='blue')
                del draw
                settings=public_options(adaptive_hybrid_cost=policy,profile_key='microsoft-paint',
                    profile_name='Microsoft Paint',gpu_mode='CPU',subject_focus='Off')
                observed=[]
                def forward(*args,options,cancelled,**kwargs):
                    observed.append((options,cancelled))
                    return original(*args,options=options,cancelled=cancelled,**kwargs)
                plan=None
                try:
                    with patch.object(SubjectFocus,'focused_stroke_plan',new=forward):
                        plan=DrawBot.make_plan(image,image.size,settings,cancelled)
                    self.assertEqual(len(observed),1)
                    forwarded,callback=observed[0]
                    self.assertIs(callback,cancelled)
                    for key in ('profile_key','adaptive_hybrid_cost','gpu_mode','subject_focus',
                                'brush_px','cpu_workers_resolved','skip_white'):
                        self.assertEqual(forwarded[key],settings[key],key)
                    self.assertIs(forwarded['_execution_cost_calibration_override'],settings['_execution_cost_calibration_override'])
                    self.assertTrue(forwarded['pixel_accurate'])
                    self.assertEqual(forwarded['color_selectors'],plan['color_selectors'])
                    self.assertEqual(plan['options']['pixel_stroke_meta']['cost_aware'],policy=='Auto')
                    self.assertGreater(plan['count'],0)
                finally:
                    if plan is not None:close_plan(plan,image)
    def test_region_fill_uses_shared_cost_model(self):
        text=Path('RegionFillEngine.py').read_text(encoding='utf-8')
        self.assertIn('from ExecutionCostModel import build_cost_model',text)
        self.assertNotIn('from HybridCostModel import build_cost_model',text)
    def test_region_fill_fallback_is_deterministic(self):
        text=Path('RegionFillEngine.py').read_text(encoding='utf-8')
        section=text[text.index('def _legacy_region_cost'):text.index('def _region_cost')]
        self.assertNotIn('correction_for',section);self.assertNotIn('HybridCostModel',section)
        self.assertIn('fill_cost += max(.08, delivery.ui_control_delay*.45) + .24',section)
    def test_gartic_specialized_route_not_replaced(self):
        text=Path('DrawBot.py').read_text(encoding='utf-8');self.assertIn('optimize_gartic_phone_groups',text);self.assertIn('build_gartic_execution_paths',text)
    def test_no_human_mode_added_to_new_engine(self):
        self.assertNotIn('HumanMode',Path('HybridCostModel.py').read_text(encoding='utf-8'));self.assertNotIn('HumanMode',Path('HybridBenchmark.py').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
