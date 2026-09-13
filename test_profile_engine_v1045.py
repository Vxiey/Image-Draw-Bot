import unittest
from pathlib import Path

from EdgeBehavior import EDGE_BEHAVIOR_MODES
from ProfileEngine import PROFILE_ENGINE_MODES, policy_for, policy_summary, resolve_profile_policy, validate_profile_engine
from Version import APP_VERSION, FILE_VERSION


class ProfileEngineV1045Tests(unittest.TestCase):
    def test_modes_validate(self):
        for value in PROFILE_ENGINE_MODES:self.assertEqual(validate_profile_engine(value),value)
        with self.assertRaises(ValueError):validate_profile_engine('Magic')

    def test_paint_policy_quality_fill_exact_and_verification(self):
        out,meta=resolve_profile_policy('Microsoft Paint',{'speed':'Fast','mode':'Dots'},mode='Auto')
        self.assertEqual(out['mode'],'Shape paths')
        self.assertEqual(out['shape_model'],'Better shapes v2')
        self.assertEqual(out['shape_order'],'Fill first')
        self.assertEqual(out['background_fill'],'Balanced')
        self.assertEqual(out['fill_engine'],'Closed regions v2')
        self.assertEqual(out['color_rendering'],'Perceptual match')
        self.assertEqual(out['visual_verification'],'Strict')
        self.assertEqual(out['precision'],'High')
        self.assertTrue(meta['applied'])

    def test_skribbl_fast_reduces_colors_strokes_and_time(self):
        out,_=resolve_profile_policy('Skribbl.io Fast',{},mode='Auto')
        self.assertEqual(out['color_grouping'],'Reduced palette')
        self.assertEqual(out['max_stroke_cap'],'1000')
        self.assertEqual(out['time_budget_mode'],'Skribbl 60')
        self.assertEqual(out['adaptive_detail'],'Strong simplify')
        self.assertEqual(out['progressive_rendering'],'Off')

    def test_skribbl_quality_keeps_more_detail(self):
        out,_=resolve_profile_policy('Skribbl.io',{},mode='Auto')
        self.assertEqual(out['adaptive_detail'],'Preserve detail')
        self.assertEqual(out['planning_resolution'],'High')
        self.assertEqual(out['progressive_rendering'],'On')
        self.assertEqual(out['max_stroke_cap'],'2500')

    def test_gartic_is_timer_aware(self):
        out,_=resolve_profile_policy('Gartic Phone',{},mode='Auto')
        self.assertEqual(out['time_budget_mode'],'Gartic Phone Fast')
        self.assertEqual(out['speed'],'Fast')
        self.assertEqual(out['background_fill'],'Off')

    def test_manual_settings_are_preserved(self):
        requested={'mode':'Dots','speed':'Safe','max_stroke_cap':'777','edge_behavior':'Hard Clip'}
        out,meta=resolve_profile_policy('Microsoft Paint',requested,mode='Manual settings')
        self.assertEqual(out,requested)
        self.assertFalse(meta['applied'])

    def test_all_policy_values_match_renderer_enums(self):
        from DrawBot import DrawBotApp
        names=('Microsoft Paint','Skribbl.io Fast','Skribbl.io','Gartic.io','Gartic Phone','Sketchful.io','Drawize','Other drawing app')
        for name in names:
            policy=policy_for(name)['overrides']
            if 'edge_behavior' in policy:self.assertIn(policy['edge_behavior'],EDGE_BEHAVIOR_MODES)

    def test_policy_cannot_contain_native_safety_state(self):
        forbidden={'armed','mouse','target_lock','target_window','preflight','dry_run','start_authorization','corners','palette_positions','tool_actions'}
        for name in ('Microsoft Paint','Skribbl.io Fast','Skribbl.io','Gartic.io','Gartic Phone','Sketchful.io','Drawize','Other drawing app'):
            keys=set(policy_for(name)['overrides'])
            self.assertFalse(keys & forbidden,(name,keys & forbidden))

    def test_unknown_custom_profile_uses_generic_policy(self):
        generic=policy_for('Other drawing app')
        custom=policy_for('My custom profile')
        self.assertEqual(custom['overrides'],generic['overrides'])

    def test_ui_and_options_hooks_exist(self):
        ui=Path(__file__).with_name('StudioUI.py').read_text(encoding='utf-8')
        bot=Path(__file__).with_name('DrawBot.py').read_text(encoding='utf-8')
        self.assertIn("'Profile policy'",ui)
        self.assertIn("'Edge behavior'",ui)
        self.assertIn('resolve_profile_policy',bot)
        self.assertIn("'profile_policy_meta':profile_policy_meta",bot)

    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.146-rc2')
        self.assertEqual(FILE_VERSION,'1.0.146')
        self.assertIn('Profile Engine v2',policy_summary('Microsoft Paint'))

if __name__=='__main__':unittest.main()
