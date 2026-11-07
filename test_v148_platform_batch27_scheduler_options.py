"""The UI and public planner validate recommendations for the same RAM policy."""
from contextlib import ExitStack, closing, contextmanager
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import tempfile
from types import MethodType
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import Colors
import CrashDiagnostics
import DrawBot
import DrawTimeCalibration
import ResourceAllocation as allocation
import ResourceScheduler as scheduler
from PixelData import closest_color
from test_precision_v102 import Value
import test_v148_ui_batch07_renderer as renderer_fixture


@contextmanager
def recommendation_case(*, saved_ram=4096, selected_ram='8 GB', current_cpus=16,
                        available=32768, workers='Auto', mode='Auto'):
    """Real file IO, allocation, controller options and two public plan routes."""
    previous_palette = list(Colors.allColors)
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch.dict(os.environ))
        stack.enter_context(patch('RuntimePaths.source_dir', return_value=root))
        stack.enter_context(patch.object(scheduler, 'SCHEDULER_FILE', root / 'scheduler.json'))
        stack.enter_context(patch.object(DrawTimeCalibration, 'FILE', root / 'timing.json'))
        stack.enter_context(patch.object(allocation, 'logical_cpu_count', return_value=current_cpus))
        memory_probe = stack.enter_context(patch.object(allocation, 'available_ram_mb', return_value=available))
        for name, value in (('LOG_DIR', root / 'logs'),
                            ('SESSION_LOG', root / 'logs/session.log'),
                            ('DEBUG_ERROR_LOG', root / 'logs/errors.log')):
            stack.enter_context(patch.object(CrashDiagnostics, name, value))
        stack.enter_context(patch.object(DrawBot, 'custom_rgb_available', return_value=False))
        path = root / 'palette.json'
        Colors.save_calibration([(10, 10), (20, 10), (30, 10)],
            [(0, 0, 0), (190, 50, 50), (255, 255, 255)], path,
            profile_key='generic', state='calibrated')
        Colors.load_calibration(path, profile_key='generic')
        try:
            saved = scheduler.save_recommendation({
                'logical_cpus': 16, 'ram_budget_mb': saved_ram,
                'recommended_workers': 1, 'recommended_engine': 'Threads',
                'best_score': 1.0, 'scores': [],
            })
            app = renderer_fixture.AdvertisedRendererTests().app('Other drawing app')
            app.render_style.set('Standard / pixel')
            app.cpu_workers.set(workers)
            app.resource_scheduler.set(mode)
            app.ram_budget = Value(selected_ram)
            app.calibration_path = path
            app.corners = [(0, 0), (96, 64)]
            app.area = MethodType(DrawBot.DrawBotApp.area, app)
            options = DrawBot.DrawBotApp.options(app)
            option_memory_probes = memory_probe.call_count
            reference = deepcopy(options)
            reference.pop('resource_scheduler_plan')
            expected = scheduler.resolve_resource_schedule(reference, mode=mode,
                area=(96, 64), drawing_mode=options['drawing_mode'],
                gpu_mode='CPU', gpu_available=False, preview=False)
            with closing(Image.new('RGB', (96, 64), 'white')) as source:
                ImageDraw.Draw(source).rectangle((12, 8, 81, 55), fill=(190, 50, 50))
                ImageDraw.Draw(source).line((15, 12, 77, 50), fill='black', width=2)
                source_before = source.tobytes()
                plans = []
                try:
                    plans.append(DrawBot.make_plan(source, source.size, options))
                    plans.append(DrawBot.make_plan(source, source.size, reference))
                    yield dict(saved=saved, options=options, expected=expected,
                        plans=plans, option_memory_probes=option_memory_probes,
                        source_unchanged=source.tobytes() == source_before)
                finally:
                    for plan in plans:
                        renderer_fixture.close_images(plan)
        finally:
            Colors.allColors[:] = previous_palette
            closest_color.cache_clear()


def observable_summary(case):
    plans = case['plans']
    return dict(
        saved_signature=case['saved']['machine_signature'],
        current_signature=scheduler.machine_signature(
            logical_cpus=case['options']['logical_cpus'],
            ram_mb=case['options']['ram_budget_mb']),
        option_memory_probes=case['option_memory_probes'],
        ui_schedule=case['options']['resource_scheduler_plan'],
        expected_schedule=case['expected'],
        plans=[dict(schedule=plan['options']['resource_scheduler_plan'],
                    count=plan['count'], estimate=plan['estimate'],
                    preview_sha256=hashlib.sha256(plan['preview'].tobytes()).hexdigest())
               for plan in plans],
        geometry_equal=plans[0]['groups'] == plans[1]['groups'],
        source_unchanged=case['source_unchanged'])


class SchedulerOptionsTests(unittest.TestCase):
    def assert_consistent(self, case):
        self.assertEqual(case['option_memory_probes'], 1)
        self.assertTrue(case['source_unchanged'])
        expected = case['expected']
        self.assertEqual(case['options']['resource_scheduler_plan'], expected)
        for plan in case['plans']:
            actual = dict(plan['options']['resource_scheduler_plan'])
            actual.pop('preview', None)  # The public rescheduler explicitly records it.
            self.assertEqual(actual, expected)
        first, second = case['plans']
        self.assertEqual(first['groups'], second['groups'])
        self.assertEqual(first['count'], second['count'])
        self.assertEqual(first['estimate'], second['estimate'])
        self.assertEqual(first['preview'].tobytes(), second['preview'].tobytes())

    def test_changed_ram_rejects_old_record_in_both_automatic_scheduler_modes(self):
        for mode in ('Auto', 'Benchmark recommendations'):
            for saved_ram, selected in ((4096, '8 GB'), (8192, '4 GB')):
                with self.subTest(mode=mode, saved_ram=saved_ram, selected=selected):
                    with recommendation_case(mode=mode, saved_ram=saved_ram, selected_ram=selected) as case:
                        self.assert_consistent(case)
                        self.assertEqual(case['expected']['worker_reason'], 'auto safe cap')
                        self.assertEqual(case['expected']['base_workers'], 10)

    def test_unchanged_ram_keeps_saved_worker_choice(self):
        for mode in ('Auto', 'Benchmark recommendations'):
            with self.subTest(mode=mode), recommendation_case(mode=mode, selected_ram='4 GB') as case:
                self.assert_consistent(case)
                self.assertEqual(case['expected']['base_workers'], 1)
                self.assertIn('saved', case['expected']['worker_reason'])

    def test_current_capacity_and_effective_headroom_remain_authoritative(self):
        for changes in ({'current_cpus': 8, 'selected_ram': '4 GB'},
                        {'available': 2048, 'selected_ram': '4 GB'}):
            with self.subTest(changes=changes), recommendation_case(**changes) as case:
                self.assert_consistent(case)
                self.assertNotIn('saved', case['expected']['worker_reason'])
                if 'available' in changes:
                    self.assertEqual(case['options']['ram_budget_mb'], 1536)

    def test_manual_workers_and_disabled_scheduler_keep_their_existing_policy(self):
        for changes, reason in (({'workers': '4'}, 'manual worker setting'),
                                ({'mode': 'Off'}, 'scheduler off')):
            with self.subTest(changes=changes), recommendation_case(**changes) as case:
                self.assert_consistent(case)
                self.assertEqual(case['expected']['worker_reason'], reason)


if __name__ == '__main__':
    unittest.main()
