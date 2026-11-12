"""Measured worker counts belong to the executor that actually ran them."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ResourceScheduler as scheduler


class SchedulerExecutorIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'scheduler.json'
        self.location = patch.object(scheduler, 'SCHEDULER_FILE', self.path)
        self.location.start()
        self.addCleanup(self.location.stop)
        self.allocation = dict(cpu_workers='Auto', cpu_workers_resolved=6,
            logical_cpus=8, cpu_engine='Threads', ram_budget_mb=1024,
            available_ram_mb=8192)

    def save(self, engine='Threads', workers=1):
        return scheduler.save_recommendation(dict(logical_cpus=8,
            recommended_workers=workers, recommended_engine=engine,
            ram_budget_mb=1024, best_score=4.2, scores=[],
            machine_signature=scheduler.machine_signature(logical_cpus=8, ram_mb=1024)), self.path)

    def schedule(self, engine, *, mode='Auto', **options):
        allocation = dict(self.allocation, cpu_engine=engine, **options)
        return scheduler.resolve_resource_schedule(allocation, mode=mode,
            area=(1000, 1000), gpu_mode='CPU')

    def test_persisted_thread_result_cannot_force_process_planning_into_serial_work(self):
        self.save('Threads', 1)
        before = self.path.read_bytes()
        result = self.schedule('Processes')
        self.assertEqual(result['recommended_engine'], 'Processes')
        self.assertEqual(result['base_workers'], 6)
        self.assertEqual(result['phases']['connected_components']['workers'], 6)
        self.assertEqual(self.path.read_bytes(), before)

    def test_persisted_process_result_cannot_choose_threads_or_auto_workers(self):
        self.save('Processes', 1)
        for engine in ('Threads', 'Auto'):
            for mode in ('Auto', 'Benchmark recommendations'):
                with self.subTest(engine=engine, mode=mode):
                    result = self.schedule(engine, mode=mode)
                    self.assertEqual(result['recommended_engine'], 'Threads')
                    self.assertEqual(result['base_workers'], 6)

    def test_auto_and_threads_are_the_same_effective_executor(self):
        for measured in ('Threads', 'Auto'):
            self.save(measured, 2)
            for requested in ('Threads', 'Auto'):
                with self.subTest(measured=measured, requested=requested):
                    result = self.schedule(requested)
                    self.assertEqual(result['base_workers'], 2)
                    self.assertIn('saved benchmark', result['worker_reason'])

    def test_matching_process_result_keeps_the_existing_safety_and_preview_caps(self):
        self.save('Processes', 8)
        result = self.schedule('Processes')
        self.assertEqual(result['base_workers'], 6)
        result = scheduler.resolve_resource_schedule(dict(self.allocation, cpu_engine='Processes'),
            area=(1000, 1000), preview=True, gpu_mode='CPU')
        self.assertEqual(result['base_workers'], 4)

    def test_explicit_recommendations_also_require_executor_evidence(self):
        complete = self.save('Threads', 1)
        for record in (complete, {'recommended_workers': 1},
                       dict(complete, recommended_engine='Unknown'),
                       dict(complete, recommended_engine=None)):
            with self.subTest(record=record):
                workers, _ = scheduler.recommended_workers(
                    dict(self.allocation, cpu_engine='Processes'), recommendation=record)
                self.assertEqual(workers, 6)

    def test_manual_workers_and_disabled_scheduler_keep_their_existing_authority(self):
        self.save('Threads', 1)
        self.assertEqual(self.schedule('Processes', cpu_workers='3')['base_workers'], 3)
        self.assertEqual(self.schedule('Processes', mode='Off', cpu_workers_resolved=5)['base_workers'], 5)

    def test_legacy_serial_proxy_profile_stays_ignored_without_rewriting_it(self):
        record = self.save('Threads', 1)
        record['version'] = 2
        self.path.write_text(json.dumps(record), encoding='utf-8')
        before = self.path.read_bytes()
        self.assertEqual(self.schedule('Threads')['base_workers'], 6)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
