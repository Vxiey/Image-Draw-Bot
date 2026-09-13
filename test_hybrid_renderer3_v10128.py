import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from HybridRenderer3 import (
    HYBRID_MODES, HYBRID_RENDER_STYLE, SAFETY_STATE_KEYS,
    analyze_source, apply_hybrid_policy, pass_plan, resolve_hybrid_mode,
    validate_hybrid_mode,
)


class HybridRenderer3Step29Tests(unittest.TestCase):
    @staticmethod
    def base_options(**extra):
        out = {
            'render_style': HYBRID_RENDER_STYLE,
            'hybrid_mode': 'Auto Hybrid',
            'render_preset': 'Manual',
            'time_budget_mode': 'Manual',
            'time_budget_active': False,
            'max_seconds': 180,
            'manual_max_seconds': 180,
            'paint_current_color': False,
            'erase_mode': False,
            'outline': False,
            'fill_tool_available': True,
            'canvas_guard_enabled': True,
            'strict_runtime_safety': True,
            'target_lock_passed': True,
            'safety_preflight_passed': True,
            'dry_run_passed': True,
            'profile_key': 'microsoft-paint',
            'profile_name': 'Microsoft Paint',
        }
        out.update(extra)
        return out

    def test_modes_are_explicit_and_validate(self):
        self.assertEqual(HYBRID_MODES, (
            'Auto Hybrid','Pixel Art','Icon / Logo','Line Art','Portrait',
            'Shaded Object','Deadline Silhouette'))
        for mode in HYBRID_MODES:
            self.assertEqual(validate_hybrid_mode(mode), mode)
        with self.assertRaises(ValueError):
            validate_hybrid_mode('AI auto')

    def test_line_art_analysis_routes_to_line_art(self):
        im = Image.new('RGB',(420,260),'white')
        d = ImageDraw.Draw(im)
        d.line((30,40,380,210),fill='black',width=5)
        d.ellipse((110,55,300,230),outline='black',width=5)
        mode, analysis = resolve_hybrid_mode(im,self.base_options())
        self.assertEqual(mode,'Line Art')
        self.assertGreater(analysis.white_fraction,.70)
        self.assertLess(analysis.chroma_fraction,.05)

    def test_small_block_palette_routes_to_pixel_art(self):
        im = Image.new('RGB',(48,48),(250,250,250))
        d = ImageDraw.Draw(im)
        d.rectangle((4,4,22,22),fill=(220,30,40))
        d.rectangle((24,4,43,22),fill=(30,100,220))
        d.rectangle((4,24,43,43),fill=(25,25,25))
        mode, analysis = resolve_hybrid_mode(im,self.base_options())
        self.assertEqual(mode,'Pixel Art')
        self.assertLessEqual(analysis.quantized_colors,28)
        self.assertGreaterEqual(analysis.pixel_art_score,.68)

    def test_large_flat_graphic_routes_to_icon_logo(self):
        im = Image.new('RGB',(512,280),'white')
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((40,40,472,240),radius=45,fill=(35,155,95))
        d.rectangle((180,90,330,190),fill=(245,205,35))
        mode, analysis = resolve_hybrid_mode(im,self.base_options())
        self.assertEqual(mode,'Icon / Logo')
        self.assertGreaterEqual(analysis.flatness_score,.78)

    def test_short_deadline_routes_texture_to_silhouette(self):
        im = Image.new('RGB',(320,220),'white')
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                px[x,y] = ((x*7+y*3)%256,(x*3+y*11)%256,(x*13+y*5)%256)
        mode, _ = resolve_hybrid_mode(im,self.base_options(
            time_budget_active=True,time_budget_seconds=45,deadline_render_budget_seconds=45))
        self.assertEqual(mode,'Deadline Silhouette')

    def test_auto_does_not_claim_portrait_recognition(self):
        im = Image.new('RGB',(360,240),(145,130,118))
        d = ImageDraw.Draw(im)
        for y in range(0,240,8):
            d.line((0,y,359,(y*3)%240),fill=((y*5)%255,90,160),width=3)
        mode, _ = resolve_hybrid_mode(im,self.base_options())
        self.assertNotEqual(mode,'Portrait')
        explicit, _ = resolve_hybrid_mode(im,self.base_options(hybrid_mode='Portrait'))
        self.assertEqual(explicit,'Portrait')

    def test_policy_preserves_native_safety_state(self):
        im = Image.new('RGB',(64,64),'white')
        d = ImageDraw.Draw(im); d.rectangle((8,8,55,55),fill='red')
        source = self.base_options(hybrid_mode='Icon / Logo', target_handle=12345,
                                   corners=[(10,10),(200,200)],
                                   palette_positions=[(5,5),(9,5)],
                                   tool_actions=[('brush',(1,1))])
        before = {k:source.get(k) for k in SAFETY_STATE_KEYS if k in source}
        out = apply_hybrid_policy(im,source)
        after = {k:out.get(k) for k in before}
        self.assertEqual(before,after)
        self.assertTrue(out['hybrid_renderer_active'])
        self.assertFalse(out['hybrid_renderer_meta']['native_input_changed'])
        self.assertFalse(out['hybrid_renderer_meta']['semantic_ai_used'])
        self.assertFalse(out['hybrid_renderer_meta']['ocr_used'])

    def test_specialised_modes_route_to_existing_real_engines(self):
        im = Image.new('RGB',(96,64),'white')
        expected = {
            'Pixel Art': ('Standard / pixel','Pixel Accurate'),
            'Icon / Logo': ('Quick Sketch Fill + Contour','High likeness'),
            'Line Art': ('Standard / pixel','High likeness'),
            'Portrait': ('Standard / pixel','Maximum likeness'),
            'Shaded Object': ('Standard / pixel','High likeness'),
            'Deadline Silhouette': ('Quick Sketch Fill + Contour','Balanced'),
        }
        for mode,(style,quality) in expected.items():
            with self.subTest(mode=mode):
                out = apply_hybrid_policy(im,self.base_options(hybrid_mode=mode))
                self.assertEqual(out['render_style'],style)
                self.assertEqual(out['draw_quality'],quality)
                self.assertEqual(out['hybrid_mode_resolved'],mode)
                self.assertGreaterEqual(len(out['hybrid_renderer_meta']['passes']),3)

    def test_single_colour_portrait_uses_existing_portrait_planner_route(self):
        im = Image.new('RGB',(80,80),(180,150,130))
        out = apply_hybrid_policy(im,self.base_options(
            hybrid_mode='Portrait',paint_current_color=True))
        self.assertEqual(out['render_style'],'Portrait / shaded')
        self.assertFalse(out['outline'])
        self.assertTrue(out['portrait_focus'])

    def test_pass_plans_are_deterministic(self):
        self.assertEqual(pass_plan('Deadline Silhouette')[0],'recognisable silhouette')
        self.assertIn('micro-detail correction',pass_plan('Pixel Art'))
        self.assertIn('outer contour',pass_plan('Icon / Logo'))

    def test_make_plan_pixel_art_uses_pixel_accurate_backend_and_keeps_hybrid_meta(self):
        from DrawBot import make_plan
        from test_pixel_accurate_v1086 import opts
        im = Image.new('RGB',(24,18),'white')
        d = ImageDraw.Draw(im)
        d.rectangle((2,2,10,14),fill=(220,30,40))
        d.rectangle((12,3,21,15),fill=(30,100,220))
        o = opts(render_preset='Manual',render_style=HYBRID_RENDER_STYLE,
                 hybrid_mode='Pixel Art',draw_quality='High likeness',
                 profile_name='Microsoft Paint',profile_key='microsoft-paint',
                 paint_profile=True,resource_scheduler='Off')
        plan = make_plan(im,(96,72),o)
        meta = plan['options'].get('hybrid_renderer_meta') or {}
        self.assertTrue(meta.get('enabled'))
        self.assertEqual(meta.get('resolved_mode'),'Pixel Art')
        self.assertTrue(plan['options'].get('pixel_accurate'))
        self.assertEqual(plan['options'].get('planning_resolution_effective'),'Pixel Accurate / full target')
        self.assertGreater(plan['count'],0)

    def test_ui_build_and_profile_hooks_exist(self):
        base = Path(__file__).resolve().parent
        drawbot = (base/'DrawBot.py').read_text(encoding='utf-8')
        ui = (base/'StudioUI.py').read_text(encoding='utf-8')
        profile_isolation = (base/'ProfileIsolation.py').read_text(encoding='utf-8')
        portability = (base/'ProfilePortability.py').read_text(encoding='utf-8')
        build = (base/'build_exe.py').read_text(encoding='utf-8')
        self.assertIn('apply_hybrid_policy',drawbot)
        self.assertIn("'Hybrid mode', a.hybrid_mode",ui)
        self.assertIn('HYBRID_RENDER_STYLE',ui)
        self.assertIn("'hybrid_mode'",profile_isolation)
        self.assertIn('hybrid_mode',portability)
        self.assertIn("'HybridRenderer3'",build)

    def test_step29_version(self):
        from Version import APP_VERSION, FILE_VERSION
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')


if __name__ == '__main__':
    unittest.main()
