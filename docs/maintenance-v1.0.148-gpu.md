# v1.0.148 GPU improvements 001–025

This ledger records 25 changes to program behavior. Tests, documentation, release
metadata, and formatting are not counted as separate improvements.

| ID | Improvement | Implementation | Regression evidence |
| --- | --- | --- | --- |
| 001 | Windows hardware discovery no longer starts PowerShell. Native DXGI enumerates NVIDIA, AMD, Intel, and other hardware; preserves full pointer-width dedicated VRAM; excludes software adapters by their documented flag; and retains hardware with no dedicated VRAM. | `WindowsGpuDiscovery.enumerate_adapters`, `GpuHardware._detect_all_with_windows`. Fixed-width Windows ABI fields, UTF-16 descriptions, optional UMD driver version, explicit COM release, bounded adapter count, and System32-only loading through `WindowsSystem`. | `test_windows_gpu_discovery.py` exercises real ctypes vtables with fakes, >4 GiB/Unicode metadata, 32/64-bit layouts, failed HRESULTs, empty results, software filtering, and release counts. A real Windows subprocess smoke has a 30-second timeout. |
| 002 | One unusable CUDA device no longer hides healthy devices. | `GpuAcceleration._load_cupy` isolates errors for each candidate before selecting a usable device. | `test_gpu_execution_regressions.py` covers a failing first adapter followed by a working adapter, and the all-failed CPU fallback. |
| 003 | Cached CUDA selection is applied to the thread that actually performs the work. | `GpuAcceleration._resolve_backend` retains the selected device ID separately from the existing backend tuple, binds it per calling thread, and clears it on reset/failure. | A real Python worker thread with thread-local fake CUDA state now reports the selected GPU's name and memory consistently; reselection and binding failures are covered. |
| 004 | Windows cannot select an arbitrary `nvidia-smi` executable from PATH, the working directory, or environment-overridden install roots. | `GpuHardware._nvidia_smi_candidates` uses OS-reported System32 and Program Files/NVIDIA NVSMI locations. Linux PATH lookup is retained. | `test_gpu_discovery_regressions.py` supplies hostile PATH/environment entries, duplicate trusted roots, and unavailable directory APIs. |
| 005 | NVIDIA metadata cannot be assigned to a different GPU whose model merely shares a prefix. | `GpuHardware._merge_devices` matches complete normalized model names rather than substrings. | RTX A500 and RTX A5000 remain separate and keep their correct memory/driver data. |
| 006 | Two physical adapters with the same model are retained when NVIDIA's utility is unavailable. | Native fallback merging preserves each generic adapter's ordinal; CUDA-specific fallback indices remain unknown rather than borrowing DXGI ordinals. | Duplicate-model merging and a native adapter at ordinal 3 are covered without inventing a CUDA index. |
| 007 | Missing NVIDIA fields do not erase useful native metadata. | `_merge_devices` retains known memory, driver, bus, PNP, and processor fields when enrichment has no replacement value. | Partial SMI metadata preserves the native memory, driver, and existing identity fields. |
| 008 | Malformed NVIDIA CSV or nonfinite/fractional indices cannot crash discovery or select the wrong device. | `_detect_with_nvidia_smi`, `_parse_int`, `_smi_text` use CSV parsing, finite integer-valued numbers, nonnegative indices, and explicit unavailable-field handling. | Quoted names, malformed rows, `nan`, `inf`, negative memory/indices, fractional indices, and exact large integer parsing are exercised. |
| 009 | A full Windows GPU refresh performs one native enumeration. | `_cached_nvidia_gpus` reuses the generic Windows snapshot for the NVIDIA fallback. | A full refresh followed by cached public queries calls the native probe once. |
| 010 | Refreshing NVIDIA information invalidates an older universal GPU snapshot. | `_cached_nvidia_gpus` invalidates `_ALL_CACHE`; public cache operations share an `RLock`. | A direct NVIDIA refresh is visible on the next `detect_gpus` call without a second SMI probe. |
| 011 | CUDA fused kernels receive scalars with the widths declared by their C signatures. | All four portrait/saliency full-frame and tiled launch sites use `numpy.float32`/`numpy.int32`. | `test_gpu_execution_regressions.py` executes full and tiled paths with strict fake kernels that validate argument types and resulting image values. |
| 012 | Retrying a failed accuracy-scoring tile does not count pixels or brush hits twice. | `PixelAccuracyGpu.score_cuda_host` commits per-tile reductions only after all reductions and the host transfer succeed. | `test_gpu_scoring_regressions.py` injects first/later-copy and reduction failures, then compares every metric and the error image with the independent CPU scorer. |
| 013 | Very dark byte palettes produce correct Oklab distances. | `UniversalGpuAcceleration.pairwise_oklab_distance` normalizes the byte-RGB API explicitly instead of guessing scale from the brightest channel. | `test_gpu_route_regressions.py` compares CPU, fake CUDA, and fake OpenCL results against `ColorFidelity` for channels limited to 0/1; normalized-float APIs retain their existing meaning. |
| 014 | Damaged hardware profiles become recoverable cache misses instead of uncaught exceptions. | `UniversalHardwareBenchmark._read_profile` and `_current_profile_version` handle invalid encodings, JSON shapes, and version values. | Invalid UTF-8, invalid JSON, lists/null, invalid strings/lists, NaN, and boolean versions are rejected without invoking a hardware probe. |
| 015 | Explicit empty preference data is respected, and malformed nested preferences safely select CPU. | `preferred_backend` loads a saved profile only for `None`, validates mappings and thresholds, and returns a copied preference. | Empty profiles do not read disk; invalid preference shapes and crossover values fall back; valid measured thresholds still select the GPU. |
| 016 | Nonfinite benchmark values cannot win backend selection or create infinite speedups. | `_scores_by_workload` rejects nonfinite/invalid rates and elapsed times. | NaN, infinity, invalid elapsed time, and string rates cannot defeat a valid CPU score; resulting preferences serialize without nonfinite JSON numbers. |
| 017 | Suggested GPU memory budgets respect currently reported free memory. | `_safe_gpu_budget_mb` caps the recommendation using free memory, including zero, and keeps headroom on small cards. | A busy 16 GiB card with 100 MiB free receives at most 80 MiB; zero free memory remains zero; small/integrated cards do not exceed the reported capacity. |
| 018 | CPU-name fallback does not perform unnecessary WMI/platform queries. | `cpu_name` returns an available process CPU identifier first and evaluates remaining probes lazily, tolerating unavailable platform queries. | Platform probes are not called when the identifier exists; a failed processor query falls back to machine information. |
| 019 | Reading optional runtime versions does not initialize CUDA/OpenCL DLLs. | `runtime_versions` uses installed distribution metadata and already-loaded modules only, including optional CUDA runtime wheel versions. | Import traps ensure CuPy/PyOpenCL are never imported by the version probe; missing metadata is nonfatal. |
| 020 | Auto backend status follows measured crossover thresholds and current backend health. | `GpuBackendStatus.verified_gpu_status` resolves current Auto routes for the exact workload size, with one consistent profile read per status update. Explicit CPU/CUDA caching is retained. | A measured 80k-pixel crossover distinguishes 40k and 120k inputs within the old cache bucket; same-size backend quarantine is reflected immediately. |
| 021 | Cancellation is responsive during a single long stroke. | `compile_swept_rectangles` checks cancellation while materializing long paths, traversing segments, and expanding diagonals. | Cancellation interrupts each of those inner loops within 128 additional points/segments. |
| 022 | Programmatic GPU installers verify the actual target virtual environment before modifying packages. | `GpuSetupRuntime.require_virtual_environment` runs a fixed isolated Python probe before any pip operation in both installers. Setup state is not written into a system Python prefix. | `test_gpu_setup_regressions.py` rejects a system target even when the caller is in a venv, rejects malformed/frozen targets, verifies the first installer command, and runs the read-only protocol against the current interpreter. |
| 023 | Process start failures and timeouts return controlled setup results with CPU fallback. | Both setup entry points handle probe/install/post-install failures; invalid pip inventory is not treated as an empty environment. | Simulated probe/install timeouts and launch failures do not escape setup; an initial probe timeout does not trigger package installation. |
| 024 | OpenCL validation uses the selected Python interpreter before and after installation. | `AutoUniversalGpuSetup._smoke_test` uses the module's read-only `--smoke-json` path with separate stderr and a bounded process timeout. | Tests verify the selected interpreter, structured response validation, and repeated validation of the same target after installation. |
| 025 | A broken first OpenCL adapter no longer hides another working GPU. | `opencl_smoke_test` tests candidates independently, checks the complete small result array, and reports a device only after successful execution. | A failed context or partially written kernel output proceeds to the next GPU; all-failed candidates produce an explicit failure. |

## Validation

The integrated GPU/native/setup/benchmark/pixel regression run completed with
**176 tests, no failures, and 3 skips** on the Linux development host. It includes
the new portable native-ABI and fake-compute regression tests plus the related
existing GPU, pixel-accuracy, and resource-allocation suites.

The real Windows DXGI subprocess smoke is platform-gated and was not executed
on that host. The application self-test also calls the strict native probe on
Windows, including in the frozen release gate. GPU fakes verify dispatch,
normalization, error recovery, and thread behavior; they do not certify every
physical driver. No package installation was performed during these tests.

These changes improve correctness, reliability, and executable/library
resolution. They do not constitute an antivirus vendor's false-positive review
or a guarantee that a release will receive no detections.

## Native API references

- [CreateDXGIFactory1](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/nf-dxgi-createdxgifactory1)
- [EnumAdapters1](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/nf-dxgi-idxgifactory1-enumadapters1)
- [DXGI_ADAPTER_DESC1](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/ns-dxgi-dxgi_adapter_desc1)
- [DXGI adapter flags](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/ne-dxgi-dxgi_adapter_flag)
- [CheckInterfaceSupport driver version query](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/nf-dxgi-idxgiadapter-checkinterfacesupport)
- [Microsoft SDK DXGI interface definitions](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/shared/dxgi.h)
