import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import weakref

import numpy as np

import UniversalHardwareBenchmark as bench
import PerformanceAutoTuner as tuner
import ResourceScheduler as scheduler
import RuntimePaths


class NumpyCuda:
    __version__ = "synthetic"

    def __init__(self, *, bad=False, clock=None, stopped=None):
        self.bad=bad;self.clock=clock or [0.0];self.stopped=stopped
        self.uploads=[];self.downloads=[];self.references=[];self.trims=0
        self.cuda=SimpleNamespace(Device=lambda _i: mock.MagicMock(), runtime=SimpleNamespace(
            getDeviceCount=lambda: 1,getDeviceProperties=lambda _i:{"name":b"Synthetic CUDA","multiProcessorCount":4},
            memGetInfo=lambda:(1024**3,2*1024**3)))

    def __getattr__(self, name):
        return getattr(np,name)

    def asarray(self, value, dtype=None):
        result=np.array(value,dtype=dtype,copy=True)
        self.references.append(weakref.ref(result));self.uploads.append(result.shape);self.clock[0]+=.01
        return result

    def asnumpy(self, value):
        self.downloads.append(value.shape);self.clock[0]+=.02
        if self.stopped is not None:self.stopped[0]=True
        if self.bad:return np.full(value.shape,np.nan,dtype=np.float32)
        return np.array(value,copy=True)

    def get_default_memory_pool(self):
        def trim():
            self.trims+=1
            if any(reference() is not None for reference in self.references):
                raise AssertionError("benchmark device inputs are still live")
        return SimpleNamespace(free_all_blocks=trim)


class NumpyOpenCL:
    device_type=SimpleNamespace(GPU=1)
    mem_flags=SimpleNamespace(READ_ONLY=1,WRITE_ONLY=2,COPY_HOST_PTR=4)

    def __init__(self, *, bad=False, broken_metadata=False):
        self.bad=bad;self.uploads=0;self.downloads=0
        good=SimpleNamespace(name="Synthetic GPU",vendor="AMD",global_mem_size=1024**3,
                             max_compute_units=4,host_unified_memory=False,version="synthetic",driver_version="test")
        class Broken:
            @property
            def name(self):raise RuntimeError("adapter disconnected")
        self.devices=([Broken()] if broken_metadata else [])+[good]

    def get_platforms(self):return [SimpleNamespace(get_devices=lambda **kwargs:self.devices)]
    def Context(self, **kwargs):return SimpleNamespace(**kwargs)
    def CommandQueue(self, _ctx):return SimpleNamespace(finish=lambda:None)
    def Buffer(self, _ctx, _flags, size=None, hostbuf=None):
        return SimpleNamespace(data=None if hostbuf is None else np.array(hostbuf,copy=True))
    def enqueue_copy(self, _queue, destination, source, **kwargs):
        if isinstance(destination,np.ndarray):
            self.downloads+=1
            np.copyto(destination,np.asarray(source.data).reshape(destination.shape))
        else:
            self.uploads+=1
            destination.data=np.array(source,copy=True)

    def Program(self, _ctx, _source):
        def oklab(_queue,_shape,_local,src,dst,_n):
            data=np.ones_like(src.data)
            data[:,:3]=bench._srgb_to_oklab_np(src.data[:,:3])
            if self.bad:data[:,:3]=np.nan
            dst.data=data
        def palette(_queue,_shape,_local,src,pal,dst,_n,_count):
            delta=src.data[:,:3,None]-pal.data[:,:3].T[None,:,:]
            dst.data=np.argmin(np.sum(delta*delta,axis=1),axis=1).astype(np.uint16)
        def edge(_queue,_shape,_local,src,dst,width,height):
            dst.data=bench.luminance_edges(src.data.reshape(int(height),int(width))).ravel()
        def bulk(_queue,_shape,_local,src,dst,_n):
            value=src.data
            dst.data=((value*.731+.117)*(1-value*.213)+np.sqrt(value+.001)).astype(np.float32)
        value=SimpleNamespace(imagedrawbot_oklabish=oklab,imagedrawbot_palette=palette,
                              imagedrawbot_edge=edge,imagedrawbot_bulk=bulk)
        value.build=lambda **kwargs:value
        return value


class BenchmarkEvidenceTests(unittest.TestCase):
    def test_cuda_times_full_upload_and_download_and_releases_inputs(self):
        clock=[0.0];cp=NumpyCuda(clock=clock)
        with mock.patch.dict(sys.modules,{"cupy":cp}), mock.patch.object(bench.time,"perf_counter",side_effect=lambda:clock[0]):
            scores=bench.benchmark_cuda(size=32,repeats=1)
        self.assertEqual(len(scores),4)
        self.assertTrue(all(not score.error and score.elapsed_ms>=30 for score in scores))
        self.assertEqual(len(cp.downloads),8)
        self.assertEqual(set(cp.downloads),{(32,32,3),(1024,),(32,32)})
        self.assertEqual(len(cp.uploads),10)
        self.assertEqual(cp.trims,1)
        self.assertTrue(all(reference() is None for reference in cp.references))

    def test_bad_gpu_arithmetic_never_becomes_a_successful_score(self):
        for name,backend,function in (("cupy",NumpyCuda(bad=True),bench.benchmark_cuda),
                                      ("pyopencl",NumpyOpenCL(bad=True),bench.benchmark_opencl)):
            with self.subTest(backend=name), mock.patch.dict(sys.modules,{name:backend}):
                scores=function(size=32,repeats=1)
            self.assertEqual(len(scores),1)
            self.assertEqual(scores[0].workload,"probe")
            self.assertTrue(scores[0].error)

    def test_opencl_includes_each_input_transfer_and_continues_after_bad_metadata(self):
        cl=NumpyOpenCL(broken_metadata=True)
        with mock.patch.dict(sys.modules,{"pyopencl":cl}):
            scores=bench.benchmark_opencl(size=32,repeats=1)
        self.assertEqual(len(scores),5)
        self.assertTrue(scores[0].error)
        self.assertTrue(all(not score.error and score.backend_id=="opencl:0:1" for score in scores[1:]))
        self.assertEqual((cl.uploads,cl.downloads),(10,8))

    def test_direct_benchmark_parameters_match_actual_array_size_and_are_bounded(self):
        scores=bench.benchmark_cpu(size=1,repeats=0)
        self.assertTrue(all(score.size==32 and score.pixels==1024 for score in scores))
        self.assertEqual(bench._benchmark_parameters(10**100,10**100),(1024,5))
        for size,repeats in ((True,1),(32,False),(32.1,2),(32,float("inf"))):
            with self.subTest(size=size,repeats=repeats),self.assertRaises(ValueError):
                bench._benchmark_parameters(size,repeats)

    def test_cancelled_cuda_probe_propagates_and_trims_workload_buffers(self):
        stopped=[False];cp=NumpyCuda(stopped=stopped)
        with mock.patch.dict(sys.modules,{"cupy":cp}),self.assertRaises(InterruptedError):
            bench.benchmark_cuda(size=32,repeats=1,cancelled=lambda:stopped[0])
        self.assertEqual(cp.trims,1)
        self.assertTrue(all(reference() is None for reference in cp.references))

    def test_mid_workload_cancellation_releases_inputs_even_when_error_is_retained(self):
        cp=NumpyCuda()
        retained=None
        with mock.patch.dict(sys.modules,{"cupy":cp}):
            try:
                bench.benchmark_cuda(size=32,repeats=1,
                                     cancelled=lambda:len(cp.uploads)>=3)
            except InterruptedError as error:
                retained=error
            else:
                self.fail("mid-palette cancellation did not propagate")
        self.assertIsNotNone(retained.__traceback__)
        self.assertEqual(len(cp.uploads),4)  # two OKLab runs, then RGB + palette
        self.assertEqual(cp.trims,1)
        self.assertTrue(all(reference() is None for reference in cp.references))


class HardwareCacheTests(unittest.TestCase):
    def test_deep_oversized_and_invalid_nested_profiles_are_cache_misses(self):
        samples=["["*2000+"0"+"]"*2000,"x"*(4*1024*1024+1),
                 json.dumps({"version":bench.PROFILE_VERSION,"hardware":[]}),
                 json.dumps({"version":bench.PROFILE_VERSION,"primary_backend":{"safe_memory_budget_mb":10**400}})]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"profile.json"
            for sample in samples:
                path.write_text(sample,encoding="utf-8")
                self.assertIsNone(bench.load_hardware_profile(path=path,validate_current=False))

    def test_old_timing_profile_is_invalidated_and_current_roundtrip_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"profile.json"
            path.write_text('{"version":1,"hardware_signature":"same"}',encoding="utf-8")
            self.assertIsNone(bench.load_hardware_profile(path=path,validate_current=False))
            bench.save_hardware_profile({"hardware_signature":"same"},path=path)
            original=path.read_bytes()
            with mock.patch.object(RuntimePaths.os,"replace",side_effect=PermissionError("denied")),self.assertRaises(PermissionError):
                bench.save_hardware_profile({"hardware_signature":"new"},path=path)
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(list(Path(tmp).iterdir()),[path])
            with self.assertRaises(InterruptedError):
                bench.save_hardware_profile({"hardware_signature":"new"},path=path,cancelled=lambda:True)
            self.assertEqual(path.read_bytes(),original)

    def test_malformed_summary_and_unavailable_current_hardware_are_controlled(self):
        self.assertIn("0 ms",bench.format_hardware_summary({"hardware":[],"primary_backend":42,"elapsed_ms":10**400}))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"profile.json"
            bench.save_hardware_profile({"hardware_signature":"same"},path=path)
            with mock.patch.object(bench,"hardware_snapshot",side_effect=OSError("device missing")):
                self.assertTrue(bench.profile_needs_benchmark(path=path)[0])


class TunerCancellationPublicationTests(unittest.TestCase):
    def test_stop_after_cpu_phase_keeps_all_preexisting_profiles(self):
        stopped=[False]
        def cpu(*args,**kwargs):
            self.assertFalse(kwargs["save"])
            stopped[0]=True
            return {}
        with mock.patch.object(tuner,"benchmark_scheduler",side_effect=cpu), \
             mock.patch.object(tuner,"run_universal_hardware_benchmark") as hardware, \
             mock.patch.object(tuner,"replace_text_files") as publish, self.assertRaises(InterruptedError):
            tuner.run_auto_tune(cancelled=lambda:stopped[0])
        hardware.assert_not_called();publish.assert_not_called()

    def test_completed_profiles_publish_as_one_rollback_capable_file_set(self):
        cpu=dict(version=scheduler.SCHEDULER_VERSION,logical_cpus=4,recommended_workers=2,best_score=1,scores=[],
                 recommended_engine="Threads",ram_budget_mb=1024,machine_signature="synthetic")
        hardware=dict(version=bench.PROFILE_VERSION,hardware_signature="synthetic",primary_backend={},workload_preferences={})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/"tuner.json";cpu_path=root/"cpu.json";gpu_path=root/"gpu.json"
            for destination in (target,cpu_path,gpu_path):destination.write_text("old",encoding="utf-8")
            def failure(changes):
                self.assertEqual(set(changes),{target,cpu_path,gpu_path})
                raise OSError("publication failed")
            with mock.patch.object(scheduler,"SCHEDULER_FILE",cpu_path),mock.patch.object(bench,"PROFILE_FILE",gpu_path), \
                 mock.patch.object(tuner,"benchmark_scheduler",return_value=cpu) as cpu_bench, \
                 mock.patch.object(tuner,"run_universal_hardware_benchmark",return_value=hardware) as gpu_bench, \
                 mock.patch.object(tuner,"replace_text_files",side_effect=failure),self.assertRaises(OSError):
                tuner.run_auto_tune(path=target)
            self.assertFalse(cpu_bench.call_args.kwargs["save"])
            self.assertFalse(gpu_bench.call_args.kwargs["save"])
            for destination in (target,cpu_path,gpu_path):self.assertEqual(destination.read_text(encoding="utf-8"),"old")


if __name__ == "__main__":
    unittest.main()
