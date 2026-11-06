"""Stop and owned-buffer contracts for actual benchmark/preprocessing paths."""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock
import weakref

import numpy as np
from PIL import Image

import GpuAcceleration as ga
import ResourceAllocation as allocation
import ResourceScheduler as scheduler
from test_gpu_execution_regressions import FakeCupy


class PlatformCancellationTests(unittest.TestCase):
    def gpu_context(self, *, copied=None, tiled=False):
        stack = ExitStack()
        self.addCleanup(stack.close)
        cp = FakeCupy()
        if copied is not None:
            cp.asnumpy = copied
        cnd = SimpleNamespace(gaussian_filter=lambda value, **kwargs: value.copy())
        info = ga.AccelerationInfo("Auto", "CUDA", True, "Fake GPU", 4096, 2048,
                                   vram_budget_mb=1024)
        stack.enter_context(mock.patch.object(ga, "_resolve_backend", return_value=("CUDA", (cp, cnd))))
        stack.enter_context(mock.patch.object(ga, "acceleration_info", return_value=info))
        stack.enter_context(mock.patch.object(ga, "plan_vram_allocation", return_value={
            "mode": "tiled" if tiled else "full", "tile_rows": 2, "workspace_mb": 1}))
        def enhance(_grid, _block, args):
            args[2][...] = args[0]
        stack.enter_context(mock.patch.object(ga, "_kernels", return_value=(enhance, None)))
        return cp, info

    def test_pinned_and_ordinary_uploads_finish_before_host_owner_expires(self):
        class Pinned(bytearray):
            pass
        owners = []
        def allocate(size):
            value = Pinned(size)
            owners.append(weakref.ref(value))
            return value
        calls = []
        def upload(value, dtype=None, *, blocking=False):
            calls.append(blocking)
            self.assertTrue(blocking, "asynchronous upload could outlive its private host owner")
            return np.array(value, dtype=dtype, copy=True)
        cp = SimpleNamespace(cuda=SimpleNamespace(alloc_pinned_memory=allocate),
                             float32=np.float32, asarray=upload)
        with Image.new("L", (7, 3), 91) as image:
            for mode in ("Balanced", "High throughput"):
                np.testing.assert_array_equal(ga._upload_gray(cp, image, mode), np.full((3, 7), 91))
        self.assertEqual(calls, [True, True])
        self.assertTrue(owners and all(owner() is None for owner in owners))

    def test_pre_cancel_avoids_driver_discovery_and_image_allocation(self):
        with mock.patch.object(ga, "_resolve_backend") as backend, \
             mock.patch.object(ga, "_benchmark_image") as stimulus:
            with self.assertRaises(InterruptedError):
                ga.benchmark(cancelled=lambda: True)
            with Image.new("L", (8, 8)) as image, self.assertRaises(InterruptedError):
                ga.enhance_portrait(image, .4, 1, False, 0, cancelled=lambda: True)
        backend.assert_not_called()
        stimulus.assert_not_called()

    def test_late_full_frame_stop_closes_result_and_releases_session(self):
        stopped = [False]
        def copied(value):
            stopped[0] = True
            return np.array(value, copy=True)
        self.gpu_context(copied=copied)
        sessions, images = [], []
        original_session = ga.GpuAnalysisSession
        class CapturedSession(original_session):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                sessions.append(self)
        original_fromarray = Image.fromarray
        def capture_image(*args, **kwargs):
            value = original_fromarray(*args, **kwargs)
            images.append(value)
            return value
        source = Image.new("L", (8, 8), 91)
        self.addCleanup(source.close)
        with mock.patch.object(ga, "GpuAnalysisSession", CapturedSession), \
             mock.patch.object(Image, "fromarray", side_effect=capture_image):
            with self.assertRaises(InterruptedError):
                ga.enhance_portrait(source, .4, 1, False, 0,
                                    performance="High throughput", cancelled=lambda: stopped[0])
        self.assertEqual(len(sessions), 1)
        self.assertIsNone(sessions[0].arr)
        with self.assertRaises(ValueError):
            images[0].getpixel((0, 0))
        self.assertEqual(source.getpixel((0, 0)), 91)

    def test_tile_stop_does_not_run_remaining_tiles_or_disable_driver(self):
        stopped, copies = [False], []
        def copied(value):
            copies.append(True)
            stopped[0] = True
            return np.array(value, copy=True)
        self.gpu_context(copied=copied, tiled=True)
        with mock.patch.object(ga, "_DISABLED_REASON", ""), Image.new("L", (8, 20)) as image:
            with self.assertRaises(InterruptedError):
                ga.enhance_portrait(image, .4, 1, False, 0,
                                    performance="High throughput", cancelled=lambda: stopped[0])
            self.assertEqual(ga._DISABLED_REASON, "")
        self.assertEqual(len(copies), 1)

    def test_cpu_and_failed_gpu_benchmark_never_claim_noop_throughput(self):
        with mock.patch.object(ga, "_benchmark_image") as stimulus:
            result = ga.benchmark("CPU", 4096)
            self.assertEqual(result["throughput_mp_s"], 0)
            stimulus.assert_not_called()
        info = ga.AccelerationInfo("Auto", "CUDA", True)
        image = Image.new("L", (256, 256))
        with mock.patch.object(ga, "acceleration_info", return_value=info), \
             mock.patch.object(ga, "_benchmark_image", return_value=image), \
             mock.patch.object(ga, "enhance_portrait", return_value=(None, info, None)):
            result = ga.benchmark()
        self.assertFalse(result["used_gpu"])
        self.assertEqual(result["throughput_mp_s"], 0)
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))

    def test_benchmark_interruption_releases_all_owned_images_and_session(self):
        info = ga.AccelerationInfo("Auto", "CUDA", True)
        source, enhanced, session = Image.new("L", (256, 256)), Image.new("L", (256, 256)), object()
        callback = lambda: False
        with mock.patch.object(ga, "acceleration_info", return_value=info), \
             mock.patch.object(ga, "_benchmark_image", return_value=source), \
             mock.patch.object(ga, "enhance_portrait", return_value=(enhanced, info, session)) as enhance, \
             mock.patch.object(ga, "saliency", side_effect=InterruptedError) as analyze, \
             mock.patch.object(ga, "release_analysis_session") as release:
            with self.assertRaises(InterruptedError):
                ga.benchmark(cancelled=callback)
        self.assertIs(enhance.call_args.kwargs["cancelled"], callback)
        self.assertIs(analyze.call_args.kwargs["cancelled"], callback)
        release.assert_called_once_with(session, trim_cache=False)
        for image in (source, enhanced):
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))

    def test_vector_stimulus_matches_old_pixels_and_stops_between_row_chunks(self):
        size = 129
        expected = bytes((x * 17 + y * 31 + (x ^ y)) % 256 for y in range(size) for x in range(size))
        image = ga._benchmark_image(size)
        try:
            self.assertEqual(image.tobytes(), expected)
        finally:
            image.close()
        checks = []
        def cancelled():
            checks.append(True)
            return len(checks) == 2
        with self.assertRaises(InterruptedError):
            ga._benchmark_image(4096, cancelled=cancelled)
        self.assertEqual(len(checks), 2)

    def test_allocation_stop_uses_parallel_map_before_next_task(self):
        stopped, tasks = [False], []
        def worker(task):
            tasks.append(task)
            stopped[0] = True
            return 42
        with mock.patch.object(allocation, "choose_parallel_backend", return_value="serial"), \
             mock.patch.object(allocation, "_resource_benchmark_worker", side_effect=worker):
            with self.assertRaises(InterruptedError):
                allocation.benchmark_allocation("2", "Threads", "512 MB", "4096",
                                                loops_per_worker=1000, cancelled=lambda: stopped[0])
        self.assertEqual(len(tasks), 1)

    def test_scheduler_cancel_in_workload_preserves_saved_recommendation(self):
        checks = []
        def cancelled():
            checks.append(True)
            return len(checks) == 4
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scheduler.json"
            path.write_text("old recommendation")
            with self.assertRaises(InterruptedError):
                scheduler.benchmark_scheduler({"logical_cpus": 4}, loops_per_worker=10_000,
                                               path=path, cancelled=cancelled)
            self.assertEqual(path.read_text(), "old recommendation")
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
