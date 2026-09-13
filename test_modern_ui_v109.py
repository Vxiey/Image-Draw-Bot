import unittest
from pathlib import Path
from PIL import Image

from UIState import compute_workspace_state, classify_error
from PreviewLayers import build_auxiliary_previews
from Version import APP_VERSION, FILE_VERSION


class ModernUIV109Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_not_ready_state(self):
        state=compute_workspace_state(image_loaded=False,target_name='Microsoft Paint',paint_tools_ready=False,
                                      area_ready=False,palette_ready=False,test_passed=False)
        self.assertEqual(state.label,'Not ready')
        self.assertFalse(state.ready)

    def test_ready_state(self):
        state=compute_workspace_state(image_loaded=True,target_name='Microsoft Paint',paint_tools_ready=True,
                                      area_ready=True,palette_ready=True,test_passed=True,target_locked=True,gpu_text='CUDA ready')
        self.assertEqual(state.label,'Ready to draw')
        self.assertTrue(state.ready)
        self.assertEqual(next(i for i in state.items if i.key=='gpu').detail,'CUDA ready')

    def test_error_state_and_plain_english_paint_error(self):
        text='Stopped: the first stroke did not get the expected color (0, 0, 0). Closest rendered RGB was (232, 237, 242).'
        state=compute_workspace_state(image_loaded=True,target_name='Microsoft Paint',paint_tools_ready=True,
                                      area_ready=True,palette_ready=True,test_passed=False,status=text)
        self.assertEqual(state.label,'Error')
        info=classify_error(text)
        self.assertIn('color verification',info['title'])
        self.assertIn('Auto Paint calibration',info['action'])

    def test_normal_stop_is_not_error(self):
        self.assertIsNone(classify_error('Stopped.'))

    def test_auxiliary_previews_have_expected_layers(self):
        image=Image.new('RGB',(40,30),(245,245,245))
        groups=[[(3,4,30,4)],[(10,8,10,22)]]
        palette=((0,0,0),(220,60,60))
        def point(x,y):return (x*2,y*2)
        options={'background_fill_plan':{'enabled':True,'color_index':1},
                 'fill_regions':[{'bbox':(5,5,15,15),'color_index':1}]}
        maps=build_auxiliary_previews(image,(80,60),groups,palette,point,2,options)
        self.assertEqual(set(maps),{'stroke','fill','color'})
        for preview in maps.values():
            self.assertEqual(preview.size,(80,60))
            self.assertEqual(preview.mode,'RGB')

    def test_ui_source_contains_five_step_workspace_and_modes(self):
        source=(Path(__file__).resolve().parent/'StudioUI.py').read_text(encoding='utf-8')
        for text in ('Choose target app','Add image','Prepare target app','Configure drawing',"step_card(5, 'Safety & draw'",
                     "['Simple', 'Advanced', 'Developer']",'Readiness','NEXT STEP'):
            self.assertIn(text,source)

    def test_ui_source_contains_five_preview_tabs(self):
        source=(Path(__file__).resolve().parent/'StudioUI.py').read_text(encoding='utf-8')
        for text in ("('Original', 'original_canvas')","('Drawing preview', 'result_canvas')",
                     "('Stroke plan', 'stroke_canvas')","('Fill regions', 'fill_canvas')",
                     "('Color map', 'color_canvas')"):
            self.assertIn(text,source)

    def test_release_collects_ui_modules_and_doc(self):
        source=(Path(__file__).resolve().parent/'build_exe.py').read_text(encoding='utf-8')
        self.assertIn("'--hidden-import', 'UIState'",source)
        self.assertIn("'--hidden-import', 'PreviewLayers'",source)
        self.assertNotIn('MODERN-UI-v1.0.9.md',source)

    def test_small_test_readiness_is_tracked(self):
        source=(Path(__file__).resolve().parent/'DrawBot.py').read_text(encoding='utf-8')
        self.assertIn('self.small_test_passed = False',source)
        self.assertIn("self.events.put(('test_passed',True))",source)
        self.assertIn("elif kind=='test_passed':",source)


if __name__=='__main__':unittest.main()
