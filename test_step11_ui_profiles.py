import unittest
from pathlib import Path

from AppTools import capability
from GameProfiles import PROFILES, PROFILE_DEFAULTS, PROFILE_UI, profile_defaults, profile_ui
from UIState import compute_workspace_state
from Version import APP_VERSION, FILE_VERSION


class Step11UIProfileTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc1')
        self.assertEqual(FILE_VERSION,'1.0.146')

    def test_every_standard_profile_has_ui_metadata_and_defaults(self):
        self.assertEqual(set(PROFILES), set(PROFILE_UI))
        self.assertEqual(set(PROFILES), set(PROFILE_DEFAULTS))
        for name in PROFILES:
            ui=profile_ui(name);defaults=profile_defaults(name)
            for key in ('icon','badge','prepare_title','prepare_subtitle','tool_button','palette_button','area_button','tip'):
                self.assertTrue(str(ui.get(key,'')).strip(), (name,key))
            for key in ('mode','speed','planning_resolution','color_grouping'):
                self.assertIn(key,defaults,(name,key))

    def test_web_profiles_use_shape_defaults(self):
        for name in ('Skribbl.io','Sketchful.io','Drawize','Gartic.io','Kleki','Magma'):
            defaults=profile_defaults(name)
            self.assertEqual(defaults['mode'],'Shape paths',name)
            self.assertEqual(defaults['shape_model'],'Better shapes v2',name)
            self.assertEqual(defaults['progressive_rendering'],'On',name)
        gartic=profile_defaults('Gartic Phone')
        self.assertEqual(gartic['mode'],'Smart paths (recommended)')
        self.assertEqual(gartic['progressive_rendering'],'Off')
        self.assertEqual(gartic['custom_color_workflow'],'Calibrated palette')
        self.assertEqual(gartic['time_budget_mode'],'Gartic Phone Fast')
        fast=profile_defaults('Skribbl.io Fast')
        self.assertEqual(fast['mode'],'Smart paths (recommended)')
        self.assertEqual(fast['progressive_rendering'],'Off')
        self.assertEqual(fast['custom_color_workflow'],'Calibrated palette')
        self.assertEqual(fast['color_rendering'],'Perceptual match')
        self.assertEqual(fast['time_budget_mode'],'Skribbl 60')

    def test_skribbl_fast_has_explicit_tool_capability(self):
        cap=capability('skribbl-fast')
        self.assertTrue(cap['brush']);self.assertTrue(cap['fill']);self.assertTrue(cap['eraser'])
        self.assertIn('Skribbl',cap['note'])

    def test_non_paint_profile_is_ready_not_attention(self):
        state=compute_workspace_state(image_loaded=True,target_name='Skribbl.io',paint_tools_ready=True,
                                      area_ready=True,palette_ready=True,test_passed=True,target_locked=True,
                                      preflight_passed=True,dry_run_passed=True)
        target=next(i for i in state.items if i.key=='target')
        tools=next(i for i in state.items if i.key=='tools')
        self.assertEqual(target.state,'ready')
        self.assertIn('Skribbl.io',target.label)
        self.assertEqual(tools.state,'ready')
        self.assertNotIn('Paint',tools.label)

    def test_ui_contains_icons_dynamic_profile_guide_and_generic_prepare_step(self):
        source=(Path(__file__).resolve().parent/'StudioUI.py').read_text(encoding='utf-8')
        for text in ('🎯','🖼️','🧰','⚙️','▶️','profile_guide_recommend','profile_ui(a.game.get())',
                     "step_card(3, 'Prepare target app'", "item_glyphs = {'ready': '✓'"):
            self.assertIn(text,source)

    def test_drawbot_applies_profile_defaults_before_reading_saved_settings(self):
        source=(Path(__file__).resolve().parent/'DrawBot.py').read_text(encoding='utf-8')
        defaults_pos=source.index('apply_profile_defaults(self,selected)')
        settings_pos=source.index('self.read_settings()',defaults_pos)
        self.assertLess(defaults_pos,settings_pos)
        self.assertIn("self.preview_mode.set('Manual')",source[settings_pos:settings_pos+800])


if __name__=='__main__':unittest.main()
