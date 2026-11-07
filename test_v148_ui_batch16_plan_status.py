"""Visible plan feedback belongs to the accepted source/setup, not old work."""
import ast
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
from types import MethodType, SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import customtkinter as ctk

import DrawBot
import StudioUI
from ProfileIsolation import SETTING_NAMES, capture_defaults
from SettingsValidation import ADDITIONAL_VARIABLES
from test_pixel_accurate_v1086 import opts
from test_v148_application_batch04_settings import Value
from test_v148_application_batch14_browser_start import ScheduledRoot
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_ui_batch09_readouts import actual_live_readouts


class BoundReadout:
    """Native allocation boundary; text still follows a real Tcl variable."""
    def __init__(self, _parent, **options):
        self.variable = options['textvariable']

    def visible_text(self):
        return self.variable.get()


def actual_diagnostic_readout(parent, app):
    tree = ast.parse(Path(StudioUI.__file__).read_text(encoding='utf-8'))
    build = next(node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == 'build_ui')
    factory = next(node for node in build.body
                   if isinstance(node, ast.FunctionDef) and node.name == 'label')
    call = next(node for node in ast.walk(build)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'label' and any(
                    keyword.arg == 'var' and isinstance(keyword.value, ast.Attribute)
                    and keyword.value.attr == 'preview_diagnostics_text'
                    for keyword in node.keywords))
    statement = ast.Assign(targets=[ast.Name(id='diagnostic', ctx=ast.Store())], value=call)
    module = ast.fix_missing_locations(ast.Module(body=[factory, statement], type_ignores=[]))
    namespace = dict(vars(StudioUI), a=app, workspace_center=parent)
    exec(compile(module, StudioUI.__file__, 'exec'), namespace)
    return namespace['diagnostic']


class PlanStatusFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tcl = tk.Tcl()
        self.images = []
        self.plans = []
        self.addCleanup(self.close_images)
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('SessionRecovery.clear_render_progress'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_close_smart_drop_overlay'))

    def close_images(self):
        for plan in self.plans:
            close_plan(plan, None)
        for image in self.images:
            image.close()

    def image(self, color):
        image = Image.new('RGBA', (8, 6), color)
        self.images.append(image)
        return image

    def app(self):
        app = SimpleNamespace(**{name: Value('') for name in (*SETTING_NAMES, *ADDITIONAL_VARIABLES)})
        app.root = ScheduledRoot()
        app.root.deiconify = Mock()
        app.root.title = Mock()
        app.activity = None
        app.closing = False
        app.shutdown_complete = False
        app.pending_clear_drawing = None
        app.profile_change_after = None
        app.profile_change_in_progress = False
        app.preview_generation = 4
        app.preview_mode = Value('Manual')
        app.plan = None
        app.original = self.image('red')
        app.background_removal_original = None
        app.background_removal_meta = None
        app.upscale_original = None
        app.stop = threading.Event()
        app.paused = threading.Event()
        app.worker = None
        app.progress = {'value': 0}
        app.corners = [(10, 20), (90, 80)]
        app.saved_area = [(100, 120), (180, 180)]
        app.target_window = (11, (0, 0, 200, 200))
        app.target_client_rect = (0, 0, 200, 200)
        app.target_dpi = 96
        app.canvas_anchor_detection = {'old': 'anchors'}
        app.color_session_cache = {}
        app.game = Value('Microsoft Paint')
        app._active_profile_name = 'Microsoft Paint'
        app.paint_simple = Value(False)
        app.outline = Value(False)
        app.auto_clear_canvas = Value(False)
        app.browser_one_click_enabled = Value(False)
        app.small_test_passed = True
        app.target_lock_passed = False
        app.full_draw_armed_until = 0.
        for name in ('status', 'summary', 'area_text', 'file_label', 'url', 'profile_hint',
                     'color_plan_text', 'draw_time_text', 'draw_live_time_text',
                     'total_draw_time_text', 'preview_diagnostics_text'):
            setattr(app, name, tk.StringVar(self.tcl, value=''))
        for name in ('show_previews', 'schedule_previews', '_schedule_recovery_checkpoint',
                     'refresh_palette', 'refresh_tool_calibration', 'refresh_app_tool_calibration',
                     'refresh_exact_color_status', 'save_settings', 'read_settings'):
            setattr(app, name, Mock())
        app.set_busy = Mock(side_effect=lambda activity: setattr(app, 'activity', activity))
        for name in ('_mark_plan_stale', '_maybe_auto_preview', '_auto_preview_enabled',
                     '_sync_mobile_preview', 'cancel', 'area', 'capture_target'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        with patch.object(ctk, 'CTkLabel', BoundReadout):
            app.readouts = actual_live_readouts(object(), app)
            app.readouts['diagnostic'] = actual_diagnostic_readout(object(), app)
        capture_defaults(app)
        return app

    def adopt_plan(self, app):
        plan = DrawBot.make_plan(app.original, (40, 30), opts(
            profile_name='Microsoft Paint', profile_key='microsoft-paint',
            paint_current_color=True, render_preset='Manual',
            unlimited_time=True, time_budget_mode='Unlimited', cpu_workers='1',
            detail_zoom='Off', _execution_cost_calibration_override={}))
        self.plans.append(plan)
        plan['preview_generation'] = app.preview_generation
        DrawBot.DrawBotApp._handle_event(app, 'planned', plan)
        self.assertIs(app.plan, plan)
        self.assertNotIn('appears after Build preview', app.draw_time_text.get())
        self.assertNotIn('appear after Build preview', app.preview_diagnostics_text.get())
        DrawBot.DrawBotApp._handle_event(app, 'draw_time_actual', {'seconds': 37.2})
        return plan

    def assert_invalid_plan_feedback(self, app):
        self.assertIsNone(app.plan)
        self.assertEqual(app.readouts['draw_time_side'].visible_text(),
                         'Estimated draw time appears after Build preview.')
        self.assertEqual(app.readouts['diagnostic'].visible_text(),
                         'Preview diagnostics appear after Build preview.')

    @staticmethod
    def runtime_text(app):
        return (app.draw_live_time_text.get(), app.total_draw_time_text.get())


class PlanFeedbackTests(PlanStatusFixture):
    def test_settings_invalidation_clears_visible_projection_not_completed_actual_time(self):
        app = self.app()
        self.adopt_plan(app)
        actual = self.runtime_text(app)
        DrawBot.DrawBotApp.options_changed(app)
        self.assert_invalid_plan_feedback(app)
        self.assertEqual(self.runtime_text(app), actual)
        self.assertFalse(app.root.jobs, 'Manual mode must not queue a replacement preview')

    def test_file_and_bitmap_adoption_drop_the_previous_sources_eta_and_diagnostics(self):
        for kind in ('loaded', 'pasted'):
            with self.subTest(kind=kind):
                app = self.app()
                self.adopt_plan(app)
                source = self.image('blue')
                payload = (source, 'blue.png', None) if kind == 'loaded' else (source, None)
                DrawBot.DrawBotApp._handle_event(app, kind, payload)
                self.assertIs(app.original, source)
                self.assert_invalid_plan_feedback(app)
                self.assertFalse(app.root.jobs)
                if kind == 'loaded':
                    self.assertEqual(self.runtime_text(app),
                        ('Drawing timer: starts when drawing begins.', 'Total draw time: —'))

    def test_background_undo_invalidates_feedback_for_the_modified_source(self):
        app = self.app()
        self.adopt_plan(app)
        previous = self.image('green')
        app.background_removal_original = previous
        self.assertTrue(DrawBot.DrawBotApp.undo_background_removal(app))
        self.images.append(app.original)
        self.assertEqual(app.original.tobytes(), previous.tobytes())
        self.assert_invalid_plan_feedback(app)

    def test_profile_application_resets_current_plan_feedback_without_resetting_elapsed_time(self):
        app = self.app()
        self.adopt_plan(app)
        actual = self.runtime_text(app)
        app.game.set('Other drawing app')
        DrawBot.DrawBotApp._apply_profile_change(app, 'Other drawing app')
        self.assertEqual(app._active_profile_name, 'Other drawing app')
        self.assert_invalid_plan_feedback(app)
        self.assertEqual(self.runtime_text(app), actual)

    def test_clear_cached_drawing_invalidates_plan_feedback_and_retains_source_and_actual(self):
        app = self.app()
        self.adopt_plan(app)
        original, actual = app.original, self.runtime_text(app)
        with patch('SessionRecovery.clear_snapshot'), \
                patch('SessionRecovery.STATE_FILE') as state, \
                patch('SessionRecovery.RENDER_FILE') as render, \
                patch('SessionRecovery.IMAGE_FILE') as image:
            for path in (state, render, image):
                path.exists.return_value = False
            DrawBot.DrawBotApp.clear_cached_drawing(app)
        self.assertIs(app.original, original)
        self.assert_invalid_plan_feedback(app)
        self.assertEqual(self.runtime_text(app), actual)

    def test_active_execution_timer_is_not_a_plan_projection_to_clear(self):
        app = self.app()
        self.adopt_plan(app)
        app.activity = 'draw'
        DrawBot.DrawBotApp._handle_event(app, 'draw_timer', dict(
            state='paused', elapsed_seconds=125., remaining_seconds=3., predicted_total_seconds=128.))
        live = self.runtime_text(app)
        plan = app.plan
        DrawBot.DrawBotApp.options_changed(app)
        self.assertIs(app.plan, plan)
        self.assertEqual(self.runtime_text(app), live)
        # An explicit invalidation from another setup path clears only the
        # plan-derived fields; runtime status still belongs to the executor.
        app._mark_plan_stale('A plan has been invalidated')
        self.assert_invalid_plan_feedback(app)
        self.assertEqual(self.runtime_text(app), live)

    def test_noop_edit_retains_accepted_plan_and_all_readouts(self):
        app = self.app()
        plan = self.adopt_plan(app)
        before = {key: readout.visible_text() for key, readout in app.readouts.items()}
        result = self.image('red')
        DrawBot.DrawBotApp._handle_event(app, 'background_removed', SimpleNamespace(
            image=result, metadata={'no_op_reason': 'No removable background found'}))
        self.assertIs(app.plan, plan)
        self.assertEqual({key: readout.visible_text() for key, readout in app.readouts.items()}, before)
        with self.assertRaises(ValueError):
            result.getpixel((0, 0))

    def test_next_accepted_real_plan_repopulates_the_same_bound_readouts(self):
        app = self.app()
        self.adopt_plan(app)
        widgets = dict(app.readouts)
        DrawBot.DrawBotApp.options_changed(app)
        self.assert_invalid_plan_feedback(app)
        self.adopt_plan(app)
        self.assertEqual(app.readouts, widgets)
        self.assertIn('draw time', app.readouts['draw_time_side'].visible_text().lower())
        self.assertIn('Accuracy', app.readouts['diagnostic'].visible_text())


class ReuseAreaTransactionTests(PlanStatusFixture):
    @staticmethod
    def geometry(app):
        return (app.corners, app.canvas_anchor_detection, app.target_window,
                app.target_client_rect, app.target_dpi)

    def test_failed_capture_restores_previous_geometry_plan_and_visible_feedback(self):
        app = self.app()
        plan = self.adopt_plan(app)
        app.area_text.set('✓ 80 × 60 px')
        before = self.geometry(app)
        feedback = (app.area_text.get(), app.draw_time_text.get(), app.preview_diagnostics_text.get())

        def failed_capture():
            app.target_window = (99, (100, 100, 300, 300))
            app.target_client_rect = (101, 101, 299, 299)
            app.target_dpi = 144
            app.canvas_anchor_detection = None
            raise OSError('Target became unavailable')

        app.capture_target = failed_capture
        DrawBot.DrawBotApp.reuse_area(app)
        self.assertEqual(self.geometry(app), before)
        self.assertIs(app.plan, plan)
        self.assertEqual((app.area_text.get(), app.draw_time_text.get(), app.preview_diagnostics_text.get()), feedback)
        self.assertIn('Target became unavailable', app.status.get())
        app.set_busy.assert_not_called()
        self.assertFalse(app.root.jobs)

    def test_too_small_saved_area_preserves_existing_selection_before_native_capture(self):
        app = self.app()
        plan = self.adopt_plan(app)
        app.saved_area = [(10, 10), (15, 15)]
        before = self.geometry(app)
        with patch('TargetCapture.capture_target_metadata_isolated') as capture:
            DrawBot.DrawBotApp.reuse_area(app)
        capture.assert_not_called()
        self.assertEqual(self.geometry(app), before)
        self.assertIs(app.plan, plan)
        self.assertIn('too small', app.status.get())

    def test_successful_restore_commits_the_real_capture_then_invalidates_the_old_plan(self):
        from AnchorTransform import rebase_canvas_area
        from CanvasAnchorDetection import detect_canvas_anchors

        app = self.app()
        self.adopt_plan(app)
        actual = self.runtime_text(app)
        # Startup restores the saved area and its normalized anchors together.
        # Reuse must retain this matching geometry, not discard valid anchors.
        with Image.new('RGB', (80, 60), 'white') as screenshot:
            detected = detect_canvas_anchors(screenshot).as_options()
        with tempfile.TemporaryDirectory() as directory:
            app.settings_path = Path(directory) / 'paint.json'
            app.settings_path.write_text(json.dumps(dict(settings_schema=2,
                corners=[[100, 120], [180, 180]], canvas_anchor_detection=detected)), encoding='utf-8')
            app.saved_area = app.canvas_anchor_detection = None
            self.assertTrue(DrawBot.DrawBotApp.read_settings(app))
        anchors = app.canvas_anchor_detection
        meta = {'handle': 99, 'rect': (100, 100, 300, 300),
                'client_rect': (100, 100, 300, 300), 'dpi': 144}
        with patch('TargetCapture.capture_target_metadata_isolated', return_value=meta) as capture:
            DrawBot.DrawBotApp.reuse_area(app)
        self.assertEqual(capture.call_args.args[0], (100, 120, 80, 60))
        self.assertEqual(tuple(app.corners), tuple(map(tuple, app.saved_area)))
        self.assertIs(app.canvas_anchor_detection, anchors)
        self.assertEqual(app.target_window, (99, meta['rect']))
        self.assertEqual(app.target_client_rect, meta['client_rect'])
        self.assertEqual(app.target_dpi, 144)
        rebased, transform = rebase_canvas_area(app.area(), app.target_client_rect,
            (110, 110, 310, 310), app.canvas_anchor_detection)
        self.assertEqual(rebased, (110, 130, 80, 60))
        self.assertEqual(transform.method, 'anchors+corners')
        self.assertEqual(transform.used_anchors, 4)
        self.assert_invalid_plan_feedback(app)
        self.assertEqual(self.runtime_text(app), actual)

    def test_busy_closing_or_pending_profile_cannot_restore_an_area_into_another_context(self):
        for field, value in (('activity', 'draw'), ('closing', True),
                             ('profile_change_after', 'queued'), ('pending_clear_drawing', False)):
            with self.subTest(field=field):
                app = self.app()
                before = self.geometry(app)
                setattr(app, field, value)
                meta = {'handle': 99, 'rect': (100, 100, 300, 300),
                        'client_rect': (100, 100, 300, 300), 'dpi': 144}
                with patch('TargetCapture.capture_target_metadata_isolated', return_value=meta) as capture:
                    DrawBot.DrawBotApp.reuse_area(app)
                capture.assert_not_called()
                self.assertEqual(self.geometry(app), before)
                app.set_busy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
