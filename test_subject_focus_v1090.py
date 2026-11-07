import unittest
import numpy as np
from PIL import Image, ImageDraw
from SubjectFocus import rectangle_mask, subject_mask, focused_stroke_plan
from PixelAccuratePlanner import build_pixel_map
from PixelAccuracyEngine import progressive_time_budget, simulate_strokes
from DrawBot import make_plan
from test_pixel_accurate_v1086 import opts

PALETTE=((255,255,255),(0,0,0),(255,0,0))

class SubjectFocusTests(unittest.TestCase):
    def image(self):
        image=Image.new('RGB',(40,30),'white')
        ImageDraw.Draw(image).rectangle((10,5,29,24),fill='red')
        return image

    def test_uniform_background_mask(self):
        mask,method=subject_mask(self.image())
        self.assertEqual(int(mask.sum()),400)
        self.assertFalse(mask[0,0])
        self.assertTrue(mask[10,15])

    def test_rectangle_validation(self):
        for box in ((0,0,float('nan'),1),(-1,0,1,1),(1,0,0,1),(0,0,0,1)):
            with self.assertRaises(ValueError): rectangle_mask((40,30),box)
        self.assertEqual(rectangle_mask((40,30),(.25,0,.75,1)).sum(),600)

    def test_alpha_is_authoritative(self):
        image=Image.new('RGBA',(10,10),(30,40,50,0))
        image.putpixel((3,3),(30,40,50,255))
        mask,method=subject_mask(image)
        self.assertEqual(mask.sum(),1)
        self.assertEqual(method,'Image transparency')

    def test_complex_border_refuses_to_guess(self):
        rng=np.random.default_rng(10)
        with self.assertRaisesRegex(ValueError,'complex'):
            subject_mask(Image.fromarray(rng.integers(0,256,(30,40,3),dtype=np.uint8)))

    def test_uniform_image_refuses_empty_subject(self):
        with self.assertRaisesRegex(ValueError,'No clear subject'):
            subject_mask(Image.new('RGB',(20,20),'white'))

    def test_cancel(self):
        with self.assertRaises(InterruptedError): subject_mask(self.image(),cancelled=lambda:True)

    def test_only_subject_has_no_background_paths(self):
        im=self.image();pm=build_pixel_map(im,PALETTE,gpu_mode='CPU',skip_white=False)
        target,plan=focused_stroke_plan(pm,im,3,'Subject only')
        self.assertEqual(target.drawable_mask.sum(),400)
        sim=simulate_strokes(target,plan['execution_sequence'],PALETTE)
        self.assertEqual(sim.metrics['pixel_accuracy_percent'],100)
        self.assertFalse(sim.coverage_map[~target.drawable_mask].any())
        self.assertEqual(pm.drawable_mask.sum(),1200)  # Original map is immutable.

    def test_subject_first_is_lossless_and_ordered(self):
        im=self.image();pm=build_pixel_map(im,PALETTE,gpu_mode='CPU',skip_white=False)
        target,plan=focused_stroke_plan(pm,im,3,'Subject first')
        sections=[e['subject_section'] for e in plan['execution_sequence']]
        self.assertIn('background',sections)
        self.assertEqual(sections,sorted(sections,reverse=True))
        self.assertEqual(simulate_strokes(target,plan['execution_sequence'],PALETTE).metrics['pixel_accuracy_percent'],100)

    def test_timer_keeps_subject_before_background_without_unused_correction_reserve(self):
        sequence=[dict(phase='subject/fine_detail',path=((0,0),),color_index=0,subject_section='subject') for _ in range(200)]
        sequence += [dict(phase='background/fill',path=((1,1),),color_index=0,subject_section='background') for _ in range(200)]
        result=progressive_time_budget(sequence,active=True,seconds=5,correction_reserve_ratio=0)
        self.assertTrue(result['paths_omitted'])
        self.assertEqual(result['correction_reserve'],0)
        self.assertTrue(all(e['subject_section']=='subject' for e in result['execution_sequence']))

    def test_integrated_plan_applies_mode_and_keeps_only_selection(self):
        plan=make_plan(self.image(),(40,30),opts(subject_focus='Subject only',subject_region=(.25,1/6,.75,5/6),draw_quality='Balanced',brush_px=3))
        self.assertEqual(plan['options']['brush_px'],3)
        self.assertTrue(plan['options']['pixel_accurate'])
        self.assertFalse(plan['options']['pixel_accuracy_meta']['automatic_corrections'])
        for entry in plan['execution_sequence']:
            for x,y in entry['path']:
                self.assertTrue(10<=x<30 and 5<=y<25,(x,y))

    def test_incompatible_current_colour_is_explicit(self):
        with self.assertRaisesRegex(ValueError,'full colour'):
            make_plan(self.image(),(40,30),opts(subject_focus='Subject first',paint_current_color=True))

    def test_integrated_off_preserves_existing_plan(self):
        plan=make_plan(self.image(),(40,30),opts(subject_focus='Off'))
        self.assertTrue(plan['options']['pixel_accuracy_meta']['automatic_corrections'])
        self.assertNotIn('subject_focus',plan['options']['pixel_map_meta'])

if __name__=='__main__': unittest.main()
