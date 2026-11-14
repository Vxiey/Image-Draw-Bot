"""Reuse one unchanged worker sequence cost; all late ETA conditions stay fresh."""
from contextlib import nullcontext
from contextvars import copy_context
from copy import deepcopy
import gc
import threading
from unittest.mock import patch
import weakref

import DrawBot
import DrawTimeEstimate as eta
import DrawTimeCalibration as timing
import RealSpeedBudget as speed
from test_v148_ui_batch20_preview_estimate import PreviewEstimateFixture, observe_estimates
from test_v148_rendering_batch06_canvas import close_plan
from test_v148_rendering_batch21_calibration_scope import public_source, public_options, public_environment


class PreviewSequenceTransferTests(PreviewEstimateFixture):
    def test_actual_native_projected_and_full_worker_cost_once_with_identical_final_estimate(self):
        for area, full in (((84, 64), False), ((1100, 600), False), ((84, 64), True)):
            with self.subTest(area=area, full=full):
                app = self.app(area)
                source = app.original.tobytes()
                with observe_estimates() as records:
                    plan, done = self.build(app, full_detail=full)
                    self.assertEqual(len(records), 2)
                    self.assertGreater(records[0]['path_calls'], 0)
                    self.assertEqual(records[1]['sequence_calls'], 0)
                    self.assertEqual(records[1]['path_calls'], 0,
                                     'The final preview worker must not recost unchanged geometry')
                    self.assertEqual(records[0]['metadata']['sequence_operation_model'],
                                     records[1]['metadata']['sequence_operation_model'])
                    prepared = deepcopy(plan['draw_time_estimate'])
                    self.adopt(app, plan, done)
                    self.assertEqual(len(records), 2, 'Existing U2001 still prevents a third UI pass')
                self.assertEqual(plan['draw_time_estimate'], eta.estimate_from_plan(plan))
                self.assertEqual(plan['draw_time_estimate'], prepared)
                self.assertEqual(app.original.tobytes(), source)
                self.assertEqual(prepared['is_projection'], area == (1100, 600))

    def test_mutated_geometry_order_phase_brush_selector_and_delivery_recalculate(self):
        def path(plan):
            row = next(row for row in plan['execution_sequence'] if len(row['path']) > 1)
            row['path'] = [list(point) for point in row['path']]
            row['path'][-1][1] += 7

        def phase(plan):
            plan['execution_sequence'][1]['phase'] = 'explicit-late-phase'

        def selector(plan):
            index = int(plan['execution_sequence'][0]['color_index'])
            selectors = [dict(kind='palette') for _ in plan['colors']]
            selectors[index]['kind'] = 'custom'
            plan['options']['exact_color_available'] = True
            plan['options']['color_selectors'] = selectors

        mutations = {
            'nested-mutable-path': path,
            'reordered-sequence': lambda plan: plan['execution_sequence'].reverse(),
            'phase': phase,
            'brush': lambda plan: plan['execution_sequence'][0].update(brush_px=4),
            'color': lambda plan: plan['execution_sequence'][0].update(color_index=1),
            'selector': selector,
            'delay': lambda plan: plan['options'].update(delay=.023),
            'speed': lambda plan: plan['options'].update(speed='Safe'),
            'precision': lambda plan: plan['options'].update(precision='Normal'),
            'delivery': lambda plan: plan['options'].update(paint_stroke_delivery='Compatible'),
            'fitted': lambda plan: plan.update(fitted=(168, 128)),
            'scale': lambda plan: plan['options'].update(_execution_scale_x=2.75),
        }
        actual = DrawBot.make_plan
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                app = self.app()
                def changed(*args, **kwargs):
                    plan = actual(*args, **kwargs)
                    mutate(plan)
                    return plan
                with patch.object(DrawBot, 'make_plan', new=changed), observe_estimates() as records:
                    plan, done = self.build(app)
                    self.assertEqual(len(records), 2)
                    self.assertGreater(records[-1]['path_calls'], 0)
                    self.adopt(app, plan, done)
                self.assertEqual(plan['draw_time_estimate'], eta.estimate_from_plan(plan))

    def test_foreign_plan_and_missing_geometry_use_the_existing_fresh_or_legacy_path(self):
        actual = DrawBot.make_plan
        for change in ('foreign-plan', 'missing-image-fitted', 'no-sequence'):
            with self.subTest(change=change):
                app = self.app()
                def changed(*args, **kwargs):
                    plan = actual(*args, **kwargs)
                    if change == 'foreign-plan':
                        return dict(plan)
                    if change == 'missing-image-fitted':
                        self.images.append(plan.pop('image'))
                        plan.pop('fitted')
                    else:
                        plan['execution_sequence'] = None
                    return plan
                with patch.object(DrawBot, 'make_plan', new=changed), observe_estimates() as records:
                    # The inherited build assertion requires a final sequence;
                    # handle the explicit legacy control at its actual queue.
                    if change == 'no-sequence':
                        app.update_plan(user_initiated=True)
                        self.wait_for_preview_worker(app)
                        events = [app.events.get_nowait(), app.events.get_nowait()]
                        self.assertEqual([kind for kind, _ in events], ['planned', 'done'])
                        plan, done = events[0][1], events[1]
                        self.plans.append(plan)
                        self.assertFalse(plan['draw_time_estimate']['sequence_model_used'])
                    else:
                        plan, done = self.build(app)
                        self.assertGreater(records[-1]['path_calls'], 0)
                    self.adopt(app, plan, done)
                self.assertEqual(plan['draw_time_estimate'], eta.estimate_from_plan(plan))

    def test_final_fixed_and_background_costs_are_fresh_without_repricing_sequence(self):
        app = self.app()
        actual = DrawBot.make_plan
        def changed(*args, **kwargs):
            plan = actual(*args, **kwargs)
            plan['options'].update(
                adaptive_deadline_meta={'fixed_overhead': {'countdown_seconds': 3., 'clear_seconds': 1.25}},
                background_fill_plan={'enabled': True, 'color_index': 0}, fill_tool_available=True)
            return plan
        with patch.object(DrawBot, 'make_plan', new=changed), observe_estimates() as records:
            plan, done = self.build(app)
            self.assertEqual(records[-1]['path_calls'], 0)
            cold = plan['draw_time_estimate']['sequence_operation_model']
            self.assertEqual(cold['outside_sequence_seconds'], 4.25)
            self.assertEqual(cold['fill_actions'], 1)
            self.assertGreater(cold['background_fill_seconds'], 0)
            self.assertNotEqual(records[0]['metadata'], records[-1]['metadata'])
            self.adopt(app, plan, done)
        self.assertEqual(plan['draw_time_estimate'], eta.estimate_from_plan(plan))

    def test_selector_container_and_stringified_phase_types_cannot_collide_in_the_input_seal(self):
        for name, initial, changed in (
                ('selector-container', None, None), ('phase-int-float', 1, 1.0),
                ('phase-bool-int', True, 1), ('phase-signed-zero', 0.0, -0.0)):
            with self.subTest(name=name):
                app = self.app()
                plan = DrawBot.make_plan(app.original, (84, 64), app.options())
                self.plans.append(plan)
                rows = plan['execution_sequence']
                self.assertGreater(len(rows), 2)
                rows[0]['color_index'] = rows[1]['color_index'] = 0
                if name == 'selector-container':
                    selectors = [dict(kind='palette') for _ in plan['colors']]
                    selectors[0] = dict(kind='custom')
                    plan['options'].update(exact_color_available=True, color_selectors=selectors)
                else:
                    for row in rows:
                        row['phase'] = initial
                with eta.preview_estimate_scope(), observe_estimates() as records:
                    before = eta.attach_draw_time_estimate(plan)
                    if name == 'selector-container':
                        plan['options']['color_selectors'][0] = [('kind', 'custom')]
                    else:
                        rows[1]['phase'] = changed
                    after = eta.attach_preview_draw_time_estimate(plan)
                expected = eta.estimate_from_plan(plan)
                self.assertNotEqual(before, expected, 'The production cost model must really distinguish the fixture')
                self.assertEqual(after, expected)
                self.assertGreater(records[-1]['path_calls'], 0)

    def test_actual_fill_contours_are_repriced_independently_of_the_sequence_transfer(self):
        import RegionFillEngine
        actual = RegionFillEngine.estimate_fill_execution_seconds
        calls = []
        def fill(*args, **kwargs):
            result = actual(*args, **kwargs)
            calls.append((kwargs.get('use_cached_cost'), deepcopy(result)))
            return result
        source = public_source()
        self.images.append(source)
        with public_environment(self.directory), patch.object(RegionFillEngine, 'estimate_fill_execution_seconds', new=fill), eta.preview_estimate_scope():
            options = public_options('paint_fill')
            options.update(progressive_rendering='On', color_workflow='Progressive passes')
            plan = DrawBot.make_plan(source, source.size, options)
            self.plans.append(plan)
            self.assertEqual(len(plan['options']['fill_regions']), 3)
            self.assertTrue(plan['draw_time_estimate']['sequence_model_used'])
            calls.clear()
            eta.attach_preview_draw_time_estimate(plan)
            self.assertEqual(len(calls), 1)
            self.assertIs(calls[0][0], False)
            prepared = deepcopy(plan['draw_time_estimate'])
        self.assertEqual(prepared, eta.estimate_from_plan(plan))

    def test_nonbuiltin_phase_and_failed_snapshot_use_fresh_cost_without_custom_serialization(self):
        reducer_calls = []
        class Phase:
            def __str__(self):
                return 'late-phase'
            def __reduce__(self):
                reducer_calls.append('object')
                raise AssertionError('A nonbuiltin value must not reach serialization')
        class StringPhase(str):
            def __reduce_ex__(self, protocol):
                reducer_calls.append(('str-subclass', protocol))
                raise AssertionError('A str subclass must not reach serialization')
        for reason in ('nonbuiltin', 'str-subclass', 'allocation'):
            with self.subTest(reason=reason):
                app = self.app()
                plan = DrawBot.make_plan(app.original, (84, 64), app.options())
                self.plans.append(plan)
                if reason == 'nonbuiltin':
                    plan['execution_sequence'][0]['phase'] = Phase()
                elif reason == 'str-subclass':
                    plan['execution_sequence'][0]['phase'] = StringPhase('late-phase')
                expected = eta.estimate_from_plan(plan)
                failing = patch.object(eta.pickle, 'dumps', side_effect=MemoryError('private byte snapshot'))
                with failing if reason == 'allocation' else nullcontext(), eta.preview_estimate_scope(), observe_estimates() as records:
                    self.assertEqual(eta.attach_draw_time_estimate(plan), expected)
                    self.assertEqual(eta.attach_preview_draw_time_estimate(plan), expected)
                self.assertEqual(len(records), 2)
                self.assertTrue(all(row['path_calls'] > 0 for row in records))
                self.assertEqual(reducer_calls, [])

    def test_calibration_and_real_speed_written_after_planning_are_read_before_publication(self):
        app = self.app()
        options = app.options()
        options.update(profile_key='gartic-phone', profile_name='Gartic Phone', paint_profile=False)
        app.options = lambda: dict(options)
        actual = DrawBot.make_plan
        scoped = []
        read = eta._local_calibration
        def calibration(settings):
            scoped.append(timing._planning_observation.get() is not None)
            return read(settings)
        def learned(*args, **kwargs):
            plan = actual(*args, **kwargs)
            self.assertIsNone(timing._planning_observation.get())
            for _ in range(3):
                self.assertTrue(timing.record_sample(plan['options'], 10., 20., completed_paths=plan['count'])['recorded'])
            self.assertTrue(speed.record_runtime_sample('gartic-phone', plan['count'], plan['count'] / .25,
                path=self.directory / 'speed.json', options=plan['options'])['recorded'])
            return plan
        with patch.object(DrawBot, 'make_plan', new=learned), patch.object(eta, '_local_calibration', new=calibration), observe_estimates() as records:
            plan, done = self.build(app)
            self.assertEqual(records[0]['metadata']['measured_samples'], 0)
            self.assertEqual(records[-1]['metadata']['measured_samples'], 3)
            self.assertEqual(records[-1]['path_calls'], 0)
            self.assertEqual(scoped, [True, False])
            self.assertGreater(plan['draw_time_estimate']['projected_seconds'], plan['count'])
            prepared = deepcopy(plan['draw_time_estimate'])
            self.adopt(app, plan, done)
            self.assertEqual(len(records), 2)
        self.assertEqual(prepared, eta.estimate_from_plan(plan))

    def test_copied_context_other_thread_cannot_borrow_or_retire_the_owning_workers_result(self):
        app = self.app()
        with eta.preview_estimate_scope():
            plan = DrawBot.make_plan(app.original, (84, 64), app.options())
            self.plans.append(plan)
            results, failures = [], []
            context = copy_context()
            def foreign():
                try:
                    results.append(context.run(eta.attach_preview_draw_time_estimate, plan))
                except BaseException as error:
                    failures.append(error)
            with observe_estimates() as records:
                worker = threading.Thread(target=foreign)
                worker.start(); worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                self.assertFalse(failures)
                self.assertEqual(len(results), 1)
                self.assertGreater(records[0]['path_calls'], 0)
                expected = deepcopy(results[0])
                self.assertEqual(eta.attach_preview_draw_time_estimate(plan), expected)
                self.assertEqual(records[-1]['path_calls'], 0)
                self.assertEqual(eta.attach_preview_draw_time_estimate(plan), expected)
                self.assertGreater(records[-1]['path_calls'], 0, 'The same transfer cannot be consumed twice')

    def test_stop_after_real_planning_discards_transfer_and_next_explicit_preview_is_fresh(self):
        app = self.app()
        actual = DrawBot.make_plan
        def stopped(*args, **kwargs):
            plan = actual(*args, **kwargs)
            self.plans.append(plan)
            DrawBot.DrawBotApp._request_stop(app)
            return plan
        with patch.object(DrawBot, 'make_plan', new=stopped):
            app.update_plan(user_initiated=True)
            self.wait_for_preview_worker(app)
            kinds = []
            while not app.events.empty():
                event = app.events.get_nowait()
                kinds.append(event[0]); app._handle_event(*event)
            self.assertNotIn('planned', kinds)
            self.assertIn('done', kinds)
            self.assertIsNone(app.plan)
            self.assertTrue(app.stop.is_set())
        with observe_estimates() as records:
            plan, done = self.build(app)
            self.adopt(app, plan, done)
            self.assertGreater(records[0]['path_calls'], 0)
            self.assertEqual(records[-1]['path_calls'], 0)
        self.assertEqual(plan['draw_time_estimate'], eta.estimate_from_plan(plan))

    def test_retained_stop_and_failure_do_not_keep_the_private_plan_or_cost_scope_alive(self):
        app = self.app()
        references, retained = [], []
        def unpublished(error):
            plan = None
            try:
                with eta.preview_estimate_scope():
                    plan = DrawBot.make_plan(app.original, (84, 64), app.options())
                    references.append(weakref.ref(plan['image']))
                    raise error
            finally:
                if plan is not None:
                    close_plan(plan, app.original)
                plan = None
        for error in (InterruptedError('actual owner stop'), RuntimeError('late publication failure')):
            try:
                unpublished(error)
            except (InterruptedError, RuntimeError) as failure:
                retained.append(failure)
        gc.collect()
        self.assertTrue(all(reference() is None for reference in references))
        self.assertTrue(all(error.__traceback__ is not None for error in retained))
        self.assertIsNone(eta._preview_sequence_cost.get())
        self.assertEqual(app.original.getpixel((0, 0)), (255, 255, 255, 255))


if __name__ == '__main__':
    import unittest
    unittest.main()
