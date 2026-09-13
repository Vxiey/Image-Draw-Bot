import tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
import CompletedDrawingAnalysis as CDA
from GarticOpacity import choose_opacity_percent,validate_opacity,plan_gartic_opacity
from AutoBrushWidth import resolve_brush_width
from BrowserBrushSize import plan_browser_brush_size
from Version import APP_VERSION

class Rc27Tests(unittest.TestCase):
    def test_version(self):self.assertEqual(APP_VERSION,'1.0.146-rc2')
    def test_gartic_auto_brush_never_exceeds_level_five(self):
        im=Image.new('RGB',(3000,1800),'white')
        self.assertLessEqual(resolve_brush_width(im,target_size=im.size,profile_key='gartic-phone',render_preset='Extra fast').brush_px,5)
    def test_opacity_validation(self):
        self.assertEqual(validate_opacity('30%'),'30%')
        with self.assertRaises(ValueError):validate_opacity('25%')
    def test_flat_image_prefers_opaque(self):
        im=Image.new('RGB',(400,300),'white');ImageDraw.Draw(im).rectangle((40,40,360,260),fill='red')
        self.assertEqual(choose_opacity_percent(im,requested='Auto')['selected_percent'],100)
    def test_completed_analysis_keeps_accuracy_components(self):
        plan={'options':{'profile_key':'gartic-phone','profile_name':'Gartic Phone','post_draw_accuracy_meta':{'available':True,'trusted':True,'feedback_trust':'high','visual_accuracy_percent':91.5,'source_pixel_accuracy_percent':90,'perceptual_color_accuracy_percent':92,'luminance_accuracy_percent':94,'hue_accuracy_percent':91,'edge_accuracy_percent':87,'actual_coverage_percent':98,'unexpected_ink_percent':1.0},'runtime_operation_timing':{'stroke':{'count':10,'total_seconds':5,'average_seconds':.5}},'browser_brush_plan':{'requested_level':3,'effective_level':3,'nominal_sizes':[2,4,8]}},'draw_time_estimate':{'projected_seconds':12},'estimate':12}
        r=CDA.build_completed_drawing_report(plan,10,completed_paths=10)
        self.assertEqual(r['drawing_accuracy_score_0_100'],91.5);self.assertEqual(r['accuracy']['edge_accuracy_percent'],87.0)
        self.assertIn('recommendations',r)
    def test_source_contains_universal_scoring_and_completed_analysis(self):
        src=Path('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn("if dry_run or not hasattr(mouse,'snapshot_canvas')",src)
        self.assertIn('from CompletedDrawingAnalysis import record_completed_drawing',src)
        self.assertIn("note_runtime_operation('opacity_change'",src)

if __name__=='__main__':unittest.main()
