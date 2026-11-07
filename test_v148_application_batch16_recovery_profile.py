"""Recovery publication belongs to applied settings during a deferred profile change."""
import json
from pathlib import Path
import queue
import tempfile
from types import MethodType
import unittest
from unittest.mock import patch

import DrawBot
import SessionRecovery as recovery
import test_v148_ui_batch16_plan_status as plan_status


PROFILE_A = 'Microsoft Paint'
PROFILE_B = 'Other drawing app'
AREA_A = [[100, 120], [180, 180]]
AREA_B = [[200, 220], [280, 280]]


class RecoveryProfileTests(plan_status.PlanStatusFixture):
    def setUp(self):
        super().setUp()
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.profiles = self.directory / 'profiles'
        self.profiles.mkdir()
        root = self.directory / 'recovery'
        for name, path in {'RECOVERY_DIR': root, 'STATE_FILE': root / 'state.json',
                           'IMAGE_FILE': root / 'last-image.png',
                           'RENDER_FILE': root / 'render.json'}.items():
            self.stack.enter_context(patch.object(recovery, name, path))
        self.stack.enter_context(patch('DrawBot.profile_settings_file',
            side_effect=lambda key: self.profiles / f'{key}.json'))
        self.stack.enter_context(patch('DrawBot.profile_palette_file',
            side_effect=lambda key: self.profiles / f'{key}-palette.json'))
        self.apps = []
        self.addCleanup(self.stop_jobs)

    def stop_jobs(self):
        for app in self.apps:
            job = getattr(app, '_recovery_image_job', None)
            if job is not None:
                job.cancel()
                self.assertTrue(job.wait_idle(5), 'Recovery encoder did not stop')

    def application(self):
        app = super().app()
        self.apps.append(app)
        app.events = queue.Queue()
        app.quality.set('High detail')
        app.contrast.set(1.25)
        app.brush_px.set('4')
        app.subject_focus.set('Subject first')
        app.subject_region = (.1, .2, .8, .9)
        app.saved_area = list(map(tuple, AREA_A))
        app.settings_path = DrawBot.profile_settings_file(DrawBot.PROFILES[PROFILE_A][0])
        app.calibration_path = DrawBot.profile_palette_file(DrawBot.PROFILES[PROFILE_A][0])
        for name in ('save_settings', 'read_settings', '_apply_profile_change',
                     '_schedule_recovery_checkpoint'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        target = DrawBot.profile_settings_file(DrawBot.PROFILES[PROFILE_B][0])
        target.write_text(json.dumps(dict(settings_schema=2, quality='Quick sketch',
            contrast=.75, brush_px='2', corners=AREA_B,
            profile_extras={'subject_focus': 'Off'})), encoding='utf-8')
        return app

    def select_pending_profile(self, app):
        app.game.set(PROFILE_B)
        DrawBot.DrawBotApp.change_profile(app)
        self.assertEqual(app._active_profile_name, PROFILE_A)
        self.assertEqual(app.contrast.get(), 1.25)
        self.assertIsNotNone(app.profile_change_after)
        # The outgoing settings are really saved, and the incoming profile is
        # only a selected menu value until its actual after_idle callback runs.
        outgoing = json.loads(app.settings_path.read_text(encoding='utf-8'))
        self.assertEqual(outgoing['contrast'], 1.25)
        return app.profile_change_after

    def apply_pending_profile(self, app, token):
        app.root.run(token)
        self.assertEqual(app._active_profile_name, PROFILE_B)
        self.assertEqual(app.game.get(), PROFILE_B)
        self.assertEqual(app.contrast.get(), .75)
        self.assertEqual(app.quality.get(), 'Quick sketch')
        self.assertIsNone(app.profile_change_after)

    def assert_snapshot(self, app, profile):
        state = recovery.load_snapshot()
        self.assertIsNotNone(state)
        if profile == PROFILE_A:
            self.assertEqual((state['options']['quality'], state['options']['contrast'],
                              state['options']['brush_px']), ('High detail', 1.25, '4'))
            self.assertEqual(state['saved_area'], AREA_A)
        else:
            self.assertEqual((state['options']['quality'], state['options']['contrast'],
                              state['options']['brush_px']), ('Quick sketch', .75, '2'))
            self.assertEqual(state['saved_area'], AREA_B)
        with recovery.load_cached_image(state['image_sha256']) as image:
            self.assertEqual((image.mode, image.size, image.tobytes()),
                             (app.original.mode, app.original.size, app.original.tobytes()))
        self.assertEqual(state['profile'], profile)
        return state

    def complete_image_job(self, app):
        job = app._recovery_image_job
        self.assertTrue(job.wait_idle(5))
        kind, value = app.events.get(timeout=3)
        self.assertEqual(kind, 'recovery_image_prepared')
        self.assertIs(value, job)
        DrawBot.DrawBotApp._handle_event(app, kind, value)
        self.assertIsNone(app._recovery_image_job)
        self.assertEqual(list(recovery.RECOVERY_DIR.glob('.recovery-pending-*')), [])

    def test_due_timer_before_profile_callback_keeps_the_applied_profile(self):
        app = self.application()
        self.assertTrue(DrawBot.DrawBotApp._save_recovery_checkpoint(app, include_image=True))
        app._schedule_recovery_checkpoint(delay=20)
        timer = app.recovery_checkpoint_after
        profile_callback = self.select_pending_profile(app)
        app.root.run(timer)
        self.assert_snapshot(app, PROFILE_A)
        self.assertIn(profile_callback, app.root.jobs)
        self.apply_pending_profile(app, profile_callback)
        app.root.run(app.recovery_checkpoint_after)
        self.assert_snapshot(app, PROFILE_B)

    def test_ready_png_before_profile_callback_uses_the_applied_profile(self):
        app = self.application()
        self.assertTrue(DrawBot.DrawBotApp._queue_recovery_checkpoint(app, include_image=True))
        self.assertTrue(app._recovery_image_job.wait_idle(5))
        self.assertFalse(recovery.STATE_FILE.exists())
        profile_callback = self.select_pending_profile(app)
        with patch.object(recovery, '_store_image', side_effect=AssertionError('Prepared PNG must be reused')):
            self.complete_image_job(app)
            self.assert_snapshot(app, PROFILE_A)
            self.apply_pending_profile(app, profile_callback)
            app.root.run(app.recovery_checkpoint_after)
            self.assert_snapshot(app, PROFILE_B)

    def test_ready_png_after_profile_callback_captures_the_new_applied_settings(self):
        app = self.application()
        self.assertTrue(DrawBot.DrawBotApp._queue_recovery_checkpoint(app, include_image=True))
        self.assertTrue(app._recovery_image_job.wait_idle(5))
        profile_callback = self.select_pending_profile(app)
        self.apply_pending_profile(app, profile_callback)
        with patch.object(recovery, '_store_image', side_effect=AssertionError('Prepared PNG must be reused')):
            self.complete_image_job(app)
        self.assert_snapshot(app, PROFILE_B)
        self.assertIs(app._recovery_source_ref(), app.original)


if __name__ == '__main__':
    unittest.main()
