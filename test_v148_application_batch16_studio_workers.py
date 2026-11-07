"""IW40/IW08 completion: Studio planners own one worker and their images."""
from contextlib import ExitStack
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import DrawBot
from DrawBot import DrawBotApp
import test_v148_application_batch14_browser_start as worker_fixtures
from test_v148_application_batch04_settings import Value


ACTIONS = (
    ('run_performance_benchmark', 'performance-benchmark', 'performance_benchmark'),
    ('run_benchmark_suite', 'benchmark-suite', 'benchmark_suite'),
    ('run_golden_image_regression', 'golden-regression', 'golden_regression'),
)


class StudioWorkerOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.threads = []
        self.plans = []
        self.thread_hook = None
        self.stack.enter_context(patch('DrawBot.log_event'))
        self.stack.enter_context(patch('DrawBot.log_error'))
        self.screen_window = self.stack.enter_context(patch('ScreenTaskWindow.ScreenTaskWindow'))
        self.stack.enter_context(patch('DrawBot.threading.Thread', side_effect=self.new_thread))
        self.stack.enter_context(patch.object(DrawBotApp, '_schedule_poll'))
        self.stack.enter_context(patch.object(DrawBotApp, '_close_smart_drop_overlay'))
        self.stack.enter_context(patch.object(DrawBotApp, '_disarm_manual_drop_in'))
        self.stack.enter_context(patch.object(DrawBotApp, '_disarm_full_draw'))
        self.real_planner = DrawBot.make_plan
        self.planner = self.stack.enter_context(patch('DrawBot.make_plan', side_effect=self.make_plan))
        self.suite = self.stack.enter_context(patch('BenchmarkSuite.run', return_value={'case_count': 1}))
        self.golden = self.stack.enter_context(patch('GoldenImageRegression.run', return_value={'case_count': 1}))
        self.ensure_golden = self.stack.enter_context(patch('GoldenImageRegression.ensure_local_golden_images'))
        self.stack.enter_context(patch('BenchmarkSuite.format_result', return_value='Suite complete.'))
        self.stack.enter_context(patch('GoldenImageRegression.format_result', return_value='Golden complete.'))
        self.app = self.new_app()

    def image(self, color='red'):
        image = Image.new('RGBA', (12, 8), color)
        self.addCleanup(image.close)
        return image

    def new_app(self):
        app = DrawBotApp.__new__(DrawBotApp)
        app.root = worker_fixtures.ScheduledRoot()
        app.activity = None
        app.worker = None
        app.closing = app.shutdown_complete = False
        app.pending_clear_drawing = None
        app.profile_change_after = None
        app.profile_change_in_progress = False
        app.stop = threading.Event()
        app.paused = threading.Event()
        app.events = queue.Queue()
        app.original = self.image()
        app.plan = None
        app.status = Value('Ready.')
        app.summary = Value('Existing summary.')
        app.benchmark_suite_text = Value('Existing benchmark result.')
        app.options = Mock(return_value={'snapshot': 'GUI settings'})
        app.set_busy = lambda value: setattr(app, 'activity', value)
        app.save_settings = Mock()
        app._finish_shutdown = Mock()
        app.needs_plan = False
        app.drop_action_pending = None
        app.mouse = Mock()
        app.snapshots = []
        original_copy = app.original.copy
        def copy(*args, **kwargs):
            image = original_copy(*args, **kwargs)
            app.snapshots.append(image)
            self.addCleanup(image.close)
            return image
        self.stack.enter_context(patch.object(app.original, 'copy', side_effect=copy))
        self.app = app
        return app

    def new_thread(self, *, target, **kwargs):
        thread = worker_fixtures.DeferredThread(target=target, **kwargs)
        self.threads.append(thread)
        if self.thread_hook is not None:
            self.thread_hook()
        return thread

    def make_plan(self, image, target, options, cancelled):
        owned = [self.image(color) for color in ('green', 'blue', 'white', 'black')]
        plan = {'image': owned[0], 'preview': owned[1],
                'ui_previews': {'color': owned[1], 'diagnostic': owned[2]},
                'options': dict(options, _accuracy_original_source=owned[3]),
                'performance_profile': {}, 'source_count': 2, 'count': 1}
        self.plans.append((plan, owned))
        return plan

    def runner(self, method):
        return {'run_performance_benchmark': self.planner,
                'run_benchmark_suite': self.suite,
                'run_golden_image_regression': self.golden}[method]

    def drain(self):
        events = []
        while not self.app.events.empty():
            event = self.app.events.get_nowait()
            events.append(event)
            self.app._handle_event(*event)
        return events

    def assert_closed(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_each_action_tracks_one_worker_and_blocks_overlapping_jobs(self):
        for method, activity, _event in ACTIONS:
            with self.subTest(method=method):
                app = self.new_app()
                before = len(self.threads)
                getattr(app, method)()
                self.assertEqual(app.activity, activity)
                self.assertIs(app.worker, self.threads[-1])
                self.assertTrue(app.worker.is_alive())
                for other, _activity, _event in ACTIONS:
                    self.assertFalse(getattr(app, other)())
                self.assertFalse(app.begin_worker('draw', Mock()))
                self.assertEqual(len(self.threads), before + 1)
                self.assertEqual(app.options.call_count, 1)

    def test_incomplete_profile_or_shutdown_rejects_before_settings_or_image_copy(self):
        for field, value in (('closing', True), ('profile_change_after', 'pending'),
                             ('profile_change_in_progress', True),
                             ('pending_clear_drawing', object())):
            for method, _activity, _event in ACTIONS:
                with self.subTest(field=field, method=method):
                    app = self.new_app()
                    setattr(app, field, value)
                    before = len(self.threads)
                    self.assertFalse(getattr(app, method)())
                    app.options.assert_not_called()
                    self.assertEqual(app.snapshots, [])
                    self.assertEqual(len(self.threads), before)

    def test_successful_jobs_publish_results_then_release_busy_state(self):
        for method, activity, event_kind in ACTIONS:
            with self.subTest(method=method):
                app = self.new_app()
                getattr(app, method)()
                app.options.return_value = {'snapshot': 'Later GUI settings'}
                self.threads[-1].run()
                calls = self.runner(method).call_args
                options = calls.args[2] if method == 'run_performance_benchmark' else calls.args[1]
                self.assertEqual(options['snapshot'], 'GUI settings')
                self.assertEqual(app.options.call_count, 1)
                events = self.drain()
                self.assertEqual(sum(kind == event_kind for kind, _ in events), 1)
                self.assertIn(('done', activity), events)
                self.assertIsNone(app.activity)
                self.assertIsNone(app.worker)
                self.assertNotEqual(app.summary.get(), 'Existing summary.')
                self.assertFalse(app.mouse.method_calls)

    def test_explicit_new_action_can_follow_an_old_stop(self):
        for method, _activity, event_kind in ACTIONS:
            with self.subTest(method=method):
                app = self.new_app()
                app.stop.set()
                getattr(app, method)()
                self.threads[-1].run()
                self.assertFalse(app.stop.is_set())
                self.assertTrue(any(kind == event_kind for kind, _ in self.drain()))

    def test_stop_during_settings_preflight_is_not_cleared_at_handoff(self):
        for method, _activity, _event in ACTIONS:
            with self.subTest(method=method):
                app = self.new_app()
                app.options.side_effect = lambda: app.stop.set() or {'snapshot': 'stopped'}
                before = len(self.threads)
                getattr(app, method)()
                self.assertTrue(app.stop.is_set())
                self.assertEqual(len(self.threads), before)
                for image in app.snapshots:
                    self.assert_closed(image)

    def test_stop_before_task_skips_all_runners_and_releases_accepted_source(self):
        for method, _activity, _event in ACTIONS:
            with self.subTest(method=method):
                app = self.new_app()
                runner = self.runner(method)
                before = runner.call_count
                getattr(app, method)()
                app.cancel()
                self.threads[-1].run()
                self.assertEqual(runner.call_count, before)
                self.drain()
                self.assertEqual(app.status.get(), 'Stopped.')
                for image in app.snapshots:
                    self.assert_closed(image)
                self.assertEqual(app.original.getpixel((0, 0)), (255, 0, 0, 255))

    def test_stop_during_screen_window_or_thread_construction_stays_cancelled(self):
        for stage in ('window', 'thread'):
            for method, _activity, _event in ACTIONS:
                with self.subTest(stage=stage, method=method):
                    app = self.new_app()
                    runner = self.runner(method)
                    before = runner.call_count
                    if stage == 'window':
                        self.screen_window.side_effect = lambda *args: app.stop.set() or Mock()
                    else:
                        self.thread_hook = app.stop.set
                    try:
                        getattr(app, method)()
                        if app.worker is not None:
                            app.worker.run()
                        self.assertTrue(app.stop.is_set())
                        self.assertEqual(runner.call_count, before)
                        for image in app.snapshots:
                            self.assert_closed(image)
                    finally:
                        self.screen_window.side_effect = None
                        self.thread_hook = None

    def test_runner_return_after_stop_cannot_publish_success(self):
        for method, _activity, event_kind in ACTIONS:
            with self.subTest(method=method):
                app = self.new_app()
                runner = self.runner(method)
                def stopped(*args, **kwargs):
                    result = self.make_plan(*args, **kwargs) if method == 'run_performance_benchmark' else {'case_count': 1}
                    app.stop.set()
                    return result
                runner.side_effect = stopped
                try:
                    getattr(app, method)()
                    self.threads[-1].run()
                    events = self.drain()
                    self.assertFalse(any(kind == event_kind for kind, _ in events))
                    self.assertEqual(app.status.get(), 'Stopped.')
                finally:
                    runner.side_effect = self.make_plan if method == 'run_performance_benchmark' else None

    def test_already_queued_results_do_not_replace_stop_or_existing_summaries(self):
        for method, _activity, _event in ACTIONS:
            with self.subTest(method=method):
                app = self.new_app()
                getattr(app, method)()
                self.threads[-1].run()
                before = (app.summary.get(), app.benchmark_suite_text.get())
                app.cancel()
                self.drain()
                self.assertEqual(app.status.get(), 'Stopped.')
                self.assertEqual((app.summary.get(), app.benchmark_suite_text.get()), before)

    def test_shutdown_waits_for_the_tracked_worker_to_finish(self):
        for method, _activity, _event in ACTIONS:
            with self.subTest(method=method):
                app = self.new_app()
                getattr(app, method)()
                app.close()
                app._finish_shutdown.assert_not_called()
                self.assertTrue(app.stop.is_set())
                self.threads[-1].run()
                app.poll()
                app._finish_shutdown.assert_called_once_with()
                for image in app.snapshots:
                    self.assert_closed(image)

    def test_performance_success_releases_private_snapshot_and_all_plan_images(self):
        self.app.run_performance_benchmark()
        self.threads[-1].run()
        self.drain()
        for image in self.app.snapshots + self.plans[-1][1]:
            self.assert_closed(image)
        self.assertEqual(self.app.original.getpixel((0, 0)), (255, 0, 0, 255))

    def test_performance_format_failure_releases_images_despite_retained_traceback(self):
        error = RuntimeError('injected summary failure')
        with patch('DrawBot.profiler_dominant_phase', side_effect=error):
            self.app.run_performance_benchmark()
            self.threads[-1].run()
        self.assertIsNotNone(error.__traceback__)
        for image in self.app.snapshots + self.plans[-1][1]:
            self.assert_closed(image)
        self.assertEqual(self.app.original.getpixel((0, 0)), (255, 0, 0, 255))

    def test_real_pixel_plan_releases_its_full_resolution_accuracy_target(self):
        from test_pixel_accurate_v1086 import opts
        captured = []
        def plan(source, target, options, cancelled):
            self.assertEqual(target, (800, 450))
            # Exercise the real planner's owned fields at native source size;
            # this is a lifecycle regression, not an elapsed-time benchmark.
            result = self.real_planner(source, source.size, options, cancelled)
            captured.append(result)
            from AutoSketchBudget import _trial_images
            for image in _trial_images(result):
                self.addCleanup(image.close)
            return result
        self.app.options.return_value = opts(profile_name='Microsoft Paint', profile_key='microsoft-paint',
            paint_profile=True, skip_white=True, cpu_workers_resolved=1, unlimited_time=True,
            time_budget_mode='Unlimited', detail_zoom='Off', post_draw_correction_pass='Off',
            _execution_cost_calibration_override={})
        self.planner.side_effect = plan
        self.app.run_performance_benchmark()
        self.threads[-1].run()
        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0]['options']['_accuracy_quantized_target'], Image.Image)
        from AutoSketchBudget import _trial_images
        for image in self.app.snapshots + _trial_images(captured[0]):
            self.assert_closed(image)
        self.assertEqual(self.app.original.getpixel((0, 0)), (255, 0, 0, 255))

    def test_performance_source_alias_closes_without_closing_retained_ui_plan(self):
        live_target = self.image('yellow')
        self.app.plan = {'image': self.app.original,
                         'options': {'_accuracy_quantized_target': live_target}}
        def plan(source, target, options, cancelled):
            return {'image': source, 'preview': self.app.original,
                    'options': {'_accuracy_quantized_target': live_target},
                    'count': 1, 'source_count': 1, 'performance_profile': {}}
        self.planner.side_effect = plan
        self.app.run_performance_benchmark()
        self.threads[-1].run()
        self.assert_closed(self.app.snapshots[0])
        self.assertEqual(self.app.original.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(live_target.getpixel((0, 0)), (255, 255, 0, 255))

    def test_synthetic_draw_context_releases_its_pixel_core_on_retained_failure(self):
        for stage in ('paint', 'start'):
            with self.subTest(stage=stage), ExitStack() as local:
                app = self.new_app()
                app.original = None
                error = RuntimeError('retained synthetic failure')
                contexts = []
                snapshots = []
                real_draw = ImageDraw.Draw
                def draw(image, *args, **kwargs):
                    context = real_draw(image, *args, **kwargs)
                    contexts.append(context)
                    snapshots.append(image)
                    self.addCleanup(image.close)
                    if stage == 'paint':
                        context.rectangle = Mock(side_effect=error)
                    return context
                local.enter_context(patch('PIL.ImageDraw.Draw', side_effect=draw))
                if stage == 'start':
                    local.enter_context(patch.object(worker_fixtures.DeferredThread, 'start', side_effect=error))
                try:
                    app.run_performance_benchmark()
                except RuntimeError as failure:
                    self.assertIs(failure, error)
                else:
                    self.fail('The injected synthetic failure did not reach the caller.')
                self.assertIsNotNone(error.__traceback__)
                self.assertEqual(len(snapshots), 1)
                self.assert_closed(snapshots[0])
                for name in ('draw', 'im', '_image'):
                    self.assertIsNone(getattr(contexts[0], name))

    def test_rejected_or_failed_worker_start_closes_the_performance_snapshot(self):
        for stage in ('rejected', 'window', 'constructor', 'start'):
            with self.subTest(stage=stage), ExitStack() as local:
                app = self.new_app()
                if stage == 'rejected':
                    local.enter_context(patch.object(app, 'begin_worker', return_value=False))
                    self.assertFalse(app.run_performance_benchmark())
                else:
                    target = {'window': 'ScreenTaskWindow.ScreenTaskWindow',
                              'constructor': 'DrawBot.threading.Thread',
                              'start': 'test_v148_application_batch14_browser_start.DeferredThread.start'}[stage]
                    local.enter_context(patch(target, side_effect=RuntimeError('startup failure')))
                    with self.assertRaisesRegex(RuntimeError, 'startup failure'):
                        app.run_performance_benchmark()
                self.assertEqual(len(app.snapshots), 1)
                self.assert_closed(app.snapshots[0])
                self.assertEqual(app.original.getpixel((0, 0)), (255, 0, 0, 255))


class BenchmarkRunnerImageOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.images = []
        self.plans = []
        self.fixtures = []
        self.before_fixture = None
        self.stop = threading.Event()
        self.failure = None
        self.stop_after_plan = False
        self.transfer_source = False

    def image(self, color='red'):
        image = Image.new('RGBA', (8, 6), color)
        self.images.append(image)
        self.addCleanup(image.close)
        return image

    def fixture(self, *args):
        if self.before_fixture is not None:
            self.before_fixture()
        image = self.image()
        self.fixtures.append(image)
        return image

    def plan(self, image, target, options, cancelled):
        owned = [self.image(color) for color in ('green', 'blue', 'white', 'black')]
        plan = {'image': image if self.transfer_source else owned[0], 'preview': owned[1],
                'ui_previews': {'color': owned[1], 'diagnostic': owned[2]},
                'options': dict(options, _accuracy_original_source=owned[3]),
                'source_count': 4, 'count': 2, 'estimate': 1., 'colors': [(0, 0, 0)]}
        if self.transfer_source:
            # Only the three buffers actually transferred into the plan are
            # owned by the runner; this unused test allocation is irrelevant.
            owned[0].close()
        if self.failure is not None:
            failure = self.failure
            class BadCount:
                def __int__(self):
                    raise failure
            plan['count'] = BadCount()
        self.plans.append((plan, owned))
        if self.stop_after_plan:
            self.stop.set()
        return plan

    def run_runner(self, name):
        if name == 'suite':
            import BenchmarkSuite
            with patch.object(BenchmarkSuite, 'CASES', (('first', self.fixture), ('second', self.fixture))):
                return BenchmarkSuite.run(self.plan, {}, cancelled=self.stop.is_set)
        import GoldenImageRegression
        with patch.object(GoldenImageRegression, 'load_golden_image', side_effect=self.fixture):
            return GoldenImageRegression.run(self.plan, {}, cases=GoldenImageRegression.GOLDEN_CASES[:2],
                                             ensure_assets=False, cancelled=self.stop.is_set)

    def assert_closed(self, image):
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def reset_case(self):
        self.plans = []
        self.fixtures = []
        self.stop.clear()

    def test_previous_plan_is_released_before_the_next_fixture_is_allocated(self):
        for runner in ('suite', 'golden'):
            with self.subTest(runner=runner):
                self.reset_case()
                def check_previous():
                    if self.plans:
                        for image in self.plans[-1][1]:
                            self.assert_closed(image)
                self.before_fixture = check_previous
                result = self.run_runner(runner)
                self.assertEqual(result['case_count'], 2)
                self.assertEqual([row['planned_paths'] for row in result['rows']], [2, 2])
                for _plan, owned in self.plans:
                    for image in owned:
                        self.assert_closed(image)

    def test_summary_failure_releases_buffers_even_when_its_traceback_stays_alive(self):
        for runner in ('suite', 'golden'):
            with self.subTest(runner=runner):
                self.reset_case()
                self.failure = RuntimeError('retained row failure')
                try:
                    self.run_runner(runner)
                except RuntimeError as error:
                    self.assertIs(error, self.failure)
                else:
                    self.fail('The injected row failure did not reach the caller.')
                self.assertIsNotNone(self.failure.__traceback__)
                for image in self.fixtures + self.plans[0][1]:
                    self.assert_closed(image)

    def test_post_planner_cancellation_releases_the_unpublished_plan(self):
        for runner in ('suite', 'golden'):
            with self.subTest(runner=runner):
                self.reset_case()
                self.stop_after_plan = True
                with self.assertRaises(InterruptedError):
                    self.run_runner(runner)
                for image in self.fixtures + self.plans[0][1]:
                    self.assert_closed(image)

    def test_source_aliases_and_preview_aliases_are_released_after_summary(self):
        for runner in ('suite', 'golden'):
            with self.subTest(runner=runner):
                self.reset_case()
                self.transfer_source = True
                result = self.run_runner(runner)
                self.assertEqual(result['case_count'], 2)
                for image in self.fixtures:
                    self.assert_closed(image)
                for _plan, owned in self.plans:
                    for image in owned:
                        self.assert_closed(image)


if __name__ == '__main__':
    unittest.main()
