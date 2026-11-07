"""The composed Sketch Fill plan owns its counts, safety and diagnostics."""
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
import copy
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import DrawBot
from Precision import precision_path
from PreviewDiagnostics import format_preview_diagnostics
from StrokeDelivery import resolve_stroke_delivery
from test_drawbot import Mouse, NoWait
import test_v148_application_batch08_preview_cache as preview_fixtures
import test_v148_ui_batch07_renderer as renderer_fixtures
from test_v148_ui_batch09_progressive import summary_from_actual_workspace


class VerifiedMouse(Mouse):
    """Only the native ink inspection boundary is replaced for execution."""
    def inspect_ink_segment(self, _start, _end, color, _brush, _tolerance):
        return {'matched': True, 'actual': tuple(color), 'confidence': 100.0,
                'sample_count': 4, 'error': 0}


def grouped_paths(sequence, color_count):
    groups = [[] for _ in range(color_count)]
    for entry in sequence:
        groups[entry['color_index']].append(tuple(entry['path']))
    return groups


class SketchOwnershipTests(unittest.TestCase):
    @contextmanager
    def planned(self, quality='Pixel Accurate', *, failed_final_accuracy=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch('RuntimePaths.source_dir', return_value=Path(directory)))
            stack.enter_context(patch('DrawBot.log_event'))
            stack.enter_context(patch('DrawBot.custom_rgb_available', return_value=False))
            stack.enter_context(patch('DrawTimeCalibration.load_profile', return_value=None))
            source = stack.enter_context(closing(Image.new('RGB', (40, 32), 'white')))
            ImageDraw.Draw(source).rectangle((7, 6, 32, 25), fill=(220, 30, 30),
                                            outline='black', width=2)
            app = renderer_fixtures.AdvertisedRendererTests().app()
            app.draw_quality.set(quality)
            app.brush_px.set('1')
            options = DrawBot.DrawBotApp.options(app)
            inner = []
            actual_make_plan = DrawBot.make_plan
            def make_plan(image, area, settings, cancelled=lambda: False):
                result = actual_make_plan(image, area, settings, cancelled)
                if settings.get('_sketch_fill_inner'):
                    inner.append((result, copy.deepcopy(result['options'].get('pixel_accuracy_meta'))))
                return result
            from AccuracyEvaluator import evaluate_preview
            evaluations = 0
            def accuracy(*args, **kwargs):
                nonlocal evaluations
                evaluations += 1
                if failed_final_accuracy and evaluations == 2:
                    raise MemoryError('controlled final accuracy failure')
                return evaluate_preview(*args, **kwargs)
            with patch('DrawBot.make_plan', side_effect=make_plan), \
                    patch('AccuracyEvaluator.evaluate_preview', side_effect=accuracy):
                plan = DrawBot.make_plan(source, source.size, options)
            try:
                self.assertEqual(len(inner), 1)
                yield source, options, plan, inner[0]
            finally:
                seen = set()
                renderer_fixtures.close_images(plan, seen)
                for color_plan, _meta in inner:
                    renderer_fixtures.close_images(color_plan, seen)

    def test_actual_pixel_color_subplan_cannot_override_final_groups_counts_or_safety(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality), self.planned(quality) as (_source, requested, plan, inner):
                color_plan, original_meta = inner
                options = plan['options']
                sequence = plan['execution_sequence']
                self.assertEqual(requested['render_style'], 'Sketch + Auto Fill')
                self.assertEqual(requested['draw_quality'], quality)
                self.assertEqual(Counter(entry['phase'] for entry in sequence),
                                 {'sketch': 2, 'color_fill': 3, 'reoutline': 1})
                self.assertEqual(plan['count'], len(sequence))
                self.assertEqual(plan['path_stats']['mode'], 'Sketch + Auto Fill')
                self.assertTrue(plan['path_stats']['sketch_fill'])
                self.assertEqual(plan['execution_groups'], options['_sketch_fill_execution_groups'])
                for actual, expected in zip(plan['execution_groups'], grouped_paths(sequence, len(plan['colors']))):
                    self.assertEqual(Counter(actual), Counter(expected))
                self.assertEqual(options['preview_safety_meta']['paths_in'], len(sequence))
                self.assertEqual(sum(map(len, options['_preview_safety_groups'])), len(sequence))
                self.assertEqual(options['operation_timing_meta']['path_bookkeeping_seconds'],
                                 round(len(sequence) * .0015, 4))
                # Price the actual public sequence independently of the chosen
                # grouped representation. This fixture is identity-scaled and
                # entirely within the unchanged CanvasGuard inset.
                delivery = resolve_stroke_delivery(options)
                moves = 0
                brush = float(options['brush_px'])
                for entry in sequence:
                    if not entry['path']:
                        continue
                    brush = float(entry.get('brush_px', brush))
                    step = delivery.step_px
                    if options.get('pixel_accurate'):
                        step = min(step, max(1., brush * 1.5))
                    moves += sum(len(precision_path(a, b, options['precision'], step))
                                 for a, b in zip(entry['path'], entry['path'][1:]))
                dots = sum(len(entry['path']) == 1 for entry in sequence)
                motion = moves * max(DrawBot.phase_delay(options['delay'], options['speed'], 'path'),
                                     delivery.min_path_delay)
                motion += len(sequence) * (DrawBot.phase_delay(options['delay'], options['speed'], 'travel') +
                    DrawBot.phase_delay(options['delay'], options['speed'], 'boundary') +
                    delivery.press_settle + delivery.release_settle)
                motion += dots * .015
                self.assertAlmostEqual(options['operation_timing_meta']['motion_seconds'], round(motion, 4), places=4)
                self.assertEqual(color_plan['options'].get('pixel_accuracy_meta'), original_meta)
                if quality == 'Pixel Accurate':
                    self.assertIn('_pixel_execution_sequence', color_plan['options'])
                    self.assertNotIn('_pixel_execution_groups', options)
                    self.assertNotIn('_pixel_execution_sequence', options)
                    # This legacy flag is also a native spacing policy. Keep
                    # its effect even though the Pixel sub-plan no longer owns
                    # the final groups, sequence or accuracy measurements.
                    self.assertEqual(options.get('pixel_accurate'), color_plan['options']['pixel_accurate'])

    def test_actual_summary_and_previews_never_publish_inner_pixel_accuracy_as_final(self):
        with self.planned() as (source, _requested, plan, inner):
            options = plan['options']
            inner_options = inner[0]['options']
            self.assertEqual(inner_options['pixel_accuracy_meta']['spill_pixels'], 0)
            self.assertIn('coverage', inner[0]['ui_previews'])
            self.assertEqual(options['sketch_fill_meta']['pixel_metrics_status'], 'not_calculated')
            self.assertNotIn('pixel_accuracy_meta', options)
            self.assertNotIn('_pixel_coverage_preview', options)
            self.assertNotIn('coverage', plan['ui_previews'])
            for name in ('coverage_percent', 'plan_execution_accuracy_percent'):
                self.assertNotIn(name, options['adaptive_accuracy_meta'])
                self.assertNotIn(name, plan['preview_diagnostics']['accuracy'])
            self.assertIn('visual_accuracy_percent', options['adaptive_accuracy_meta'])
            self.assertIn('delta_e', plan['ui_previews'])
            self.assertIn('accuracy_error', plan['ui_previews'])
            summary = summary_from_actual_workspace(plan)
            self.assertIn('6 strokes', summary)
            self.assertIn('2 sketch → 3 color fill → 1 re-outline', summary)
            self.assertNotIn('Coverage ', summary)
            self.assertNotIn('Plan execution ', summary)
            diagnostics = format_preview_diagnostics(plan['preview_diagnostics'])
            self.assertNotIn('Coverage ', diagnostics)
            self.assertNotIn('Plan 100', diagnostics)
            self.assertIn('Visual ', diagnostics)
            app = SimpleNamespace(closing=False, original=source, plan=plan,
                original_canvas=preview_fixtures.Canvas(), result_canvas=preview_fixtures.Canvas(),
                coverage_canvas=preview_fixtures.Canvas(), delta_e_canvas=preview_fixtures.Canvas(),
                accuracy_error_canvas=preview_fixtures.Canvas(), preview_zoom=renderer_fixtures.Value(0))
            with patch('PIL.ImageTk.PhotoImage', side_effect=preview_fixtures.Photo):
                DrawBot.DrawBotApp.show_previews(app)
            self.assertIsNone(app.coverage_canvas.photo)
            self.assertIn('Coverage not calculated', app.coverage_canvas.text)
            self.assertTrue(any('plan-execution accuracy are not calculated' in text
                                for text in app.coverage_canvas.text))
            self.assertIsNotNone(app.result_canvas.photo)
            self.assertIsNotNone(app.delta_e_canvas.photo)
            self.assertIsNotNone(app.accuracy_error_canvas.photo)

    def test_final_accuracy_failure_cannot_resurrect_color_subplan_success(self):
        with self.planned(failed_final_accuracy=True) as (_source, _requested, plan, inner):
            self.assertIn('adaptive_accuracy_meta', inner[0]['options'])
            self.assertNotIn('adaptive_accuracy_meta', tuple(plan['options']))
            self.assertNotIn('pixel_accuracy_meta', tuple(plan['options']))
            self.assertFalse(plan['preview_diagnostics']['accuracy'])
            self.assertEqual(plan['options']['sketch_fill_meta']['pixel_metrics_status'], 'not_calculated')
            self.assertEqual(plan['count'], len(plan['execution_sequence']))

    def test_actual_executor_reports_the_composed_work_and_keeps_phase_order(self):
        with self.planned() as (_source, _requested, plan, _inner), ExitStack() as stack:
            stack.enter_context(patch('DrawBot.save_runtime_safety_report', side_effect=lambda state: state.as_dict()))
            for name in ('RealSpeedBudget.record_runtime_sample', 'DrawTimeEstimate.record_completed_draw',
                         'CompletedDrawingAnalysis.record_completed_drawing', 'AutoTunerFeedback.record_completed_feedback',
                         'CorrectionHistory.record_correction_history'):
                stack.enter_context(patch(name, return_value={}))
            mouse = VerifiedMouse()
            events = []
            source_sequence = copy.deepcopy(plan['execution_sequence'])
            palette = [(-900 + 5 * index, -1000) for index in range(len(plan['colors']))]
            with patch('DrawBot.precision_path', wraps=precision_path) as sampling:
                DrawBot.execute_plan(plan, (100, 100, 40, 32), palette, mouse, NoWait(), threading.Event(),
                    lambda *event: events.append(event), clock=lambda: 0)
            self.assertTrue(sampling.call_args_list)
            self.assertEqual({call.args[3] for call in sampling.call_args_list}, {1.5})
            self.assertFalse(mouse.held)
            self.assertEqual(plan['execution_sequence'], source_sequence)
            self.assertEqual(plan['options']['runtime_path_counts']['guard_skipped'], 0)
            self.assertEqual(plan['options']['runtime_path_counts']['sent'], len(source_sequence))
            progress = [value for kind, value in events if kind == 'progress']
            self.assertIn((len(source_sequence), len(source_sequence)), progress)
            self.assertTrue(all(done <= total for done, total in progress))
            self.assertEqual(plan['options']['canvas_guard_meta']['brush_inset']['brush_px'], 1)
            statuses = [value for kind, value in events if kind == 'status']
            self.assertTrue(any('Sketch 2.0 contours' in text for text in statuses))
            self.assertTrue(any('color fill' in text for text in statuses))
            self.assertTrue(any('final re-outline' in text for text in statuses))


if __name__ == '__main__':
    unittest.main()
