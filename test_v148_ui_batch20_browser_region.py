"""A selected browser subregion remains the physical bound through live setup."""
from contextlib import ExitStack
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image, ImageDraw

import DrawBot
from BrowserDrawingRegion import BrowserDrawingRegion
import test_browser_auto_calibration_v1070 as browser_fixture
from test_drawbot import Mouse
from test_pixel_accurate_v1086 import opts
from test_v148_application_batch04_settings import Value
from test_v148_ui_batch16_plan_status import PlanStatusFixture
from test_v148_ui_batch20_auto_preview import ScheduledRoot
from test_v148_application_batch05_overlay import Overlay


META = {'handle': 123, 'rect': (90, 170, 1710, 1110),
        'client_rect': (100, 200, 1700, 1100), 'dpi': 96}
FULL = (580, 490, 1512, 1012)
SELECTED = (700, 600, 820, 690)
CLOSE_OVERLAY = DrawBot.DrawBotApp._close_smart_drop_overlay


class ImmediateStopEvent(threading.Event):
    def wait(self, timeout=None):
        return self.is_set()


class HostCanvasMouse(Mouse):
    """Only native input is replaced; paint physical round-brush footprints.

    Fill and Clear deliberately affect the entire host canvas. Thus a surviving
    bucket/global-clear action cannot hide behind an in-bounds pointer seed.
    """
    def __init__(self, surface, brush=3, controls=None):
        super().__init__()
        self.surface = surface
        self.brush = brush
        self.controls = dict(controls or {})
        self.tool = 'Brush'
        self.path = []
        self.painted = []
        self.selected_tools = []

    def move(self, x, y):
        super().move(x, y)
        if self.held:
            self.path.append(self.position)

    def press(self):
        super().press()
        self.path = [self.position]

    def release(self):
        if self.held:
            self._paint(self.path)
        self.path = []
        super().release()

    def click(self):
        super().click()
        self._paint([self.position])

    def _paint(self, path):
        if not path:
            return
        if len(path) == 1 and path[0] in self.controls:
            self.tool = self.controls[path[0]]
            self.selected_tools.append(self.tool)
            if self.tool == 'Clear':
                self.surface.paste((255, 255, 255), (0, 0, *self.surface.size))
            return
        if not any(FULL[0] <= x < FULL[2] and FULL[1] <= y < FULL[3] for x, y in path):
            return  # Palette/tool UI is outside the physical drawing canvas.
        if self.tool == 'Fill':
            self.surface.paste((0, 0, 0), (0, 0, *self.surface.size))
            return
        points = [(x - FULL[0], y - FULL[1]) for x, y in path]
        draw = ImageDraw.Draw(self.surface)
        color = (255, 255, 255) if self.tool == 'Eraser' else (0, 0, 0)
        if len(points) > 1:
            draw.line(points, fill=color, width=self.brush)
        before, after = (self.brush - 1) // 2, self.brush // 2
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - before, y - before, x + after, y + after), fill=color)
        self.painted.append(tuple(path))


class BrowserRegionFlowTests(PlanStatusFixture):
    def setUp(self):
        super().setUp()
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.meta = dict(META)
        self.selection = SELECTED
        self.shot = browser_fixture.BrowserAutoCalibrationTests._gartic_image()
        self.images.append(self.shot)
        self.original_palette = list(DrawBot.allColors)
        self.addCleanup(self.restore_palette)
        self.monitor = Mock()
        self.monitor.rectangle.side_effect = lambda handle: self.meta['rect']
        self.monitor.client_rectangle.side_effect = lambda handle: self.meta['client_rect']
        self.monitor.dpi.side_effect = lambda handle: self.meta['dpi']
        self.monitor.activate.return_value = True
        self.stack.enter_context(patch('RegionPicker.select_region', side_effect=self.pick))
        self.stack.enter_context(patch('TargetCapture.capture_target_metadata_isolated',
                                       side_effect=lambda *a, **kw: dict(self.meta)))
        self.stack.enter_context(patch('TargetCapture.probe_handle_isolated',
                                       side_effect=lambda *a, **kw: dict(self.meta)))
        self.stack.enter_context(patch('ScreenGuard.WindowMonitor', return_value=self.monitor))
        self.stack.enter_context(patch('ScreenGuard._grab_rgb', side_effect=lambda *a, **kw: self.shot.copy()))
        self.stack.enter_context(patch('PIL.ImageGrab.grab', side_effect=lambda *a, **kw: self.shot.copy()))
        self.stack.enter_context(patch('LayoutFingerprintV2.profile_layout_cache_file',
                                       return_value=self.directory / 'layout.json'))
        self.stack.enter_context(patch('AppTools.tool_file', return_value=self.directory / 'tools.json'))
        self.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.stack.enter_context(patch.object(DrawBot.DrawBotApp, '_schedule_poll'))
        self.stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
        for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                     'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                     'CorrectionHistory.record_correction_history', 'SessionRecovery.save_render_progress'):
            self.stack.enter_context(patch(name, return_value={}))
        self.stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))

    def restore_palette(self):
        DrawBot.allColors[:] = self.original_palette
        DrawBot.closest_color.cache_clear()

    def pick(self, root, selected, failed, *, cancelled):
        self.assertFalse(cancelled())
        l, t, r, b = self.selection
        x, y = self.meta['client_rect'][:2]
        selected(self.selection, self.shot.crop((l - x, t - y, r - x, b - y)))

    def app(self):
        app = super().app()
        app.root = ScheduledRoot()
        app.root.lift = Mock()
        app.root.title = Mock()
        app.root.iconify = Mock()
        app.events = queue.Queue()
        app.mouse = Mouse()
        app.keyboard = None
        app.stop = ImmediateStopEvent()
        app.game.set('Gartic Phone')
        app._active_profile_name = 'Gartic Phone'
        app.corners = []
        app.target_window = None
        app.browser_drawing_region = None
        app.calibration_path = self.directory / 'palette.json'
        app.refresh_runtime_safety_ui = Mock()
        app.refresh_correction_review_ui = Mock()
        app.needs_plan = False
        app.preview_after = None
        app.palette_ready = False
        app._palette_preflight_ready = lambda: app.palette_ready
        app._paint_tool_preflight_ready = lambda: True
        for name in ('palette_text', 'browser_one_click_text', 'browser_auto_text', 'one_click_setup_text'):
            setattr(app, name, Value(''))
        for name in ('begin_worker', '_handle_event', 'capture_target', 'refresh_palette',
                     'auto_calibrate_browser_profile', '_invalidate_target_lock',
                     '_refresh_target_for_draw', '_apply_profile_change', 'load_source'):
            setattr(app, name, MethodType(getattr(DrawBot.DrawBotApp, name), app))
        app.options = lambda: opts(
            profile_name='Gartic Phone', profile_key='gartic-phone',
            render_preset='Manual', auto_engine_resolved=True, draw_quality='High likeness',
            unlimited_time=True, time_budget_mode='Unlimited', cpu_workers='1',
            planning_watchdog='Off', detail_zoom='Off', brush_px=3,
            strict_color_verification=False, adaptive_color_verification=False,
            visual_verification_enabled=False, visual_verification_resolved='Off',
            stroke_delivery_verification='Off', canvas_edge_verification='Off',
            _execution_cost_calibration_override={})
        return app

    def events(self, app):
        worker = app.worker
        self.assertIsInstance(worker, threading.Thread)
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), 'Real worker exceeded the bounded fixture')
        result = []
        while not app.events.empty():
            event = app.events.get_nowait()
            result.append(event)
            if event[0] == 'planned':
                self.plans.append(event[1])
            elif event[0] == 'loaded':
                self.images.append(event[1][0])
        return result

    def deliver(self, app, events):
        for kind, value in events:
            DrawBot.DrawBotApp._handle_event(app, kind, value)
        self.assertNotIn('UI event error contained:', app.status.get())

    def select(self, app, *, calibrate=True):
        DrawBot.DrawBotApp.set_boundary(app)
        self.assertEqual(app.corners, [self.selection[:2], self.selection[2:]])
        self.assertIsInstance(app.browser_drawing_region, BrowserDrawingRegion)
        self.assertIsNone(app.browser_drawing_region.verified_canvas)
        if not calibrate:
            return
        token = app.capture_job
        self.assertEqual(app.root.jobs[token][0], 450)
        app.root.run(token)
        events = self.events(app)
        self.assertEqual([kind for kind, _ in events], ['browser_auto_calibration_complete', 'done'])
        self.deliver(app, events)
        return events[0][1]

    def assert_selected(self, app, box=SELECTED):
        self.assertEqual(app.corners, [box[:2], box[2:]])
        self.assertEqual(app.saved_area, app.corners)

    def calibrate_tools(self, names):
        from AppTools import save_calibration
        from CalibrationAnchors import make_anchor
        tools = {name: (330 + index * 30, 240) for index, name in enumerate(names)}
        save_calibration('gartic-phone', tools, anchor=make_anchor(META['client_rect']))
        return {point: name for name, point in tools.items()}

    def drawing(self, app, *, clear=False):
        options = app.options
        app.options = lambda: dict(options(), background_fill='Conservative',
            use_region_fill_engine=True, fill_engine='Auto', auto_clear_canvas=clear)
        surface = Image.new('RGB', (FULL[2] - FULL[0], FULL[3] - FULL[1]), (77, 131, 201))
        self.images.append(surface)
        controls = self.calibrate_tools(('Brush', 'Fill', 'Eraser', 'Clear'))
        mouse = HostCanvasMouse(surface, controls=controls)
        app.mouse = mouse
        source = Image.new('RGBA', (32, 24), 'white')
        ImageDraw.Draw(source).rectangle((5, 4, 26, 19), fill='black')
        self.images.append(source)
        app.original = source
        return mouse

    def execute_actual(self, app, *, start=None):
        import BrowserBrushSize
        import BrowserToolLayout
        import GarticOpacity
        actual_execute = DrawBot.execute_plan
        with ExitStack() as local:
            # OS input/window verification is the only executor boundary. The
            # final per-path CanvasGuard, plan preparation and native sequence
            # remain the actual public execution implementation.
            local.enter_context(patch('ScreenGuard.GuardedMouse', side_effect=lambda mouse, *a, **kw: mouse))
            planner = local.enter_context(patch('DrawBot.make_plan', wraps=DrawBot.make_plan))
            execute = local.enter_context(patch('DrawBot.execute_plan', side_effect=lambda *a, **kw:
                actual_execute(*a, **kw, clock=lambda: 0.0)))
            detectors = [local.enter_context(patch.object(module, name, wraps=getattr(module, name)))
                         for module, name in ((BrowserBrushSize, 'plan_browser_brush_size'),
                                              (BrowserToolLayout, 'plan_browser_tools'),
                                              (GarticOpacity, 'plan_gartic_opacity'))]
            if start is None:
                DrawBot.DrawBotApp.draw(app, user_initiated=True)
            else:
                start()
            self.assertEqual(app.activity, 'draw', app.status.get())
            events = self.events(app)
            self.assertNotIn('error', [kind for kind, _ in events], events)
            self.assertEqual(execute.call_count, 1)
            for detector in detectors:
                self.assertEqual(detector.call_count, 1)
                self.assertEqual(detector.call_args.kwargs['canvas_box'], FULL)
            plan, area = execute.call_args.args[:2]
            self.assertEqual(planner.call_args.args[1], area[2:])
            self.deliver(app, events)
            self.assertEqual(app.start_state_machine.state, 'COMPLETED')
            self.assertIs(app.plan, plan)
        return plan, area

    def test_actual_planner_and_executor_keep_brush_footprints_inside_region_and_never_restore_fill(self):
        app = self.app()
        self.select(app)
        mouse = self.drawing(app)
        before = np.asarray(mouse.surface).copy()
        plan, area = self.execute_actual(app)
        self.assertEqual(area, (700, 600, 120, 90))
        self.assertEqual(plan['preview'].size, (120, 90))
        self.assertEqual(tuple(plan['options']['canvas_guard_meta']['area']), area)
        self.assertGreater(plan['count'], 0)
        self.assertFalse(plan['options']['fill_tool_available'])
        self.assertFalse(plan['options']['fill_tool_actions'])
        self.assertFalse((plan['options'].get('background_fill_plan') or {}).get('enabled'))
        self.assertFalse(plan['options'].get('fill_regions'))
        self.assertNotIn('Fill', mouse.selected_tools)
        self.assertNotIn('Clear', mouse.selected_tools)
        self.assertTrue(mouse.painted)
        changed = np.any(np.asarray(mouse.surface) != before, axis=2)
        inside = np.zeros(changed.shape, dtype=bool)
        inside[SELECTED[1] - FULL[1]:SELECTED[3] - FULL[1],
               SELECTED[0] - FULL[0]:SELECTED[2] - FULL[0]] = True
        self.assertGreater(int(changed.sum()), 0)
        self.assertFalse(np.any(changed & ~inside), 'Native brush footprint escaped the explicitly selected region')
        self.assert_selected(app)

    def test_auto_clear_rejects_both_global_clear_and_unverified_eraser_width_before_input(self):
        app = self.app()
        self.select(app)
        mouse = self.drawing(app, clear=True)
        for tools in (('Clear',), ('Brush', 'Eraser')):
            with self.subTest(tools=tools):
                self.calibrate_tools(tools)
                with patch('DrawBot.execute_plan', wraps=DrawBot.execute_plan) as execute:
                    DrawBot.DrawBotApp.draw(app, user_initiated=True)
                self.assertIsNone(app.activity)
                self.assertIn('Disable Auto clear or select the full canvas', app.status.get())
                self.assertIsNone(app.worker)
                self.assertFalse(mouse.actions)
                execute.assert_not_called()
                self.assert_selected(app)

    def test_explicit_full_canvas_keeps_its_existing_native_clear_and_fill_policy(self):
        app = self.app()
        self.selection = FULL
        self.select(app)
        mouse = self.drawing(app, clear=True)
        plan, area = self.execute_actual(app)
        self.assertEqual(area, (FULL[0], FULL[1], FULL[2] - FULL[0], FULL[3] - FULL[1]))
        self.assertTrue(plan['options']['fill_tool_available'])
        self.assertTrue(plan['options']['fill_tool_actions'])
        self.assertEqual(plan['options']['canvas_clear_strategy'], 'native-clear')
        self.assertIn('Clear', mouse.selected_tools)
        self.assertGreater(plan['count'], 0)

    def test_real_import_persistent_one_click_keeps_region_on_cache_hit_and_reaches_execution(self):
        app = self.app()
        self.select(app)
        self.drawing(app)
        source = self.directory / 'one-click-source.png'
        app.original.save(source)
        app.browser_one_click_enabled.set(True)
        self.assertTrue(app.load_source(str(source), source.name))
        self.deliver(app, self.events(app))
        self.assertTrue(app.root.run(app.browser_one_click_after))
        setup = self.events(app)
        self.assertEqual([kind for kind, _ in setup], ['browser_one_click_setup_complete', 'done'])
        self.assertEqual(setup[0][1]['method'], 'Layout Fingerprint v2 cache')
        self.deliver(app, setup)
        self.assert_selected(app)
        plan, area = self.execute_actual(app, start=lambda: app.root.run(app.browser_one_click_after))
        self.assertEqual(area, (700, 600, 120, 90))
        self.assertFalse(plan['options']['fill_tool_available'])
        self.assertTrue(app.mouse.painted)

    def test_one_click_palette_cache_cannot_publish_ready_after_canvas_disappears(self):
        app = self.app()
        self.select(app)
        path = self.directory / 'source-no-canvas.png'
        app.original.save(path)
        app.browser_one_click_enabled.set(True)
        self.assertTrue(app.load_source(str(path), path.name))
        self.deliver(app, self.events(app))
        ImageDraw.Draw(self.shot).rectangle((470, 280, 1420, 820), fill=(190, 45, 80))
        self.assertTrue(app.root.run(app.browser_one_click_after))
        result = self.events(app)
        self.assertEqual(result[0][0], 'browser_one_click_setup_complete')
        self.assertEqual(result[0][1]['method'], 'Layout Fingerprint v2 cache')
        self.assertIsNone(result[0][1]['canvas_box'])
        for event in result:
            app.events.put(event)
        # Malformed/incomplete live setup uses the real poll containment and
        # failed-done route; it must never grant the deferred drawing start.
        while not app.events.empty():
            DrawBot.DrawBotApp.poll(app)
        self.assertIsNone(app.browser_one_click_request)
        self.assertIsNone(app.activity)
        self.assertFalse(app.browser_auto_calibration_success)
        self.assertIsNone(app.browser_drawing_region.verified_canvas)
        self.assertIn('failed safely', app.browser_one_click_text.get())
        self.assert_selected(app)
        self.assertFalse(app.mouse.actions)

    def test_current_ink_refresh_uses_fresh_full_canvas_without_requiring_palette(self):
        app = self.app()
        self.select(app)
        app.paint_simple.set(True)
        app.outline.set(True)
        app.refresh_palette()
        self.assertFalse(app.palette_ready)
        self.assertEqual(app._refresh_target_for_draw(), META['client_rect'])
        self.assert_selected(app)
        self.assertEqual(DrawBot.DrawBotApp._run_browser_visual_preflight(app, META['client_rect']), META['client_rect'])
        self.assert_selected(app)
        self.assertFalse(app.mouse.actions)

    def test_canvas_drop_explicitly_selects_full_canvas_then_loads_and_runs_force_one_click(self):
        app = self.app()
        self.select(app)
        owner = app.browser_drawing_region
        source = self.directory / 'canvas-drop-source.png'
        app.original.save(source)
        app.smart_drop_in_text = Value('')
        app._expire_smart_drop_overlay = MethodType(DrawBot.DrawBotApp._expire_smart_drop_overlay, app)
        with ExitStack() as local:
            local.enter_context(patch('DrawBot.tk.Toplevel', Overlay))
            local.enter_context(patch('DrawBot.tk.Canvas', return_value=Mock()))
            local.enter_context(patch('SmartDropInCanvas.place_canvas_overlay', side_effect=lambda window, box: box))
            local.enter_context(patch.object(DrawBot.DrawBotApp, '_close_smart_drop_overlay', CLOSE_OVERLAY))
            app.root.tk = self.tcl.tk
            try:
                self.assertTrue(DrawBot.DrawBotApp._show_smart_drop_overlay(app, {
                    'target_meta': dict(self.meta), 'canvas_box': FULL, 'canvas_confidence': .99}))
                overlay = app.smart_drop_overlay
                dropped = overlay.callbacks['<<Drop>>']
                event = SimpleNamespace(x_root=800, y_root=700, data=str(source))
                self.assertEqual(dropped(event), 'copy', app.status.get())
                self.assertTrue(overlay.destroyed)
                self.assertIsNot(app.browser_drawing_region, owner)
                self.assertIsNone(app.browser_drawing_region)
                self.assertEqual(app.corners, [FULL[:2], FULL[2:]])
                self.assertEqual(dropped(event), 'none')
            finally:
                # Mock call/history graphs can retain this scheduler after the
                # app is torn down. The extra raw Tcl owner must end on its
                # creator thread, including a retained failed assertion.
                del app.root.tk
        loaded = self.events(app)
        self.assertEqual([kind for kind, _ in loaded], ['loaded', 'done'], loaded)
        self.deliver(app, loaded)
        self.assertFalse(app.browser_one_click_enabled.get())
        request = app.browser_one_click_request
        self.assertTrue(request['auto_start'])
        self.assertTrue(app.root.run(app.browser_one_click_after))
        setup = self.events(app)
        self.assertEqual([kind for kind, _ in setup], ['browser_one_click_setup_complete', 'done'])
        self.deliver(app, setup)
        self.assertEqual(app.corners, [FULL[:2], FULL[2:]])
        # Observe the actual continuation at the accepted drawing worker. The
        # complete physical executor is independently tested above for a region.
        def accept_draw(current, *, user_initiated=False):
            self.assertIs(current, app)
            self.assertTrue(user_initiated)
            return app.begin_worker('draw', lambda: None)
        with patch.object(DrawBot.DrawBotApp, 'draw', side_effect=accept_draw) as draw:
            self.assertTrue(app.root.run(app.browser_one_click_after))
        draw.assert_called_once_with(app, user_initiated=True)
        self.assertEqual(app.activity, 'draw')
        self.deliver(app, self.events(app))
        self.assertFalse(app.mouse.actions)

    def test_same_profile_reset_and_recovery_retire_the_previous_region_owner(self):
        import ProfilePortability
        for route in ('reset', 'recovery'):
            with self.subTest(route=route), ExitStack() as local:
                app = self.app()
                self.select(app, calibrate=False)
                DrawBot.DrawBotApp._cancel_after_attr(app, 'capture_job')
                app.browser_drawing_region = app.browser_drawing_region.with_canvas('gartic-phone', self.meta, FULL)
                if route == 'reset':
                    local.enter_context(patch('ProfileStorage.data_dir', return_value=self.directory))
                    local.enter_context(patch('ProfilePortability.data_dir', return_value=self.directory))
                    local.enter_context(patch('ProfilePortability.profile_reset_paths',
                        return_value=(app.calibration_path, self.directory / 'tools.json', self.directory / 'layout.json')))
                    local.enter_context(patch('ProfilePortability.profile_timing_file',
                        return_value=self.directory / 'timing.json'))
                    local.enter_context(patch('RealSpeedBudget.SPEED_FILE', self.directory / 'speed.json'))
                    local.enter_context(patch('DrawBot.profile_palette_file', return_value=app.calibration_path))
                    local.enter_context(patch('DrawBot.profile_settings_file', return_value=self.directory / 'settings.json'))
                    self.assertEqual(ProfilePortability.reset_profile(app), 'Gartic Phone')
                    self.assertEqual(app._active_profile_name, 'Gartic Phone')
                else:
                    DrawBot.DrawBotApp._apply_recovery_snapshot(app, {
                        'profile': 'Gartic Phone', 'saved_area': [list(SELECTED[:2]), list(SELECTED[2:])],
                        'has_image': False, 'options': {}}, recovered_image=None)
                self.assertIsNone(app.browser_drawing_region)
                self.assertFalse(app.corners)
                self.assertIsNone(app.target_window)
                self.assertFalse(DrawBot.DrawBotApp._start_guard_ready(app, require_image=True)[0])
                self.assertFalse(app.mouse.actions)

    def test_full_setup_is_an_explicit_new_full_canvas_choice_without_starting_input(self):
        from BrowserOneClick import Candidate
        app = self.app()
        self.select(app, calibrate=False)
        candidate = Candidate(META['handle'], META['rect'], META['client_rect'], 96,
                              999, 'Gartic Phone', .99, 72, FULL, self.shot.copy())
        with patch('BrowserOneClick.discover_browser_target', return_value=candidate):
            DrawBot.DrawBotApp.auto_setup_gartic_full(app)
            self.assertIsNone(app.browser_drawing_region)
            events = self.events(app)
            self.assertEqual([kind for kind, _ in events], ['browser_auto_calibration_complete', 'done'])
            self.deliver(app, events)
        self.assertEqual(app.corners, [FULL[:2], FULL[2:]])
        self.assertIsNone(app.browser_drawing_region)
        self.assertFalse(app.mouse.actions)

    def test_selected_region_survives_actual_setup_refresh_and_independent_visual_preflight(self):
        app = self.app()
        payload = self.select(app)
        self.assertEqual(tuple(payload['canvas_box']), FULL)
        self.assertEqual(payload['palette_count'], 72)
        self.assert_selected(app)
        self.assertIn('inside verified canvas', app.area_text.get())
        self.assertTrue(DrawBot.DrawBotApp._start_guard_ready(app, require_image=True)[0])
        self.assertEqual(app._refresh_target_for_draw(), META['client_rect'])
        self.assert_selected(app)
        self.assertEqual(DrawBot.DrawBotApp._run_browser_visual_preflight(app, META['client_rect']), META['client_rect'])
        self.assert_selected(app)
        self.assertEqual(app.browser_drawing_region.expected_canvas('gartic-phone', self.meta), FULL)
        self.assertFalse(app.mouse.actions)

    def test_cached_auto_setup_rechecks_the_same_capture_and_palette_only_stays_unverified(self):
        app = self.app()
        self.select(app)
        self.assertTrue((self.directory / 'layout.json').exists())
        # Preserve every palette swatch and cached client/layout identity while
        # removing the physical canvas. Palette cache success is insufficient.
        ImageDraw.Draw(self.shot).rectangle((470, 280, 1420, 820), fill=(190, 45, 80))
        for _ in range(2):
            payload = self.select(app)
            self.assertEqual(payload['method'], 'Layout Fingerprint v2 cache')
            self.assertEqual(payload['palette_count'], 72)
            self.assertIsNone(payload['canvas_box'])
            self.assert_selected(app)
            ready, reason = DrawBot.DrawBotApp._start_guard_ready(app, require_image=True)
            self.assertFalse(ready)
            self.assertIn('not verified', reason)
            self.assertIn('Auto setup browser', app.status.get())
            self.assertIsNone(app.browser_drawing_region.verified_canvas)
            with self.assertRaises(ValueError):
                app._refresh_target_for_draw()
            self.assert_selected(app)
            self.assertFalse(app.mouse.actions)

    def test_same_size_translation_is_exact_but_resize_and_dpi_changes_never_expand_region(self):
        for change in ('move', 'resize', 'dpi', 'window'):
            with self.subTest(change=change):
                self.meta = dict(META)
                app = self.app()
                self.select(app)
                if change == 'move':
                    self.meta['client_rect'] = (120, 230, 1720, 1130)
                    self.meta['rect'] = (110, 200, 1730, 1140)
                    app._refresh_target_for_draw()
                    self.assert_selected(app, (720, 630, 840, 720))
                    self.assertEqual(app.browser_drawing_region.expected_canvas('gartic-phone', self.meta),
                                     (600, 520, 1532, 1042))
                else:
                    if change == 'resize':
                        self.meta['client_rect'] = (100, 200, 1720, 1100)
                    elif change == 'dpi':
                        self.meta['dpi'] = 120
                    else:
                        self.meta['handle'] = 456
                    with self.assertRaisesRegex(ValueError, 'Select the drawing area again'):
                        app._refresh_target_for_draw()
                    self.assert_selected(app)
                    self.assertIsNone(app.browser_drawing_region.verified_canvas)
                self.assertFalse(app.mouse.actions)

    def test_verify_only_cache_path_keeps_region_and_runs_a_second_live_pass_without_drawing(self):
        app = self.app()
        self.select(app)
        app.browser_one_click_enabled.set(True)
        self.assertTrue(DrawBot.DrawBotApp.run_one_click_setup_verify(app))
        setup = self.events(app)
        self.assertEqual([kind for kind, _ in setup], ['browser_one_click_setup_complete', 'done'])
        self.assertTrue(setup[0][1]['one_click_setup_verify_only'])
        self.deliver(app, setup)
        self.assert_selected(app)
        self.assertIn(app.one_click_setup_after, app.root.jobs)
        self.assertTrue(app.root.run(app.one_click_setup_after))
        verified = self.events(app)
        self.assertEqual([kind for kind, _ in verified], ['one_click_setup_verification_complete', 'done'])
        self.assertTrue(verified[0][1]['passed'], verified[0][1])
        self.deliver(app, verified)
        self.assert_selected(app)
        self.assertIsNone(app.browser_one_click_request)
        self.assertFalse(app.mouse.actions)
        self.assertIsNone(app.activity)

    def test_second_live_verification_rejects_dpi_or_small_layout_drift_even_with_matching_palette(self):
        for change in ('dpi', 'six-pixel-layout'):
            with self.subTest(change=change):
                self.meta = dict(META)
                replacement = browser_fixture.BrowserAutoCalibrationTests._gartic_image()
                self.images.append(replacement)
                self.shot = replacement
                app = self.app()
                self.select(app)
                self.assertTrue(DrawBot.DrawBotApp.run_one_click_setup_verify(app))
                self.deliver(app, self.events(app))
                if change == 'dpi':
                    self.meta['dpi'] = 120
                else:
                    draw = ImageDraw.Draw(self.shot)
                    draw.rectangle((470, 280, 1420, 820), fill=(190, 45, 80))
                    draw.rectangle((476, 280, 1426, 820), fill=(90, 36, 164))
                    draw.rectangle((486, 290, 1416, 810), fill='white')
                self.assertTrue(app.root.run(app.one_click_setup_after))
                events = self.events(app)
                result = events[0][1]
                self.assertEqual(events[0][0], 'one_click_setup_verification_complete')
                self.assertFalse(result['passed'], result)
                self.assertFalse(result['canvas_ok'], result)
                self.assertTrue(result['palette_ok'], result)
                self.deliver(app, events)
                self.assertIsNone(app.browser_drawing_region.verified_canvas)
                self.assert_selected(app)
                self.assertFalse(DrawBot.DrawBotApp._start_guard_ready(app, require_image=True)[0])
                self.assertFalse(app.mouse.actions)

    def test_old_verification_result_after_stop_or_region_reselection_never_marks_new_owner_verified(self):
        for change in ('stop', 'new-region'):
            with self.subTest(change=change):
                app = self.app()
                self.select(app)
                self.assertTrue(DrawBot.DrawBotApp.run_one_click_setup_verify(app))
                self.deliver(app, self.events(app))
                self.assertTrue(app.root.run(app.one_click_setup_after))
                pending = self.events(app)
                self.assertTrue(pending[0][1]['passed'])
                old_owner = app.browser_drawing_region
                if change == 'stop':
                    DrawBot.DrawBotApp.cancel(app)
                    expected = old_owner
                else:
                    new_box = (710, 610, 830, 700)
                    expected = BrowserDrawingRegion.capture('gartic-phone', self.meta, new_box)
                    app.browser_drawing_region = expected
                    app.corners = [new_box[:2], new_box[2:]]
                    app.saved_area = list(app.corners)
                before = app.one_click_setup_text.get()
                self.deliver(app, pending)
                self.assertIs(app.browser_drawing_region, expected)
                self.assertEqual(app.one_click_setup_text.get(), before)
                if change == 'new-region':
                    self.assertIsNone(expected.verified_canvas)
                self.assertFalse(app.mouse.actions)


class BrowserRegionFixtureOwnershipTests(unittest.TestCase):
    def test_retained_success_and_failed_drop_callbacks_release_tcl_before_worker_collection(self):
        code = '''import gc, threading, tkinter as tk, unittest, weakref
from unittest.mock import patch
import DrawBot
from test_v148_ui_batch20_browser_region import BrowserRegionFlowTests
roots, owners, variables, finalized, retained_errors = [], [], [], [], []
creator = threading.get_ident()
original_finalize = tk.Variable.__del__
def finalize(variable):
    finalized.append(threading.get_ident())
    original_finalize(variable)
tk.Variable.__del__ = finalize
actual_show = DrawBot.DrawBotApp._show_smart_drop_overlay
def failed_show(app, payload):
    actual_show(app, payload)
    try:
        raise RuntimeError('retained fixture error after real overlay creation')
    except RuntimeError as error:
        retained_errors.append(error)
        raise
class ObservedCase(BrowserRegionFlowTests):
    def setUp(self):
        super().setUp()
        owners.append(weakref.ref(self.tcl))
    def app(self):
        app = super().app()
        roots.append(app.root)
        variables.extend(weakref.ref(value) for value in vars(app).values()
                         if isinstance(value, tk.Variable))
        return app
# Delay only the diagnostic child's cyclic collection to make the later
# worker-GC boundary deterministic. Actual Tcl finalizers remain untouched.
gc.disable()
for failing in (False, True):
    case = ObservedCase('test_canvas_drop_explicitly_selects_full_canvas_then_loads_and_runs_force_one_click')
    result = unittest.TestResult()
    if failing:
        with patch.object(DrawBot.DrawBotApp, '_show_smart_drop_overlay', failed_show):
            case.run(result)
        assert len(result.errors) == 1 and not result.failures, (result.errors, result.failures)
        assert 'retained fixture error' in result.errors[0][1], result.errors
    else:
        case.run(result)
        assert result.wasSuccessful(), (result.errors, result.failures)
    del case
assert roots and all(not hasattr(root, 'tk') for root in roots)
assert retained_errors and retained_errors[0].__traceback__ is not None
assert variables and all(reference() is None for reference in variables)
assert all(reference() is None for reference in owners)
assert len(finalized) == len(variables) and set(finalized) == {creator}, finalized
worker = threading.Thread(target=gc.collect)
worker.start()
worker.join(timeout=5)
assert not worker.is_alive()
assert set(finalized) == {creator}
print('retained real drop callbacks released Tcl on creator thread; worker GC completed')
'''
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', code],
            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('worker GC completed', result.stdout)
        self.assertNotIn('Tcl_AsyncDelete', result.stderr)
        self.assertNotIn('Exception ignored in', result.stderr)


if __name__ == '__main__':
    unittest.main()
