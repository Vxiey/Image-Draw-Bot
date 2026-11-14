import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from DetailZoomPass import (
    DETAIL_ZOOM_MODES,
    add_detail_zoom_pass,
    render_detail_zoom_preview,
    validate_detail_zoom_mode,
)
from DrawBot import make_plan


class Step24AdaptiveDetailZoomTests(unittest.TestCase):
    @staticmethod
    def micro_source():
        src = Image.new('RGB', (64, 64), 'white')
        d = ImageDraw.Draw(src)
        # Thin source-only micro lines that disappear from the intentionally
        # blank 16x16 global planning image used in the direct unit tests.
        for k in range(6, 11):
            d.line((k * 4, 24, k * 4 + 3, 27), fill='black', width=1)
        return src

    @staticmethod
    def direct_options(**changes):
        out = {
            'detail_zoom': '4x', 'draw_quality': 'Maximum likeness',
            'time_budget_active': False, 'skip_white': False, 'brush_px': 1,
            'color_fidelity': 'Faithful', 'color_rendering': 'Perceptual match',
            'profile_key': 'microsoft-paint', 'effective_paint_tool': 'Pencil',
            'delay': .002,
        }
        out.update(changes)
        return out

    def test_modes_validate(self):
        self.assertEqual(DETAIL_ZOOM_MODES, ('Auto', 'Off', '2x', '4x'))
        self.assertEqual(validate_detail_zoom_mode('4x'), '4x')
        with self.assertRaises(ValueError):
            validate_detail_zoom_mode('8x')

    def test_recovers_source_micro_detail_without_target_zoom(self):
        src = self.micro_source()
        work = Image.new('RGB', (16, 16), 'white')
        groups = [[], []]
        execution = [[], []]
        ng, ne, ns, meta = add_detail_zoom_pass(
            src, work, ((255, 255, 255), (0, 0, 0)),
            groups, execution, [], self.direct_options(), fitted=(64,64))
        self.assertTrue(meta['enabled'])
        self.assertEqual(meta['analysis_zoom'], '4x')
        self.assertFalse(meta['target_app_zoomed'])
        self.assertEqual(meta['target_zoom_policy'], 'internal-source-analysis-only')
        self.assertGreater(meta['detail_paths_added'], 0)
        self.assertGreater(len(ne[1]), 0)
        self.assertGreater(len(ng[1]), 0)
        # The late pass now materializes the entire base before the new detail.
        # This fixture has an empty base, so all sequence rows are detail rows.
        self.assertTrue(meta['sequence_created_for_detail_pass'])
        self.assertEqual(len(ns), sum(len(g) for g in ne))
        self.assertTrue(all(row.get('detail_zoom') for row in ns))

    def test_progressive_sequence_gets_optional_detail_entries(self):
        src = self.micro_source()
        work = Image.new('RGB', (16, 16), 'white')
        base_groups = [[(0, 0, 2, 0)], []]
        base_exec = [[[(0, 0), (2, 0)]], []]
        seq = [{'color_index': 0, 'path': ((0, 0), (2, 0)), 'phase': 'major_coverage'}]
        _, _, out_seq, meta = add_detail_zoom_pass(
            src, work, ((255, 255, 255), (0, 0, 0)), base_groups, base_exec, seq,
            self.direct_options(time_budget_active=True, time_budget_seconds=80), fitted=(64,64))
        self.assertTrue(meta['enabled'])
        self.assertTrue(meta['sequence_appended'])
        details = [e for e in out_seq if e.get('detail_zoom')]
        self.assertTrue(details)
        self.assertTrue(all(e.get('optional') for e in details))
        self.assertTrue(all(e.get('phase') == 'important_details' for e in details))
        self.assertLessEqual(len(details), 16)

    def test_pixel_accurate_does_not_duplicate_full_pixelmap(self):
        src = self.micro_source()
        work = Image.new('RGB', (16, 16), 'white')
        _, _, _, meta = add_detail_zoom_pass(
            src, work, ((255,255,255),(0,0,0)), [[],[]], [[],[]], [],
            self.direct_options(detail_zoom='4x', draw_quality='Pixel Accurate'))
        self.assertFalse(meta['enabled'])
        self.assertEqual(meta.get('factor'), 1)

    def test_deadline_budget_is_bounded(self):
        src = Image.new('RGB',(128,128),'white')
        d = ImageDraw.Draw(src)
        for y in range(0,128,4):
            d.line((0,y,127,y),fill='black',width=1)
        work = Image.new('RGB',(32,32),'white')
        _, ne, _, meta = add_detail_zoom_pass(
            src, work, ((255,255,255),(0,0,0)), [[],[]], [[],[]], [],
            self.direct_options(time_budget_active=True,time_budget_seconds=75))
        self.assertLessEqual(meta.get('path_cap', 99), 16)
        self.assertLessEqual(sum(len(g) for g in ne), 16)

    def test_preview_overlay_marks_rois_only(self):
        meta = {
            'enabled': True, 'working_size': (16,16),
            'roi_boxes': ((2,3,6,8),(9,1,12,4)),
        }
        overlay = render_detail_zoom_preview((160,160), meta)
        self.assertEqual(overlay.mode, 'RGBA')
        self.assertEqual(overlay.size, (160,160))
        self.assertGreater(overlay.getbbox()[2], overlay.getbbox()[0])

    def test_make_plan_rejects_source_details_that_damage_native_output(self):
        im = Image.new('RGB',(256,256),'white')
        d = ImageDraw.Draw(im)
        d.rectangle((40,40,210,210), fill=(245,210,30))
        d.line((128,55,128,195), fill=(20,20,20), width=2)
        d.ellipse((118,110,138,130), fill=(210,30,40))
        opts = {
            'detail':8,'delay':.005,'speed':'Balanced','precision':'High','lines':True,
            'skip_white':True,'contrast':1.0,'outline':False,'paint_current_color':False,
            'brush_px':1,'max_seconds':300,'time_budget_mode':'Manual','time_budget_active':False,
            'gpu_mode':'CPU','planning_resolution':'Standard','custom_color_workflow':'Calibrated palette',
            'exact_color_limit':'Auto','exact_color_available':False,'color_rendering':'Perceptual match',
            'color_fidelity':'Faithful','adaptive_detail':'Auto','draw_quality':'Maximum likeness',
            'detail_zoom':'4x','profile_key':'microsoft-paint','profile_name':'Microsoft Paint',
            'drawing_mode':'Smart paths (recommended)','smart_paths':True,'background_fill':'Off',
            'fill_tool_available':False,
        }
        plan = make_plan(im,(64,64),opts)
        meta = plan['options'].get('detail_zoom_meta') or {}
        self.assertFalse(meta.get('enabled'))
        self.assertEqual(meta.get('detail_paths_added'), 0)
        self.assertGreater(meta['quality_gate']['rejected_paths'], 0)
        self.assertFalse(plan['path_stats'].get('detail_zoom_enabled'))
        self.assertFalse(any(row.get('detail_zoom') for row in plan['execution_sequence']))
        self.assertFalse(meta.get('target_app_zoomed'))

    def test_ui_and_build_hooks_exist(self):
        base = Path(__file__).resolve().parent
        ui = (base/'StudioUI.py').read_text(encoding='utf-8')
        drawbot = (base/'DrawBot.py').read_text(encoding='utf-8')
        build = (base/'build_exe.py').read_text(encoding='utf-8')
        self.assertIn("'Detail zoom', a.detail_zoom", ui)
        self.assertIn("('Detail zoom', 'detail_zoom_canvas')", ui)
        self.assertIn("self.detail_zoom = tk.StringVar(value='Auto')", drawbot)
        self.assertIn("'detail_zoom':detail_zoom", drawbot)
        self.assertIn("'DetailZoomPass'", build)


if __name__ == '__main__':
    unittest.main()
