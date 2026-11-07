"""Actual calibration evidence reaches profile guidance without reapplying policy."""
from collections import UserDict
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

import DrawBot
import DrawTimeCalibration
import ProfilePolish
import ProfileStorage
from Colors import save_calibration
import test_v148_ui_batch07_renderer as renderer_fixtures


WARNING = 'Palette is not verified for this profile; use Auto Setup or Read colors before relying on color accuracy.'


class ProfileWarningFlowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(TemporaryDirectory()))
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=self.directory))
        self.stack.enter_context(patch.object(ProfileStorage, 'data_dir', return_value=self.directory))
        self.stack.enter_context(patch.object(DrawTimeCalibration, 'FILE', self.directory / 'legacy-timing.json'))
        self.stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))

    def app(self, profile='Skribbl.io', policy='Manual settings'):
        app = renderer_fixtures.AdvertisedRendererTests().app(profile)
        app.profile_engine.set(policy)
        app.calibration_path = ProfileStorage.profile_palette_file(DrawBot.PROFILES[profile][0])
        app.options = MethodType(DrawBot.DrawBotApp.options, app)
        app.closing = False
        app.root = SimpleNamespace()
        app.original = object()
        app.corners = []
        app.palette_ready = False
        app.request_preview = lambda: self.fail('Opening guidance must not request a preview.')
        return app

    def save_palette(self, app, state):
        save_calibration([(10, 10), (20, 10), (30, 10)],
            [(0, 0, 0), (255, 0, 0), (255, 255, 255)], app.calibration_path,
            profile_key=DrawBot.PROFILES[app.game.get()][0], state=state,
            verification={'method': 'local-regression', 'confidence': .95})

    def wizard_text(self, app):
        texts = []
        class NativeWidgetBoundary:
            def __init__(self, *args, **kwargs): pass
            def title(self, *args): pass
            def transient(self, *args): pass
            def configure(self, **kwargs): pass
            def pack(self, **kwargs): pass
            def destroy(self): pass
            def insert(self, position, text): texts.append(text)
        with ExitStack() as stack:
            stack.enter_context(patch('UiCompatibility.scoped_toplevel', new=NativeWidgetBoundary))
            stack.enter_context(patch('WorkspaceLayout.fit_window'))
            for name in ('CTkFrame', 'CTkLabel', 'CTkTextbox', 'CTkButton'):
                stack.enter_context(patch('customtkinter.' + name, new=NativeWidgetBoundary))
            DrawBot.DrawBotApp.show_beginner_setup_wizard(app)
        self.assertEqual(len(texts), 1)
        return texts[0]

    def test_actual_options_publish_missing_palette_warning_after_one_policy_resolution(self):
        original = ProfilePolish.apply_profile_polish
        for profile in ('Microsoft Paint', 'Skribbl.io', 'Other drawing app'):
            for policy in ('Auto', 'Manual settings'):
                with self.subTest(profile=profile, policy=policy):
                    app = self.app(profile, policy)
                    resolved = []
                    def observe(*args, **kwargs):
                        out, meta = original(*args, **kwargs)
                        resolved.append(deepcopy(meta))
                        return out, meta
                    with patch.object(ProfilePolish, 'apply_profile_polish', side_effect=observe):
                        options = app.options()
                    self.assertEqual(len(resolved), 1)
                    self.assertIn(options['calibration_state']['palette']['state'], ('estimated', 'unavailable'))
                    meta = options['profile_polish_meta']
                    self.assertIn(WARNING, meta['warnings'])
                    self.assertEqual(meta['warnings'].count(WARNING), 1)
                    self.assertEqual({key: value for key, value in meta.items() if key != 'warnings'},
                                     {key: value for key, value in resolved[0].items() if key != 'warnings'})
                    self.assertEqual(meta['applied'], policy == 'Auto')

    def test_actual_wizard_uses_current_nested_evidence_and_preserves_verified_control(self):
        app = self.app()
        self.assertIn(WARNING, self.wizard_text(app))
        self.save_palette(app, 'verified')
        self.assertNotIn(WARNING, self.wizard_text(app))
        self.assertIn('Browser One-Click is allowed only after read-only canvas/palette verification.',
                      self.wizard_text(app))

    def test_next_options_read_fresh_calibration_without_mutating_previous_metadata(self):
        app = self.app()
        before = app.options()
        frozen_before = deepcopy(before['profile_polish_meta'])
        self.assertIn(WARNING, frozen_before['warnings'])
        self.save_palette(app, 'verified')
        verified = app.options()
        self.assertEqual(verified['calibration_state']['palette']['state'], 'verified')
        self.assertNotIn(WARNING, verified['profile_polish_meta']['warnings'])
        self.assertEqual(before['profile_polish_meta'], frozen_before)
        app.calibration_path.unlink()
        self.assertIn(WARNING, app.options()['profile_polish_meta']['warnings'])
        self.assertNotIn(WARNING, verified['profile_polish_meta']['warnings'])

    def test_flat_legacy_priority_and_explicit_empty_evidence_remain_authoritative(self):
        for state in ({'palette_state': 'verified', 'palette': {'state': 'estimated'}},
                      {'state': 'calibrated', 'palette': {'state': 'unavailable'}}):
            with self.subTest(state=state):
                self.assertNotIn(WARNING, ProfilePolish.profile_release_warnings('Skribbl.io', state))
        self.assertIn(WARNING, ProfilePolish.profile_release_warnings('Skribbl.io',
            {'palette_state': 'estimated', 'state': 'verified', 'palette': {'state': 'verified'}}))
        options = {'profile_engine': 'Manual settings',
                   'calibration_state': {'palette': {'state': 'estimated'}}}
        original = deepcopy(options)
        _, explicit = ProfilePolish.apply_profile_polish('Skribbl.io', options, calibration_state={})
        _, inherited = ProfilePolish.apply_profile_polish('Skribbl.io', options)
        self.assertNotIn(WARNING, explicit['warnings'])
        self.assertIn(WARNING, inherited['warnings'])
        self.assertEqual(options, original)

    def test_nested_mapping_support_preserves_existing_non_warning_and_malformed_cases(self):
        for state in ('estimated', 'unavailable'):
            evidence = UserDict(palette=UserDict(state=state))
            self.assertIn(WARNING, ProfilePolish.profile_release_warnings('Other drawing app', evidence))
        for state in ('verified', 'calibrated', 'unknown'):
            evidence = {'palette': {'state': state}}
            self.assertNotIn(WARNING, ProfilePolish.profile_release_warnings('Other drawing app', evidence))
        for evidence in (None, [], {}, {'palette': None}, {'palette': []}, {'palette': 'estimated'}):
            with self.subTest(evidence=evidence):
                self.assertNotIn(WARNING, ProfilePolish.profile_release_warnings('Other drawing app', evidence))


if __name__ == '__main__':
    unittest.main()
