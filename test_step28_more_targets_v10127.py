import unittest

from AppTools import capability as tool_capability
from BrowserAutoCalibration import SUPPORTED_BROWSER_PROFILES
from GameProfiles import PROFILES, profile_defaults, profile_ui
from OneClickSetupVerification import setup_mode
from ProfileEngine import policy_for
from ProfileIsolation import scope_visible
from ProfileStorage import (profile_layout_cache_file, profile_palette_file,
                            profile_settings_file, profile_timing_file,
                            profile_verified_color_file)
from TargetCapabilities import capability_for_key
from Version import APP_VERSION, FILE_VERSION


class Step28MoreTargetsTests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(APP_VERSION,'1.0.145-rc29')
        self.assertEqual(FILE_VERSION,'1.0.145')

    def test_new_profiles_are_first_class(self):
        self.assertEqual(PROFILES['Kleki'][0],'kleki')
        self.assertEqual(PROFILES['Magma'][0],'magma')
        for name in ('Kleki','Magma'):
            self.assertIn('browser',profile_ui(name)['badge'].lower())
            defaults=profile_defaults(name)
            self.assertEqual(defaults['mode'],'Shape paths')
            self.assertEqual(defaults['time_budget_mode'],'Manual')
            self.assertEqual(defaults['custom_color_workflow'],'Adaptive exact (recommended)')

    def test_manual_targets_are_not_auto_setup_targets(self):
        for key in ('drawize','gartic-io','kleki','magma'):
            self.assertNotIn(key,SUPPORTED_BROWSER_PROFILES)
            self.assertEqual(setup_mode(key),'manual')
            self.assertEqual(capability_for_key(key).palette_mode,'manual')

    def test_verified_auto_targets_remain_unchanged(self):
        self.assertEqual(SUPPORTED_BROWSER_PROFILES,frozenset({
            'gartic-phone','skribbl','skribbl-fast','sketchheads','sketchful'
        }))

    def test_browser_visibility_distinguishes_manual_and_auto(self):
        self.assertTrue(scope_visible('browser','kleki'))
        self.assertTrue(scope_visible('browser-manual','kleki'))
        self.assertFalse(scope_visible('browser-auto','kleki'))
        self.assertFalse(scope_visible('oneclick','kleki'))
        self.assertTrue(scope_visible('browser-auto','gartic-phone'))
        self.assertTrue(scope_visible('oneclick','gartic-phone'))
        self.assertTrue(scope_visible('oneclick','microsoft-paint'))

    def test_tool_capabilities_are_profile_specific(self):
        for key in ('kleki','magma'):
            cap=tool_capability(key)
            self.assertTrue(cap['brush'])
            self.assertTrue(cap['fill'])
            self.assertTrue(cap['eraser'])
            self.assertFalse(cap['clear'])

    def test_renderer_policies_do_not_contain_native_state(self):
        forbidden={'armed','mouse','target_lock','target_window','preflight','dry_run',
                   'start_authorization','corners','palette_positions','tool_actions'}
        for name in ('Kleki','Magma'):
            policy=policy_for(name)
            self.assertTrue(policy['overrides'])
            self.assertFalse(forbidden & set(policy['overrides']))
            self.assertEqual(policy['overrides']['time_budget_mode'],'Manual')

    def test_storage_is_separate_for_new_targets(self):
        keys=('kleki','magma','gartic-phone','generic')
        for fn in (profile_palette_file,profile_settings_file,profile_timing_file,
                   profile_layout_cache_file,profile_verified_color_file):
            paths=[str(fn(k)) for k in keys]
            self.assertEqual(len(paths),len(set(paths)),fn.__name__)


if __name__=='__main__':
    unittest.main()
