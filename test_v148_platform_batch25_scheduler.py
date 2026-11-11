"""Scheduler recommendations require completed, verified executor work."""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import ResourceAllocation as allocation
import ResourceScheduler as scheduler


RESOURCE_WORKER = allocation._resource_benchmark_worker
ALLOCATION = {'logical_cpus': 4, 'cpu_workers': 'Auto', 'cpu_engine': 'Threads',
              'cpu_workers_resolved': 2, 'ram_budget_mb': 512}


def observed_process_worker(task):
    result = RESOURCE_WORKER(task)
    # Different processes must not append records to the same observation file.
    # Each worker owns its marker until the benchmark joins every executor.
    pid = str(os.getpid())
    path = Path(os.environ['DRAWBOT_SCHEDULER_TEST_PIDS']) / (pid + '.pid')
    path.write_text(pid, encoding='ascii')
    return result


class MeasuredSchedulerTests(unittest.TestCase):
    def test_real_threads_receive_identical_complete_payloads_for_each_candidate(self):
        submitted = []
        thread_ids = set()
        lock = threading.Lock()
        class ObservedPool(ThreadPoolExecutor):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.tasks = []
                submitted.append(self.tasks)
            def submit(self, function, task):
                self.tasks.append(task)
                return super().submit(function, task)
        def worker(task):
            with lock:
                thread_ids.add(threading.get_ident())
            return RESOURCE_WORKER(task)
        with patch.object(allocation, 'ThreadPoolExecutor', ObservedPool), \
             patch.object(allocation, '_resource_benchmark_worker', new=worker):
            result = scheduler.benchmark_scheduler(ALLOCATION, loops_per_worker=1000, save=False)
        self.assertTrue(submitted, 'No thread executor performed the claimed worker measurement')
        self.assertTrue(thread_ids - {threading.get_ident()})
        self.assertTrue(all(tasks == submitted[0] for tasks in submitted))
        self.assertEqual(len(submitted[0]), result['benchmark_tasks'])
        iterations = sum(task[1] for task in submitted[0])
        self.assertEqual(iterations, result['benchmark_iterations'])
        for score in result['scores']:
            self.assertEqual(score['iterations'], iterations)
            self.assertGreater(score['elapsed_ms'], 0)
            self.assertEqual(len(score['samples_ms']), 2)
            self.assertEqual(score['score'], round(iterations / (score['elapsed_ms'] * 1000), 3))

    def test_process_candidate_uses_real_spawn_children_and_joins_them(self):
        pools = []
        before = {child.pid for child in multiprocessing.active_children()}
        def factory(**kwargs):
            pool = ProcessPoolExecutor(mp_context=multiprocessing.get_context('spawn'), **kwargs)
            pools.append(pool)
            return pool
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch.dict(os.environ, {'DRAWBOT_SCHEDULER_TEST_PIDS': str(path)}), \
                 patch.object(allocation, 'ProcessPoolExecutor', new=factory), \
                 patch.object(allocation, '_resource_benchmark_worker', new=observed_process_worker):
                result = scheduler.benchmark_scheduler(dict(ALLOCATION, cpu_engine='Processes'),
                                                       loops_per_worker=1000, save=False)
            self.assertTrue(pools, 'The Processes recommendation did not run a process executor')
            markers = list(path.iterdir())
            self.assertTrue(markers, 'No completed worker recorded its process identity')
            pids = set()
            for marker in markers:
                value = marker.read_text(encoding='ascii')
                pid = int(value)
                self.assertGreater(pid, 0)
                self.assertEqual(value, str(pid))
                self.assertEqual(marker.name, str(pid) + '.pid')
                pids.add(pid)
            self.assertTrue(pids - {os.getpid()})
        self.assertEqual(result['recommended_engine'], 'Processes')
        self.assertTrue(any(score['backend'] == 'processes' for score in result['scores']))
        self.assertFalse({child.pid for child in multiprocessing.active_children()} - before)

    def test_elapsed_measurement_includes_submission_collection_and_shutdown(self):
        events = []
        clock = time.perf_counter
        class ObservedPool(ThreadPoolExecutor):
            def __init__(self, **kwargs):
                events.append('construct')
                super().__init__(**kwargs)
            def submit(self, *args, **kwargs):
                events.append('submit')
                return super().submit(*args, **kwargs)
            def shutdown(self, *args, **kwargs):
                super().shutdown(*args, **kwargs)
                events.append('joined')
        def measured_clock():
            events.append('clock')
            return clock()
        with patch.object(allocation, 'ThreadPoolExecutor', ObservedPool), \
             patch.object(scheduler.time, 'perf_counter', new=measured_clock):
            scheduler.benchmark_scheduler(ALLOCATION, loops_per_worker=1000, save=False)
        self.assertIn('joined', events)
        for index, event in enumerate(events):
            if event == 'construct':
                self.assertEqual(events[index-1], 'clock')
            if event == 'joined':
                self.assertEqual(events[index+1], 'clock')

    def test_wrong_parallel_results_are_not_accepted_as_fast_recommendations(self):
        class CorruptPool(ThreadPoolExecutor):
            def submit(self, function, task):
                return super().submit(lambda: function(task) ^ 1)
        with patch.object(allocation, 'ThreadPoolExecutor', CorruptPool):
            result = scheduler.benchmark_scheduler(ALLOCATION, loops_per_worker=1000, save=False)
        failed = [score for score in result['scores'] if score.get('error')]
        self.assertTrue(failed, 'Incorrect parallel work was not rejected')
        self.assertEqual(result['recommended_workers'], 1)
        self.assertTrue(all(score['score'] == 0 for score in failed))

    def test_stop_from_an_actual_worker_preserves_the_old_profile_and_joins(self):
        joined = []
        class InterruptedPool(ThreadPoolExecutor):
            def submit(self, function, task):
                def interrupted():
                    function(task)
                    raise InterruptedError('Stop from a completed worker')
                return super().submit(interrupted)
            def shutdown(self, *args, **kwargs):
                super().shutdown(*args, **kwargs)
                joined.append(True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scheduler.json'
            path.write_bytes(b'previous completed recommendation')
            with patch.object(allocation, 'ThreadPoolExecutor', InterruptedPool):
                with self.assertRaises(InterruptedError):
                    scheduler.benchmark_scheduler(ALLOCATION, loops_per_worker=1000, path=path)
            self.assertEqual(path.read_bytes(), b'previous completed recommendation')
            self.assertTrue(joined)

    def test_late_stop_after_executor_exit_prevents_publication(self):
        stop = threading.Event()
        class StoppedPool(ThreadPoolExecutor):
            def shutdown(self, *args, **kwargs):
                super().shutdown(*args, **kwargs)
                stop.set()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scheduler.json'
            path.write_bytes(b'previous completed recommendation')
            with patch.object(allocation, 'ThreadPoolExecutor', StoppedPool):
                with self.assertRaises(InterruptedError):
                    scheduler.benchmark_scheduler(ALLOCATION, loops_per_worker=1000,
                                                   path=path, cancelled=stop.is_set)
            self.assertEqual(path.read_bytes(), b'previous completed recommendation')

    def test_previous_serial_proxy_profile_is_not_used_as_measured_evidence(self):
        legacy = {'version': 2, 'logical_cpus': 4, 'recommended_workers': 2,
                  'recommended_engine': 'Threads', 'ram_budget_mb': 512,
                  'machine_signature': scheduler.machine_signature(logical_cpus=4, ram_mb=512),
                  'best_score': 10.0, 'scores': [{'workers': 2, 'score': 10.0}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scheduler.json'
            path.write_text(json.dumps(legacy), encoding='utf-8')
            self.assertIsNone(scheduler.load_recommendation(path, signature=legacy['machine_signature']))


if __name__ == '__main__':
    unittest.main()
