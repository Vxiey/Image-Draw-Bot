"""A cancelled area analysis cannot publish a partial target/setup selection.

The crop is an existing repository screenshot. The controller, both image
detectors, target adoption, Tcl variables, settings writer and plan invalidation
are real. Only the OS picker delivery/native window probe are replaced; Stop
is injected at those boundaries or in an actual detector cancellation poll.
"""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

import CanvasAnchorDetection
import DrawBot
import GarticEngineV2
from BrowserDrawingRegion import BrowserDrawingRegion
from ProfileIsolation import SETTING_NAMES
from SettingsValidation import ADDITIONAL_VARIABLES, BOOLEAN_SETTINGS


ASSET = Path(__file__).resolve().parent / 'assets' / 'image-draw-bot-app-screenshot.webp'
OLD_BOX = (20, 30, 220, 230)
NEW_BOX = (300, 100, 1020, 493)
OLD_TARGET = {'handle': 11, 'rect': (0, 0, 1280, 800),
              'client_rect': (0, 0, 1280, 800), 'dpi': 96}
NEW_TARGET = {'handle': 22, 'rect': (0, 0, 1600, 1000),
              'client_rect': (0, 0, 1600, 1000), 'dpi': 144}
STATE_FIELDS = (
    'corners', 'saved_area', 'canvas_anchor_detection', 'target_window',
    'target_client_rect', 'target_dpi', 'browser_drawing_region', 'plan',
    'small_test_passed', 'target_lock_passed', 'target_lock_fingerprint',
    'target_lock_signature', 'safety_preflight_passed', 'safety_preflight_signature',
    'safety_preflight_valid_until', 'dry_run_passed', 'dry_run_signature',
    'dry_run_valid_until', 'full_draw_armed_until', 'preview_generation',
)


class BoundaryAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = tk.Tcl()
        self.apps, self.variables, self.images = [], [], []
        self.messages = []
        self.stack.enter_context(patch.object(DrawBot, 'log_event', self.messages.append))
        self.addCleanup(self.release_owned_resources)
        with Image.open(ASSET) as existing:
            self.source = self.own(existing.copy())
        self.source_pixels = hashlib.sha256(self.source.tobytes()).hexdigest()

    def own(self, image):
        self.images.append(image)
        return image

    def variable(self, app, name, value):
        kind = tk.BooleanVar if type(value) is bool else tk.DoubleVar if type(value) is float else tk.StringVar
        variable = kind(master=self.root, value=value)
        setattr(app, name, variable)
        self.variables.append((app, name, variable))

    def application(self, profile='Gartic Phone'):
        app = SimpleNamespace(
            root=self.root, activity=None, closing=False, shutdown_complete=False,
            stop=threading.Event(), paused=threading.Event(), controls=[],
            original=self.source, plan={'preview': self.source, 'area': OLD_BOX},
            corners=[OLD_BOX[:2], OLD_BOX[2:]], saved_area=[OLD_BOX[:2], OLD_BOX[2:]],
            canvas_anchor_detection={'canvas_anchor_meta': {'triangle_count': 2}},
            target_window=(OLD_TARGET['handle'], OLD_TARGET['rect']),
            target_client_rect=OLD_TARGET['client_rect'], target_dpi=OLD_TARGET['dpi'],
            browser_drawing_region=None, color_session_cache={'verified-color': (10, 20, 30)},
            small_test_passed=True, palette_ready=True, full_draw_armed_until=0.,
            profile_change_in_progress=False, profile_change_after=None,
            pending_clear_drawing=None, capture_job=None, preview_after=None,
            preview_generation=7, needs_plan=False, recovery_checkpoint_after=None,
            settings_path=self.directory / f'settings-{len(self.apps)}.json',
        )
        self.apps.append(app)
        values = dict.fromkeys((*SETTING_NAMES, *ADDITIONAL_VARIABLES), '')
        values.update({name: False for name in BOOLEAN_SETTINGS})
        values.update({
            'game': profile, 'quality': 'Balanced', 'speed': 'Safe', 'precision': 'High',
            'mode': 'Dots', 'contrast': 1., 'brush_px': '2', 'max_seconds': '180',
            'paint_tool': 'Use current tool', 'preview_mode': 'Manual', 'ui_mode': 'Simple',
            'subject_focus': 'Off', 'preview_show_background': True, 'preview_show_fill': True,
            'preview_show_strokes': True, 'status': 'Ready with previous area',
            'summary': 'Previous plan is ready', 'draw_time_text': 'Previous estimate',
            'preview_diagnostics_text': 'Previous diagnostics', 'area_text': 'Previous area',
            'browser_auto_text': 'Previous browser setup', 'next_step': '', 'target_lock_text': '',
        })
        for name, value in values.items():
            self.variable(app, name, value)
        for name in ('area', 'capture_target', 'save_settings', '_mark_plan_stale',
                     '_schedule_recovery_checkpoint', '_maybe_auto_preview', '_auto_preview_enabled',
                     '_palette_preflight_ready', '_paint_tool_preflight_ready',
                     '_invalidate_target_lock', 'set_busy', 'show_previews'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        if profile == 'Gartic Phone':
            app.browser_drawing_region = BrowserDrawingRegion.capture('gartic-phone', OLD_TARGET, OLD_BOX)
        app.target_lock_fingerprint = DrawBot.DrawBotApp._build_target_lock_fingerprint(app)
        app.target_lock_signature = DrawBot.DrawBotApp._target_lock_signature_from(app.target_lock_fingerprint)
        app.target_lock_passed = True
        signature = DrawBot.DrawBotApp._current_safety_signature(app)
        app.safety_preflight_passed = app.dry_run_passed = True
        app.safety_preflight_signature = app.dry_run_signature = signature
        app.safety_preflight_valid_until = app.dry_run_valid_until = time.monotonic() + 3600
        self.assertTrue(app.save_settings())
        return app

    def release_owned_resources(self):
        for token in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(token)
        for image in self.images:
            image.close()
        while self.variables:
            app, name, variable = self.variables.pop()
            setattr(app, name, None)
            del variable
        for app in self.apps:
            app.root = None
        self.root = None

    def snapshot(self, app):
        return {
            'state': {name: getattr(app, name) for name in STATE_FIELDS},
            'cache': dict(app.color_session_cache),
            'settings': app.settings_path.read_bytes(),
            'feedback': {name: getattr(app, name).get() for name in
                         ('summary', 'draw_time_text', 'preview_diagnostics_text', 'area_text')},
        }

    def select(self, app, probe=None):
        self.crop = self.own(self.source.copy())
        failures = []

        def delivered(_owner, selected, failed, *, cancelled):
            self.assertFalse(cancelled())
            try:
                selected(NEW_BOX, self.crop)
            except Exception as error:
                failures.append(error)
                failed(str(error))

        with patch('RegionPicker.select_region', side_effect=delivered), \
                patch('TargetCapture.capture_target_metadata_isolated',
                      side_effect=probe or (lambda *_a, **_k: dict(NEW_TARGET))) as native:
            DrawBot.DrawBotApp.set_boundary(app)
        with self.assertRaises(ValueError):
            self.crop.getpixel((0, 0))
        self.assertEqual(hashlib.sha256(self.source.tobytes()).hexdigest(), self.source_pixels)
        return failures, native

    def assert_previous(self, app, before):
        changed = [name for name, value in before['state'].items()
                   if getattr(app, name) != value]
        self.assertEqual(changed, [], 'Cancelled selection changed the previous setup.')
        self.assertIs(app.plan, before['state']['plan'])
        self.assertEqual(app.color_session_cache, before['cache'])
        self.assertEqual(app.settings_path.read_bytes(), before['settings'])
        for name, value in before['feedback'].items():
            self.assertEqual(getattr(app, name).get(), value)
        self.assertIsNone(app.recovery_checkpoint_after)
        self.assertIsNone(app.capture_job)

    def test_stop_during_native_target_probe_cannot_commit_generic_selection(self):
        app = self.application('Other drawing app')
        before = self.snapshot(app)

        def stopped(*_args, **_kwargs):
            DrawBot.DrawBotApp._request_stop(app)
            return dict(NEW_TARGET)

        failures, native = self.select(app, stopped)
        self.assert_previous(app, before)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], InterruptedError)
        self.assertTrue(app.stop.is_set())
        self.assertIsNone(app.activity)
        native.assert_called_once()

    def test_stop_inside_real_gartic_analysis_restores_prior_target_and_region(self):
        app = self.application()
        before = self.snapshot(app)
        near_white = GarticEngineV2._near_white
        observed = []

        def stop_while_scanning(pixel):
            if not observed:
                observed.append(tuple(pixel))
                DrawBot.DrawBotApp._request_stop(app)
            return near_white(pixel)

        with patch.object(GarticEngineV2, '_near_white', side_effect=stop_while_scanning):
            failures, native = self.select(app)
        self.assertTrue(observed, 'The real Gartic detector must enter its pixel scan.')
        self.assert_previous(app, before)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], InterruptedError)
        native.assert_called_once()

    def test_stop_inside_real_anchor_analysis_prevents_native_probe_and_publication(self):
        app = self.application('Other drawing app')
        before = self.snapshot(app)
        detector = CanvasAnchorDetection.detect_canvas_anchors
        checks = []

        def stop_in_detector(image, **kwargs):
            cancelled = kwargs.pop('cancelled', lambda: False)

            def during_analysis():
                checks.append(None)
                if len(checks) == 2:
                    DrawBot.DrawBotApp._request_stop(app)
                return cancelled()

            return detector(image, cancelled=during_analysis, **kwargs)

        with patch.object(CanvasAnchorDetection, 'detect_canvas_anchors', side_effect=stop_in_detector):
            failures, native = self.select(app)
        self.assertGreaterEqual(len(checks), 2)
        self.assert_previous(app, before)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], InterruptedError)
        native.assert_not_called()

    def test_shutdown_during_native_probe_rejects_result_without_late_ui_feedback(self):
        app = self.application('Other drawing app')
        before = self.snapshot(app)
        old_status = app.status.get()

        def closing(*_args, **_kwargs):
            app.closing = True
            return dict(NEW_TARGET)

        failures, _native = self.select(app, closing)
        self.assert_previous(app, before)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], InterruptedError)
        self.assertEqual(app.status.get(), old_status)

    def test_failed_native_probe_retains_existing_setup_and_closes_delivered_crop(self):
        app = self.application()
        before = self.snapshot(app)

        def missing_target(*_args, **_kwargs):
            raise OSError('The selected target disappeared.')

        failures, _native = self.select(app, missing_target)
        self.assert_previous(app, before)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], OSError)
        self.assertIn('disappeared', app.status.get())

    def test_successful_selection_commits_settings_and_invalidates_previous_plan_and_safety(self):
        for profile in ('Other drawing app', 'Gartic Phone'):
            with self.subTest(profile=profile):
                app = self.application(profile)
                failures, native = self.select(app)
                self.assertEqual(failures, [])
                native.assert_called_once()
                self.assertEqual(app.corners, [NEW_BOX[:2], NEW_BOX[2:]])
                self.assertEqual(app.saved_area, app.corners)
                self.assertEqual(app.target_window, (NEW_TARGET['handle'], NEW_TARGET['rect']))
                self.assertEqual(app.target_dpi, NEW_TARGET['dpi'])
                self.assertEqual(json.loads(app.settings_path.read_text())['corners'],
                                 [list(NEW_BOX[:2]), list(NEW_BOX[2:])])
                self.assertIsNone(app.plan)
                self.assertEqual(app.color_session_cache, {})
                for name in ('small_test_passed', 'target_lock_passed',
                             'safety_preflight_passed', 'dry_run_passed'):
                    self.assertFalse(getattr(app, name))
                self.assertEqual(app.full_draw_armed_until, 0)
                self.assertIsNotNone(app.recovery_checkpoint_after)
                if profile == 'Gartic Phone':
                    self.assertEqual(app.browser_drawing_region.handle, NEW_TARGET['handle'])
                    self.assertIsNotNone(app.capture_job)
                self.assertIn('Drawing area saved', app.status.get())


if __name__ == '__main__':
    unittest.main()
