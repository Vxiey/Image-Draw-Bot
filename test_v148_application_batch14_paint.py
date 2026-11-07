"""Paint Start preserves manual tools and the physical width Auto prepared."""
from contextlib import ExitStack
from pathlib import Path
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from DrawBot import DrawBotApp
from test_v148_application_batch04_settings import Value


def state(tool='Auto (recommended)'):
    app = SimpleNamespace(
        game=Value('Microsoft Paint'), paint_tool=Value(tool), brush_px=Value('4'),
        original=object(), activity=None, closing=False, stop=threading.Event(),
        status=Value(''), summary=Value(''), root=Mock(), paused=threading.Event(),
        corners=[(100, 100), (140, 120)], target_window=(7, (0, 0, 1000, 800)),
        target_client_rect=(0, 0, 1000, 800),
        full_draw_armed_until=10**12, events=queue.Queue(),
        auto_calibrate_paint_tools=Mock(return_value=True), progress={'value': 0},
        paint_simple=Value(True), outline=Value(False),
        calibration_path=Path('unused-paint-calibration.json'),
        save_settings=Mock(return_value=True),
    )
    app._palette_preflight_ready = Mock(return_value=True)
    app._paint_tool_preflight_ready = Mock(return_value=True)
    app._start_guard_ready = lambda **kw: DrawBotApp._start_guard_ready(app, **kw)
    app._disarm_full_draw = Mock(side_effect=lambda *a, **kw: setattr(app, 'full_draw_armed_until', 0))
    app._refresh_target_for_draw = Mock(return_value=(0, 0, 1000, 800))
    app.area = lambda: (100, 100, 40, 20)
    return app


class ManualPaintStartTests(unittest.TestCase):
    def test_explicit_tools_use_calibrated_start_without_auto_replacing_tool_or_width(self):
        for tool in ('Pencil', 'Brush', 'Eraser', 'Use current tool'):
            with self.subTest(tool=tool):
                app = state(tool)
                with patch.object(DrawBotApp, 'draw', return_value='started') as draw:
                    self.assertEqual(DrawBotApp.start_full_drawing(app), 'started')
                draw.assert_called_once_with(app, user_initiated=True)
                app.auto_calibrate_paint_tools.assert_not_called()
                self.assertEqual((app.paint_tool.get(), app.brush_px.get()), (tool, '4'))
                self.assertEqual(app.full_draw_armed_until, 0)

    def test_manual_paint_keeps_the_explicit_unlock_and_setup_checks(self):
        for missing in ('unlock', 'area', 'target', 'palette', 'tool'):
            with self.subTest(missing=missing):
                app = state('Eraser')
                if missing == 'unlock': app.full_draw_armed_until = 0
                elif missing == 'area': app.corners = []
                elif missing == 'target': app.target_window = None
                elif missing == 'palette': app._palette_preflight_ready.return_value = False
                elif missing == 'tool': app._paint_tool_preflight_ready.return_value = False
                with patch.object(DrawBotApp, 'draw') as draw:
                    DrawBotApp.start_full_drawing(app)
                draw.assert_not_called()
                app.auto_calibrate_paint_tools.assert_not_called()
                self.assertIn('locked', app.status.get())

    def test_auto_and_older_callers_still_prepare_without_prior_calibration(self):
        for legacy in (False, True):
            app = state()
            if legacy: del app.paint_tool
            app.corners = []
            app.target_window = None
            app.full_draw_armed_until = 0
            with patch.object(DrawBotApp, 'draw') as draw:
                self.assertTrue(DrawBotApp.start_full_drawing(app))
            draw.assert_not_called()
            app.auto_calibrate_paint_tools.assert_called_once_with(start_after=True)

    def test_quick_start_uses_manual_setup_and_unlock_for_explicit_paint_tool(self):
        app = state('Use current tool')
        app.full_draw_armed_until = 0
        with patch.object(DrawBotApp, 'unlock_full_drawing', return_value=True) as unlock, \
                patch.object(DrawBotApp, 'start_full_drawing', return_value='started') as start:
            self.assertEqual(DrawBotApp.quick_start_hotkey(app), 'started')
        unlock.assert_called_once_with(app)
        start.assert_called_once_with(app)
        app.auto_calibrate_paint_tools.assert_not_called()

    def test_button_text_matches_the_selected_start_route(self):
        for tool, unlocked, expected in (
                ('Auto (recommended)', False, 'Prepare Paint & draw'),
                ('Eraser', False, 'Start locked'), ('Brush', True, 'Start Drawing')):
            app = state(tool)
            app.full_draw_armed_until = 10**12 if unlocked else 0
            app.start = Mock()
            app.start_secondary = Mock()
            DrawBotApp._refresh_start_buttons_text(app)
            self.assertIn(expected, app.start.configure.call_args.kwargs['text'])
            self.assertEqual(app.start.configure.call_args, app.start_secondary.configure.call_args)


class PreparedPaintHandoffTests(unittest.TestCase):
    def completion(self, requested='4', width=4):
        app = state()
        request = {'image': app.original}
        app.paint_start_request = request
        for name in ('area_text', 'custom_color_workflow', 'one_click_setup_text'):
            setattr(app, name, Value(''))
        app.color_session_cache = {}
        for name in ('refresh_palette', 'refresh_tool_calibration', 'refresh_exact_color_status',
                     '_mark_plan_stale', '_invalidate_target_lock'):
            setattr(app, name, Mock())
        result = {
            'target_meta': {'handle': 7, 'rect': [0, 0, 1000, 800],
                            'client_rect': [0, 0, 1000, 800], 'dpi': 96},
            'canvas_box': [100, 100, 140, 120],
            'canvas_confidence': .95,
            'prepared_brush_px': width, 'brush_px_requested': requested,
            'auto_brush_width_meta': {'brush_px': width, 'reason': 'source analysis'},
            'start_request': request,
        }
        return app, request, result

    def test_completion_preserves_manual_width_and_auto_preference_and_passes_physical_width(self):
        for requested in ('4', 'Auto'):
            app, request, result = self.completion(requested)
            DrawBotApp._handle_event(app, 'paint_auto_calibration_complete', result)
            self.assertEqual(app.brush_px.get(), requested)
            self.assertIn('4 px', app.one_click_setup_text.get())
            prepared = request['prepared_options']
            self.assertEqual(prepared['brush_px'], 4)
            self.assertEqual(prepared['brush_px_requested'], requested)
            with patch.object(DrawBotApp, 'draw', return_value=True) as draw:
                self.assertTrue(DrawBotApp._resume_prepared_paint(app, request))
            draw.assert_called_once_with(app, user_initiated=True, paint_prepared=True,
                                         paint_prepared_options=prepared)

    def test_invalid_physical_width_cannot_partially_adopt_setup(self):
        for invalid in (True, 0, 51, 4.5, '4'):
            app, request, result = self.completion(width=invalid)
            old_corners = app.corners
            with self.assertRaisesRegex(ValueError, 'brush width'):
                DrawBotApp._handle_event(app, 'paint_auto_calibration_complete', result)
            self.assertIs(app.corners, old_corners)
            app.save_settings.assert_not_called()
            app.root.after.assert_not_called()

    def test_changed_width_or_manual_tool_revokes_delayed_prepared_start(self):
        for change in ('width', 'tool'):
            app, request, result = self.completion('Auto')
            DrawBotApp._handle_event(app, 'paint_auto_calibration_complete', result)
            if change == 'width': app.brush_px.set('8')
            else: app.paint_tool.set('Eraser')
            with patch.object(DrawBotApp, 'draw') as draw:
                self.assertFalse(DrawBotApp._resume_prepared_paint(app, request))
            draw.assert_not_called()
            self.assertIsNone(app.paint_start_request)

    def test_real_draw_preflight_uses_prepared_width_when_auto_reanalysis_differs(self):
        app = state()
        app.original = Image.new('RGB', (8, 4), 'black')
        self.addCleanup(app.original.close)
        app.options = lambda: dict(
            brush_px=2, brush_px_requested='Auto', auto_brush_width_meta={'brush_px': 2},
            paint_tool='Use current tool', effective_paint_tool='Use current tool',
            background_fill='Off', use_region_fill_engine=False, auto_clear_canvas=False,
            paint_current_color=True, outline=False, unlimited_time=True, max_seconds=180)
        captured = []
        def planning(options, **kwargs):
            captured.append(options)
            raise InterruptedError('stop before building or drawing')
        def begin(activity, task):
            self.assertEqual(activity, 'draw')
            with self.assertRaisesRegex(InterruptedError, 'stop before'):
                task()
            return False
        app.begin_worker = begin
        prepared = {'brush_px': 4, 'brush_px_requested': 'Auto',
                    'auto_brush_width_meta': {'brush_px': 4, 'reason': 'prepared'}}
        with patch.object(DrawBotApp, '_cancel_after_attr'), \
                patch.object(DrawBotApp, '_disarm_full_draw'), \
                patch.object(DrawBotApp, '_run_browser_visual_preflight', return_value=(0, 0, 1000, 800)), \
                patch('ScreenGuard.GuardedMouse'), patch('ScreenGuard.WindowMonitor'), \
                patch('DrawBot.build_planning_attempts', side_effect=planning):
            app.mouse = Mock()
            DrawBotApp.draw(app, user_initiated=True, paint_prepared=True, paint_prepared_options=prepared)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]['brush_px'], 4)
        self.assertEqual(captured[0]['canvas_guard_brush_px'], 4)
        self.assertEqual(captured[0]['auto_brush_width_meta'], prepared['auto_brush_width_meta'])
        app.auto_calibrate_paint_tools.assert_not_called()

    def test_preparation_failure_report_reads_no_tk_variable_on_the_worker(self):
        app = state()
        owner = threading.get_ident()
        class ThreadBoundValue(Value):
            def get(self):
                if threading.get_ident() != owner:
                    raise AssertionError('Tk variable read on worker')
                return super().get()
        app.game = ThreadBoundValue('Microsoft Paint')
        errors = []
        def begin(activity, task):
            def run():
                try: task()
                except BaseException as error: errors.append(error)
            worker = threading.Thread(target=run)
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            return True
        app.begin_worker = begin
        with patch('PaintPreparation.ensure_paint', side_effect=ValueError('Paint unavailable')):
            self.assertTrue(DrawBotApp.auto_calibrate_paint_tools(app, one_click_verify=True))
        self.assertFalse(errors)
        kind, payload = app.events.get_nowait()
        self.assertEqual(kind, 'one_click_setup_verification_complete')
        self.assertEqual(payload['profile_name'], 'Microsoft Paint')
        self.assertEqual(payload['error'], 'Paint unavailable')


if __name__ == '__main__':
    unittest.main()
