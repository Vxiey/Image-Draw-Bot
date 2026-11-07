"""Prepared Paint colors respect accepted settings and profile lifetimes."""
import ast
from contextlib import ExitStack
import inspect
import json
from pathlib import Path
import tempfile
import textwrap
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import Colors
import DrawBot
import ExactColorTools
import GameProfiles
import ProfileIsolation
import ProfilePortability
import ProfileStorage
import RealSpeedBudget
from CalibrationAnchors import make_anchor
from PictureCustomPalette import build_picture_palette
from PicturePalettePlanning import active_picture_palette
from test_v148_application_batch04_settings import Value
from test_v148_ui_batch07_renderer import close_images
from test_v148_ui_batch20_auto_preview import ScheduledRoot


def controller_values():
    """Use real constructor defaults, replacing only native variable allocation."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(DrawBot.DrawBotApp.__init__)))
    values = dict(ProfileIsolation.EXTRA_DEFAULTS)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and
                isinstance(node.targets[0], ast.Attribute) and
                isinstance(node.targets[0].value, ast.Name) and
                node.targets[0].value.id == 'self' and isinstance(node.value, ast.Call) and
                isinstance(node.value.func, ast.Attribute) and
                isinstance(node.value.func.value, ast.Name) and
                node.value.func.value.id == 'tk' and
                node.value.func.attr in ('StringVar', 'BooleanVar', 'DoubleVar', 'IntVar')):
            continue
        initializer = next((item.value for item in node.value.keywords if item.arg == 'value'),
                           ast.Constant(value=''))
        if isinstance(initializer, ast.Constant):
            values[node.targets[0].attr] = initializer.value
        elif isinstance(initializer, ast.Name):
            values[node.targets[0].attr] = getattr(DrawBot, initializer.id)
    return {name: Value(value) for name, value in values.items()}


class PicturePaletteWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.stack.enter_context(patch('RuntimePaths.source_dir', return_value=self.directory))
        self.stack.enter_context(patch.object(RealSpeedBudget, 'SPEED_FILE', self.directory / 'speed.json'))
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_refresh_start_buttons_text'))
        self.stack.enter_context(patch.dict(GameProfiles.PROFILES))
        self.stack.enter_context(patch.dict(GameProfiles.PROFILE_UI))
        colors = list(Colors.allColors)
        def restore_colors():
            Colors.allColors[:] = colors
            from PixelData import closest_color
            closest_color.cache_clear()
        self.addCleanup(restore_colors)
        self.images = []
        self.plans = []
        self.apps = []
        self.addCleanup(self.release)
        self.fallback = ((0, 0, 0), (255, 255, 255), (220, 0, 0), (128, 128, 128))
        self.rgb = ((32, 30, 29), (112, 115, 117), (203, 169, 146), (132, 34, 40))
        self.palette = {'version': 4, 'profile': 'microsoft-paint', 'state': 'verified',
            'verification': {'confidence': .99, 'source': 'fixture'},
            'colors': [{'name': str(index), 'position': [20 + index * 20, 30], 'rgb': list(rgb)}
                       for index, rgb in enumerate(self.fallback)]}

    def release(self):
        for app in self.apps:
            vars(app).clear()
        self.apps.clear()
        close_images(self.plans)
        close_images(self.images)

    def app(self):
        app = SimpleNamespace(**controller_values())
        self.apps.append(app)
        app.game.set('Microsoft Paint')
        app.root = ScheduledRoot()
        app.root.title = Mock()
        app.activity = None
        app.closing = False
        app.profile_change_in_progress = False
        app.profile_change_after = None
        app.profile_change_ticket = None
        app._active_profile_name = 'Microsoft Paint'
        app.color_session_cache = {}
        app.canvas_anchor_detection = None
        app.browser_drawing_region = None
        app.corners = []
        app.saved_area = None
        app.target_window = None
        app.plan = None
        app.pending_clear_drawing = None
        app.stop = threading.Event()
        app.mouse = Mock()
        app.settings_path = ProfileStorage.profile_settings_file('microsoft-paint')
        app.calibration_path = ProfileStorage.profile_palette_file('microsoft-paint')
        self.assertEqual(app.settings_path.parent, self.directory)
        self.assertEqual(ProfilePortability.profile_timing_file('microsoft-paint').parent, self.directory)
        app.calibration_path.write_text(json.dumps(self.palette), encoding='utf-8')
        ExactColorTools.save('microsoft-paint', {
            'OpenCustomColor': (10, 10), 'ConfirmColor': (20, 10),
            'RedField': (30, 10), 'GreenField': (40, 10), 'BlueField': (50, 10)},
            anchor=make_anchor((0, 0, 1000, 800)))
        self.assertEqual(ExactColorTools.file_for('microsoft-paint').parent, self.directory)
        for name in ('save_settings', 'read_settings', 'refresh_palette', '_apply_profile_change',
                     '_mark_plan_stale', '_maybe_auto_preview', '_auto_preview_enabled',
                     'options_changed', 'options', 'refresh_exact_color_status'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        for name in ('refresh_tool_calibration', 'refresh_app_tool_calibration', 'set_busy',
                     'show_previews', 'schedule_previews', '_schedule_recovery_checkpoint'):
            setattr(app, name, Mock())
        ProfileIsolation.capture_defaults(app)
        self.manual(app)
        app.original = Image.new('RGBA', (24, 16), 'white')
        image_draw = ImageDraw.Draw(app.original)
        for index, rgb in enumerate(self.rgb):
            image_draw.rectangle((index * 6, 0, index * 6 + 5, 15), fill=rgb + (255,))
        app.original.info['draw_studio_format'] = 'PNG'
        self.images.append(app.original)
        app.refresh_palette()
        self.assertTrue(app.palette_ready)
        self.assertEqual(tuple(tuple(c.RGB) for c in Colors.allColors), self.fallback)
        return app

    def manual(self, app):
        for name, value in dict(render_preset='Manual', profile_engine='Manual settings',
                render_style='Standard / pixel', draw_quality='Pixel Accurate', gpu_mode='CPU',
                cpu_workers='1', cpu_engine='Threads', resource_scheduler='Off',
                background_fill='Off', use_region_fill_engine=False, detail_zoom='Off',
                planning_resolution='Standard', paint_simple=False, paint_tool='Use current tool',
                brush_px='1', portrait_focus=False, custom_color_workflow='Calibrated palette',
                preview_mode='Manual', color_layers='Off', auto_clear_canvas=False).items():
            getattr(app, name).set(value)

    def prepare(self, app):
        palette = build_picture_palette(app.original, self.fallback, max_colors=4, fidelity='Faithful')
        self.assertEqual(set(palette.colors), set(self.rgb))
        payload = dict(profile_key='microsoft-paint', image_id=id(app.original),
                       colors=palette.colors, prepared_count=len(palette.colors))
        DrawBot.DrawBotApp._handle_event(app, 'picture_palette_complete', payload)
        self.assertEqual(active_picture_palette(app), palette.colors)
        self.assertEqual(app.custom_color_workflow.get(), 'Adaptive exact (recommended)')
        self.assertTrue(app.settings_path.is_file())
        return payload

    def plan(self, app):
        options = app.options()
        # Keep the actual public planner deterministic and local to this fixture.
        options['_execution_cost_calibration_override'] = {}
        plan = DrawBot.make_plan(app.original, app.original.size, options)
        self.plans.append(plan)
        return options, plan

    def assert_calibrated(self, app):
        options, plan = self.plan(app)
        self.assertEqual(options['custom_color_workflow'], 'Calibrated palette')
        self.assertNotIn('picture_palette_rgb', options)
        self.assertNotEqual(plan['options'].get('picture_palette_meta', {}).get('source'),
                            'prepared-picture-palette')
        self.assertTrue(set(plan['colors']).issubset(self.fallback))
        self.assertTrue(all(not selector.get('require_exact') for selector in plan['color_selectors']))
        return plan

    def test_manual_calibrated_selection_reaches_real_planner_with_and_without_rgb_controls(self):
        for available in (True, False):
            with self.subTest(exact_controls=available):
                app = self.app()
                payload = self.prepare(app)
                before = app.original.tobytes()
                app.custom_color_workflow.set('Calibrated palette')
                app.options_changed()
                if not available:
                    ExactColorTools.file_for('microsoft-paint').unlink()
                self.assert_calibrated(app)
                self.assertEqual(active_picture_palette(app), payload['colors'])
                self.assertTrue(app.save_settings())
                app.custom_color_workflow.set('Adaptive exact (recommended)')
                self.assertTrue(app.read_settings())
                self.assertEqual(app.custom_color_workflow.get(), 'Calibrated palette')
                self.assertEqual(app.original.tobytes(), before)
                self.assertEqual(app.original.info['draw_studio_format'], 'PNG')
                self.assertEqual(app.mouse.mock_calls, [])

    def test_prepared_completion_and_explicit_exact_workflows_keep_rgb_and_selected_policy(self):
        app = self.app()
        payload = self.prepare(app)
        for workflow in ('Adaptive exact (recommended)', 'Exact custom + palette fallback'):
            with self.subTest(workflow=workflow):
                app.custom_color_workflow.set(workflow)
                app.options_changed()
                options, plan = self.plan(app)
                self.assertEqual(options['custom_color_workflow'], workflow)
                self.assertEqual(tuple(plan['colors']), payload['colors'])
                self.assertEqual(tuple(item['rgb'] for item in plan['color_selectors']), payload['colors'])
                self.assertTrue(all(item['require_exact'] for item in plan['color_selectors']))
                self.assertEqual(plan['options']['picture_palette_meta']['source'], 'prepared-picture-palette')
        for field in ('paint_simple', 'outline'):
            with self.subTest(bypass=field):
                getattr(app, field).set(True)
                self.assertNotIn('picture_palette_rgb', app.options())
                self.assertEqual(active_picture_palette(app), payload['colors'])
                getattr(app, field).set(False)

    def test_auto_policy_still_promotes_calibrated_colors_when_rgb_controls_exist(self):
        app = self.app()
        self.prepare(app)
        app.custom_color_workflow.set('Calibrated palette')
        app.render_preset.set('Auto')
        app.profile_engine.set('Auto')
        app.options_changed()
        options, plan = self.plan(app)
        self.assertEqual(options['custom_color_workflow'], 'Adaptive exact (recommended)')
        self.assertTrue(plan['options']['exact_color_available'])
        self.assertTrue(all(item['require_exact'] for item in plan['color_selectors']))

    def test_accepted_profile_replace_and_reset_retire_prepared_state_without_replacing_image(self):
        for route in ('replace', 'reset'):
            with self.subTest(route=route):
                app = self.app()
                self.prepare(app)
                source = app.original
                before = source.tobytes()
                settings = {'render_preset': 'Manual', 'profile_engine': 'Manual settings',
                            'custom_color_workflow': 'Calibrated palette', 'paint_simple': False}
                package = ProfilePortability.build_package('Microsoft Paint', settings,
                                                            {'palette': self.palette})
                app.stop.set()
                if route == 'replace':
                    ProfilePortability.import_package_into_app(app, package, action='replace')
                    self.assertTrue(app.settings_path.is_file())
                    self.assertTrue(app.palette_ready)
                else:
                    ProfilePortability.reset_profile(app)
                    self.assertFalse(app.settings_path.exists())
                    self.assertFalse(app.calibration_path.exists())
                self.assertEqual(active_picture_palette(app), ())
                self.assertIsNone(getattr(app, 'picture_custom_palette_state', None))
                self.assertIs(app.original, source)
                self.assertEqual(source.tobytes(), before)
                self.assertTrue(app.stop.is_set())
                self.assertEqual(app.mouse.mock_calls, [])
                # Re-enter the actual manual palette flow after reset. Missing RGB
                # controls must not require the discarded previous preparation.
                self.manual(app)
                app.calibration_path.write_text(json.dumps(self.palette), encoding='utf-8')
                app.refresh_palette()
                self.assertFalse(ExactColorTools.custom_rgb_available('microsoft-paint'))
                self.assert_calibrated(app)

    def test_rejected_profile_apply_and_cancelled_or_foreign_completion_keep_current_state(self):
        app = self.app()
        self.prepare(app)
        state = app.picture_custom_palette_state
        DrawBot.DrawBotApp.change_profile(app)
        self.assertIs(app.picture_custom_palette_state, state)
        self.assertEqual(active_picture_palette(app), tuple(state['colors']))
        for reason in ('busy', 'closing', 'ticket', 'selection'):
            with self.subTest(reason=reason):
                app = self.app()
                self.prepare(app)
                state = app.picture_custom_palette_state
                if reason == 'busy': app.activity = 'draw'
                if reason == 'closing': app.closing = True
                if reason == 'ticket': app.profile_change_ticket = object()
                selected = 'Skribbl.io' if reason == 'selection' else 'Microsoft Paint'
                app._apply_profile_change(selected, **({'ticket': object()} if reason == 'ticket' else {}))
                self.assertIs(app.picture_custom_palette_state, state)
                self.assertEqual(active_picture_palette(app), tuple(state['colors']))
        app = self.app()
        payload = self.prepare(app)
        state = app.picture_custom_palette_state
        app.stop.set()
        DrawBot.DrawBotApp._handle_event(app, 'picture_palette_complete', {**payload, 'colors': ((1, 2, 3),)})
        self.assertIs(app.picture_custom_palette_state, state)
        app.stop.clear()
        DrawBot.DrawBotApp._handle_event(app, 'picture_palette_complete', {**payload, 'image_id': -1})
        self.assertIs(app.picture_custom_palette_state, state)


if __name__ == '__main__':
    unittest.main()
