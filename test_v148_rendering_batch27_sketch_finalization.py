"""A Sketch Fill colour handoff preserves geometry without unused UI passes."""
from collections import Counter
from contextlib import ExitStack, closing, contextmanager
import gc
import json
from pathlib import Path
import tempfile
import threading
import traceback
import unittest
from unittest.mock import patch
import weakref

from PIL import Image, ImageDraw

import AccuracyEvaluator
import Colors
import DrawBot
import EndToEndAutoTuner
import PixelAccuracyEngine
import PixelData
import PreviewDiagnostics
import PreviewLayers
import Sketch2Planner
from test_v148_rendering_batch15_sketch_memory import comparable_plan
import test_v148_ui_batch07_renderer as ui_fixtures


PALETTE = ((0, 0, 0), (255, 255, 255), (220, 30, 30), (0, 80, 205))
HANDOFF = '_sketch_fill_defer_presentation'


def plan_images(value, seen=None):
    """Test observation only: complete image aliases, never product cleanup."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, Image.Image):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from plan_images(item, seen)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from plan_images(item, seen)


def is_open(image):
    try:
        image.getpixel((0, 0))
        return True
    except (ValueError, AttributeError):
        return False


def close_plan(plan):
    for image in plan_images(plan):
        image.close()


def source_image(kind='rgb'):
    size = (1601, 16) if kind == 'wide' else (96, 72) if kind in ('rgba', 'islands') else (40, 32)
    image = Image.new('RGBA' if kind == 'rgba' else 'RGB', size, 'white')
    drawing = ImageDraw.Draw(image)
    try:
        if kind == 'islands':
            for y in range(4, 68, 5):
                for x in range(4, 92, 5):
                    color = PALETTE[(x//5 + y//5) % 3 + 1]
                    drawing.rectangle((x, y, x+1, y+1), fill=color)
        elif kind == 'rgba':
            drawing.rectangle((9, 9, 60, 62), fill=(220, 30, 30, 192),
                              outline=(0, 0, 0, 255), width=2)
            drawing.rectangle((40, 24, 86, 56), fill=(0, 80, 205, 128),
                              outline=(0, 0, 0, 255))
            drawing.rectangle((3, 3, 6, 6), fill=(123, 45, 67, 0))
        elif kind == 'wide':
            drawing.rectangle((6, 4, 1594, 11), fill=PALETTE[2], outline='black')
        else:
            drawing.rectangle((7, 6, 32, 25), fill=PALETTE[2], outline='black', width=2)
    finally:
        drawing.draw = drawing.im = drawing._image = None
    image.info['draw_studio_format'] = 'PNG'
    return image


@contextmanager
def planner_fixture(quality='Balanced', brush=1, kind='rgb', *, ui_changes=None):
    old_palette = list(Colors.allColors)
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        directory = Path(directory)
        for name in ('source_dir', 'data_dir'):
            stack.enter_context(patch('RuntimePaths.' + name, return_value=directory))
        stack.enter_context(patch.object(DrawBot, 'log_event', new=lambda *_a, **_k: None))
        stack.enter_context(patch.object(DrawBot, 'custom_rgb_available', return_value=False))
        stack.enter_context(patch('ResourceAllocation.available_ram_mb', return_value=8192))
        calibration = directory / 'palette.json'
        calibration.write_text(json.dumps({'version': 4, 'profile': 'microsoft-paint',
            'state': 'calibrated', 'colors': [
                {'name': f'Swatch {i}', 'position': [-400 + 10*i, -100], 'rgb': list(rgb)}
                for i, rgb in enumerate(PALETTE)]}), encoding='utf-8')
        Colors.load_calibration(calibration, profile_key='microsoft-paint')
        def restore_palette():
            Colors.allColors[:] = old_palette
            PixelData.closest_color.cache_clear()
        stack.callback(restore_palette)
        source = stack.enter_context(closing(source_image(kind)))
        app = ui_fixtures.AdvertisedRendererTests().app()
        try:
            app.draw_quality.set(quality)
            app.brush_px.set(str(brush))
            app.time_budget_mode = ui_fixtures.Value('Unlimited / Accuracy')
            for key,value in (ui_changes or {}).items():
                setattr(app,key,ui_fixtures.Value(value))
            options = DrawBot.DrawBotApp.options(app)
        finally:
            vars(app).clear()
        options.update(available_ram_mb=8192, logical_cpus=4, ram_budget_mb=2048,
                       cpu_workers_resolved=1)
        assert options['render_style'] == 'Sketch + Auto Fill'
        yield source, options


class WorkObservation:
    def __init__(self, stop=None, boundary=None, *, full_control=False):
        self.stop = stop or threading.Event()
        self.boundary, self.full_control = boundary, full_control
        self.stage = []
        self.calls = Counter()
        self.inner = []
        self.created = []
        self.refinement = []

    @contextmanager
    def installed(self):
        real_plan, real_finish = DrawBot.make_plan, DrawBot.finish_plan
        real_contour = Sketch2Planner.contour_image_v2
        real_refine = PixelAccuracyEngine.refine_with_corrections
        real_new = Image.Image._new
        observer = self

        def created(owner, core):
            image = real_new(owner, core)
            observer.created.append(weakref.ref(image))
            return image

        def counted(name, function):
            def call(*args, **kwargs):
                key = observer.stage[-1] if observer.stage else 'planning'
                observer.calls[key + ':' + name] += 1
                result = None
                try:
                    result = function(*args, **kwargs)
                    if key == 'inner' and name == 'safety' and observer.boundary == 'inner_safety':
                        observer.stop.set()
                    return result
                finally:
                    args = (); kwargs = {}; result = None
            return call

        def finish(image, fitted, groups, options, cancelled=lambda: False):
            kind = 'final' if options.get('sketch_fill_active') else 'inner'
            observer.calls['finish:' + kind] += 1
            if kind == 'final' and observer.boundary == 'final_finish':
                observer.stop.set()
            if (kind == 'inner' and observer.boundary == 'outer_rescue_inner'
                    and int(options.get('_auto_tuner_replan_attempt') or 0) == 1):
                observer.stop.set()
            observer.stage.append(kind)
            result = None
            try:
                result = real_finish(image, fitted, groups, options, cancelled)
                if kind == 'inner':
                    observer.inner.append({'images': [weakref.ref(v) for v in plan_images(result)],
                        'geometry': comparable_plan({key: result[key] for key in
                            ('image', 'fitted', 'groups', 'execution_groups', 'execution_sequence',
                             'count', 'colors', 'color_selectors', 'path_stats')}),
                        'options': {key: comparable_plan(result['options'].get(key)) for key in
                            ('pixel_accuracy_meta', 'pixel_accurate', 'color_order')},
                        'has_source_accuracy': 'adaptive_accuracy_meta' in result['options'],
                        'has_ui_previews': bool(result.get('ui_previews'))})
                return result
            finally:
                observer.stage.pop()
                image = groups = options = result = None

        def plan(image, area, options, cancelled=lambda: False):
            is_inner = bool(options.get('_sketch_fill_inner')) and not options.get('sketch_fill_active')
            if observer.full_control and is_inner:
                options = dict(options)
                options.pop(HANDOFF, None)
            result = None
            try:
                result = real_plan(image, area, options, cancelled)
                if is_inner and observer.boundary == 'inner_return':
                    observer.stop.set()
                return result
            finally:
                image = options = result = None

        def contour(image, cancelled=lambda: False, detail='Detailed'):
            result = None
            try:
                result = real_contour(image, cancelled, detail)
                if observer.boundary == 'contour_return':
                    observer.stop.set()
                return result
            finally:
                image = result = None

        def refine(*args, **kwargs):
            result = None
            try:
                result = real_refine(*args, **kwargs)
                observer.refinement.append(comparable_plan(result['metadata']))
                return result
            finally:
                args = (); kwargs = {}; result = None

        with ExitStack() as stack:
            stack.enter_context(patch.object(Image.Image, '_new', new=created))
            stack.enter_context(patch.object(DrawBot, 'make_plan', new=plan))
            stack.enter_context(patch.object(DrawBot, 'finish_plan', new=finish))
            stack.enter_context(patch.object(Sketch2Planner, 'contour_image_v2', new=contour))
            stack.enter_context(patch.object(PixelAccuracyEngine, 'refine_with_corrections', new=refine))
            for module, name, label in (
                (AccuracyEvaluator, 'evaluate_preview', 'source_accuracy'),
                (PreviewLayers, 'build_auxiliary_previews', 'auxiliary'),
                (PreviewDiagnostics, 'render_quantized_target', 'quantized_target'),
                (PreviewDiagnostics, 'build_preview_diagnostics', 'diagnostics'),
                (DrawBot, 'build_preview_safety_plan', 'safety'),
                (DrawBot, 'optimize_execution_groups', 'optimizer'),
                (EndToEndAutoTuner, 'evaluate_plan_acceptance', 'tuner_acceptance'),
                (EndToEndAutoTuner, 'propose_rescue_options', 'tuner_rescue'),
            ):
                stack.enter_context(patch.object(module, name, new=counted(label, getattr(module, name))))
            yield self


class SketchPresentationTests(unittest.TestCase):
    def test_real_balanced_and_pixel_callers_finalize_presentation_once(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality), planner_fixture(quality) as (source, options):
                observation = WorkObservation()
                with observation.installed():
                    plan = DrawBot.make_plan(source, source.size, options)
                try:
                    self.assertEqual(observation.calls['finish:inner'], 1)
                    self.assertEqual(observation.calls['finish:final'], 1)
                    for name in ('source_accuracy', 'auxiliary', 'quantized_target', 'diagnostics'):
                        self.assertEqual(observation.calls['inner:' + name], 0, name)
                        self.assertEqual(observation.calls['final:' + name], 1, name)
                    self.assertEqual(observation.calls['inner:safety'], 1)
                    self.assertEqual(observation.calls['final:safety'], 1)
                    self.assertEqual(observation.calls['inner:optimizer'], int(quality == 'Balanced'))
                    self.assertEqual(len(observation.refinement), int(quality == 'Pixel Accurate'))
                    self.assertNotIn(HANDOFF, plan['options'])
                    self.assertNotIn(HANDOFF, options)
                    self.assertIn('visual_accuracy_percent', plan['options']['adaptive_accuracy_meta'])
                    self.assertIn('delta_e', plan['ui_previews'])
                finally:
                    close_plan(plan)

    def test_complete_public_outputs_equal_full_inner_control(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            for brush, kind in ((1, 'rgb'), (4, 'rgb'), (3, 'rgba')):
                with self.subTest(quality=quality, brush=brush, kind=kind), \
                        planner_fixture(quality, brush, kind) as (source, options):
                    before = source.tobytes()
                    plans = []
                    observations = []
                    try:
                        for full in (True, False):
                            observation = WorkObservation(full_control=full)
                            with observation.installed():
                                plan = DrawBot.make_plan(source, source.size, options)
                            plans.append(plan); observations.append(observation)
                        self.assertEqual(comparable_plan(plans[0]), comparable_plan(plans[1]))
                        self.assertEqual(observations[0].inner[0]['geometry'], observations[1].inner[0]['geometry'])
                        self.assertEqual(observations[0].inner[0]['options'], observations[1].inner[0]['options'])
                        self.assertEqual(observations[0].refinement, observations[1].refinement)
                        self.assertEqual(source.tobytes(), before)
                    finally:
                        for plan in plans:
                            close_plan(plan)

    def assert_released(self, references, preserved=()):
        keep = {id(image) for image in preserved}
        live = []
        for reference in references:
            image = reference()
            if image is not None and id(image) not in keep and is_open(image):
                live.append((image.mode, image.size))
            image = None
        self.assertEqual(live, [], 'Private image cores survive the consumer boundary.')

    def test_inner_images_retire_while_the_returned_final_plan_stays_usable(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality), planner_fixture(quality) as (source, options):
                observation = WorkObservation()
                with observation.installed():
                    plan = DrawBot.make_plan(source, source.size, options)
                try:
                    retained = list(plan_images(plan)) + [source]
                    self.assertTrue(all(is_open(image) for image in retained))
                    self.assert_released(observation.inner[0]['images'], retained)
                    # Images returned by the contour producer and original
                    # ground-preview drawing also have no remaining consumer.
                    self.assert_released(observation.created, retained)
                finally:
                    close_plan(plan)

    def check_retained_error(self, quality, boundary=None, kind='rgb', expected=InterruptedError):
        with planner_fixture(quality, kind=kind) as (source, options):
            original = source.tobytes()
            observation = WorkObservation(boundary=boundary)
            error = None
            try:
                with observation.installed():
                    try:
                        DrawBot.make_plan(source, source.size, options, observation.stop.is_set)
                    except expected as caught:
                        error = caught
                self.assertIsNotNone(error)
                self.assertIsNotNone(error.__traceback__)
                gc.collect()
                self.assert_released(observation.created, (source,))
                self.assertEqual(source.tobytes(), original)
                tb = error.__traceback__
                while tb is not None:
                    for value in tuple(tb.tb_frame.f_locals.values()):
                        if isinstance(value, ImageDraw.ImageDraw):
                            self.assertIsNone(value.im)
                            self.assertIsNone(value.draw)
                            self.assertIsNone(value._image)
                    tb = tb.tb_next
            finally:
                for reference in observation.created:
                    image = reference()
                    if image is not None and image is not source:
                        image.close()
                if error is not None:
                    traceback.clear_frames(error.__traceback__)
                    error.__traceback__ = None
                error = image = None

    def test_stop_after_real_inner_return_releases_held_traceback_images(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality):
                self.check_retained_error(quality, 'inner_return')

    def test_stop_after_real_contours_releases_held_traceback_images(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality):
                self.check_retained_error(quality, 'contour_return')

    def test_stop_in_real_final_finisher_releases_images_and_drawing_handles(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality):
                self.check_retained_error(quality, 'final_finish')

    def test_actual_contour_size_error_releases_the_completed_pixel_color_plan(self):
        self.check_retained_error('Pixel Accurate', kind='wide', expected=ValueError)

    def test_standalone_inner_flag_keeps_complete_public_presentation(self):
        with planner_fixture() as (source, options):
            options = dict(options, _sketch_fill_inner=True, render_style='Standard / pixel')
            observation = WorkObservation()
            with observation.installed():
                plan = DrawBot.make_plan(source, source.size, options)
            try:
                self.assertEqual(observation.calls['inner:source_accuracy'], 1)
                self.assertEqual(observation.calls['inner:auxiliary'], 1)
                self.assertIn('preview_diagnostics', plan)
                self.assertIn('draw_time_estimate', plan)
                self.assertIn('quantized_target', plan['ui_previews'])
            finally:
                close_plan(plan)

    def test_real_active_tuner_keeps_full_color_diagnostics_and_bounded_rescue(self):
        for kind in ('rgb', 'rgba'):
            with self.subTest(kind=kind), planner_fixture('Pixel Accurate', 4, kind) as (source, options):
                # Use the real source analysis, quality gates and strategy. A
                # retained Auto context may then select the Sketch Fill style.
                tuned = EndToEndAutoTuner.tune_options(source, dict(options, render_preset='Auto'))
                tuned.update(render_style='Sketch + Auto Fill', draw_quality='Pixel Accurate')
                self.assertTrue(tuned['auto_tuner_meta']['active'])
                plans = []
                try:
                    for full in (True, False):
                        observation = WorkObservation(full_control=full)
                        with observation.installed():
                            plan = DrawBot.make_plan(source, source.size, tuned)
                        plans.append(plan)
                        self.assertEqual(observation.calls['finish:inner'], 2)
                        for name in ('source_accuracy', 'auxiliary', 'quantized_target'):
                            self.assertEqual(observation.calls['inner:' + name], 2, name)
                            self.assertEqual(observation.calls['final:' + name], 1, name)
                        self.assertEqual(observation.calls['planning:tuner_acceptance'], 3)
                        self.assertEqual(observation.calls['planning:tuner_rescue'], 3)
                        self.assertEqual(plan['options']['_auto_tuner_replan_attempt'], 1)
                        self.assertEqual(len(plan['options']['_auto_tuner_attempt_history']), 1)
                        self.assertEqual(plan['options']['auto_tuner_meta']['selected_strategy'], 'quality-rescue')
                        self.assertNotIn(HANDOFF, plan['options'])
                        self.assert_released(observation.created, tuple(plan_images(plan)) + (source,))
                    self.assertEqual(comparable_plan(plans[0]), comparable_plan(plans[1]))
                finally:
                    for plan in plans:
                        close_plan(plan)

    def test_stop_during_real_inner_safety_releases_an_unreturned_color_plan(self):
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality):
                self.check_retained_error(quality, 'inner_safety')

    def test_borrowed_source_and_option_images_survive_success_and_retained_stop(self):
        import SketchFillRenderer
        for stop in (False, True):
            with self.subTest(stop=stop), planner_fixture() as (source, options), \
                    closing(source.convert('RGB')) as quantized, closing(source.copy()) as normalized:
                options = dict(options, _accuracy_original_source=source,
                               _accuracy_quantized_target=quantized,
                               _accuracy_normalized_source_cache={'source': source,
                                   'image': normalized, 'size': source.size})
                borrowed = (source, quantized, normalized)
                before = [image.tobytes() for image in borrowed]
                observation = WorkObservation(boundary='inner_return' if stop else None)
                plan = error = None
                try:
                    with observation.installed():
                        try:
                            plan = DrawBot.make_plan(source, source.size, options, observation.stop.is_set)
                        except InterruptedError as caught:
                            error = caught
                    self.assertEqual(error is not None, stop)
                    self.assertIsNone(SketchFillRenderer._current_plan_image_owner())
                    self.assertEqual([image.tobytes() for image in borrowed], before)
                    preserved = borrowed + tuple(plan_images(plan))
                    self.assert_released(observation.created, preserved)
                finally:
                    close_plan(plan)
                    if error is not None:
                        traceback.clear_frames(error.__traceback__)
                        error.__traceback__ = None
                    error = None

    def test_stop_in_actual_outer_tuner_rescue_retires_the_unpublished_first_plan(self):
        with planner_fixture() as (source, options):
            tuned = EndToEndAutoTuner.tune_options(source, dict(options, render_preset='Auto'))
            tuned.update(render_style='Sketch + Auto Fill', draw_quality='Balanced',
                         extra_fast=False, extra_fast_v2=False)
            observation = WorkObservation(boundary='outer_rescue_inner')
            error = None
            try:
                with observation.installed():
                    try:
                        DrawBot.make_plan(source, source.size, tuned, observation.stop.is_set)
                    except InterruptedError as caught:
                        error = caught
                self.assertIsNotNone(error)
                self.assertEqual(observation.calls['finish:inner'], 2)
                self.assertEqual(observation.calls['finish:final'], 1)
                self.assertEqual(observation.calls['planning:tuner_acceptance'], 2)
                self.assertEqual(observation.calls['planning:tuner_rescue'], 2)
                gc.collect()
                self.assert_released(observation.created, (source,))
                self.assertTrue(is_open(source))
            finally:
                for reference in observation.created:
                    image = reference()
                    if image is not None and image is not source:
                        image.close()
                if error is not None:
                    traceback.clear_frames(error.__traceback__)
                    error.__traceback__ = None
                error = image = None

    def test_actual_active_timer_and_explicit_target_cap_stay_in_the_color_plan(self):
        ui_changes = {'time_budget_mode':'30 sec', 'target_stroke_count':'Custom',
                      'target_stroke_custom':'50', 'adaptive_detail':'Off',
                      'background_simplification':'Off', 'adaptive_deadline_renderer':True}
        for quality in ('Balanced', 'Pixel Accurate'):
            with self.subTest(quality=quality), planner_fixture(quality, kind='islands',
                    ui_changes=ui_changes) as (source, options):
                self.assertTrue(options['time_budget_active'])
                if quality=='Pixel Accurate':
                    # The inexpensive source now fits in30s under the real
                    # delivery model. Use an actual slower path delay so this
                    # fixture continues to exercise nonempty budget trimming.
                    options=dict(options,delay=.08,_execution_cost_calibration_override={})
                plans = []; observations = []
                try:
                    for full in (True, False):
                        observation = WorkObservation(full_control=full)
                        with observation.installed():
                            plans.append(DrawBot.make_plan(source, source.size, options))
                        observations.append(observation)
                    self.assertEqual(comparable_plan(plans[0]), comparable_plan(plans[1]))
                    self.assertEqual(observations[0].inner[0]['geometry'], observations[1].inner[0]['geometry'])
                    if quality == 'Balanced':
                        path_stats = observations[1].inner[0]['geometry']['path_stats']
                        self.assertGreater(path_stats['target_skipped_paths'], 0)
                        self.assertLessEqual(path_stats['target_after_paths'], 50)
                        self.assertGreater(path_stats['target_before_paths'], path_stats['target_after_paths'])
                    else:
                        budget = observations[1].inner[0]['options']['pixel_accuracy_meta']['progressive_time_budget']
                        self.assertTrue(budget['active'])
                        self.assertGreater(budget['paths_omitted'], 0)
                        self.assertGreater(budget['base_path_budget'],0)
                        self.assertGreater(budget['initial_sequence_seconds'],budget['sequence_budget_seconds'])
                        self.assertLessEqual(budget['risk_adjusted_sequence_seconds'],
                                             budget['base_sequence_budget_seconds']+1e-9)
                    self.assertNotIn(HANDOFF, plans[1]['options'])
                finally:
                    for plan in plans:
                        close_plan(plan)

    def test_nested_adaptive_hybrid_keeps_its_full_decision_plan(self):
        with planner_fixture() as (source, options):
            options = dict(options, extra_fast=True, extra_fast_v2=True)
            plans = []; observations = []
            try:
                for full in (True, False):
                    observation = WorkObservation(full_control=full)
                    with observation.installed():
                        plans.append(DrawBot.make_plan(source, source.size, options))
                    observations.append(observation)
                self.assertEqual(comparable_plan(plans[0]), comparable_plan(plans[1]))
                self.assertGreaterEqual(observations[1].calls['finish:inner'], 2)
                self.assertEqual(observations[0].calls, observations[1].calls)
                self.assertEqual(observations[1].calls['inner:source_accuracy'],
                                 observations[1].calls['finish:inner'])
            finally:
                for plan in plans:
                    close_plan(plan)


if __name__ == '__main__':
    unittest.main()
