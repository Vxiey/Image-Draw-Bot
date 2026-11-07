# Batch 26 — complete lazy GPU host preparation ownership

Integration baseline: `5b0c22ac5dc620a911fa2a1f6216e272f644f7db`, containing
837 registered groups. The subsequent `a3b7b929b1332772a089e1819143471ae5d58c68`
integration changes a prior test fixture and documentation, not this product
module. This work completes **P2504 / global 836** and adds **zero new IDs**.

## Incoming behavior and deduplication

The independently published [batch 25 platform work](v148-batch25-platform.md)
already made successful OpenCL palette matching avoid an unused full-image RGB
composite and visibility mask. Its `visible_host_input` helper also reused
successful CUDA preparation during CPU fallback. Those gains are already
counted. Earlier **GP10 / global 562** improved arithmetic inside
`_rgba_visible_rgb`; that helper remains unchanged here.

The original local proposal was developed against
`586e12db5ea5142951c844f60dc2364f07a01c37` before the independent batch25 arrived.
Its eager-versus-lazy measurements cannot establish an additional gain over the
837-entry integration baseline. This ledger preserves that historical evidence
separately and records fresh before/after evidence for the remaining error and
ownership boundaries.

The incoming implementation performs CUDA host preparation inside
`_run_accelerated`. Consequently a host preparation error can cross the native
failure boundary and cause a CPU retry of the same failed preparation. A normal
`MemoryError` is already classified as transient; the before evidence does not
claim that this error permanently quarantined the GPU. Separately, a retained
exception traceback can retain the preparation closure's private arrays.

## Fresh actual before evidence

`test_v148_platform_batch26_opencl_host.py` contains eleven methods. It retains
the nine local regression methods and adds an actual route-selection Stop case
and an actual CUDA host-allocation failure through the real
`_run_accelerated` implementation. The latter observes the real boundary, lets
the genuine `_rgba_visible_rgb` create its arrays, then raises a retained
`MemoryError` at that host boundary.

Before changing the incoming module, these eleven methods and all five incoming
palette-preparation methods ran together: **16 methods, six assertion failures
across five methods, eleven methods passing, no test errors, 0.235 s**. All five
incoming methods passed. The observed failing host-error sequence was
`native-boundary → host → host`; the corrected contract requires only `host`.
The route-selection Stop control already avoided host work in the incoming
version, but its CUDA branch still entered the native wrapper before stopping.
Other failures demonstrated private raw/RGB/visibility retention while the
original exception remained alive.

Evidence: `batch26-opencl-host-incoming-before.log` in the session scratch
directory. The incoming product module's SHA-256 was
`730e656a9e595697b69b183c9626ef8d2aa9997be81d05623a2c274a8d136f03`.

## Narrow completion

Only `UniversalGpuAcceleration.palette_indices_rgba` changes. Its local
`prepare_host_pixels` helper retains the incoming Stop check inside the
preparation `try`. CUDA host preparation now happens before
`_run_accelerated`; CPU preparation stays lazy, and successful OpenCL continues
to perform none. Native OpenCL failure releases its attempt before one fresh
CPU preparation. Successful CUDA preparation remains reusable by CPU fallback.

If host preparation or its Stop callback fails, the helper clears only its
private `raw`, `rgb` and `visible` closure cells before re-raising. This is
necessary because retained closure cells can outlive cleared exception frames.
The original exception identity and traceback remain available; borrowed input
image pixels and metadata remain open and unchanged. A host failure does not
enter native backend failure accounting or retry preparation as GPU fallback.

The OpenCL kernel, candidate ordering, tie policy, numerical formulas,
alpha/Skip-white rules, transfer layouts and chunk limits are unchanged.
No other GPU or planner module is part of this completion.

The incoming file `test_v148_platform_batch25_palette_preparation.py` remains
byte-identical, SHA-256:

```text
321a5a609b848a85c1b457e06ab1f86894473520430a2d427dc3e8559d62c758
```

Its five methods retain important additional controls: ndarray input,
mode/fidelity/Skip-white combinations, failure after actual partial native
output, Stop after partial output, and successful CUDA fallback reuse. They
remain alongside the new tests rather than being replaced.

## Current integration verification

| Gate | Result |
| --- | --- |
| Fresh incoming before, eleven local plus five incoming methods | 16 methods; six assertion failures across five methods; eleven passed; 0.235 s |
| Same combined methods after the merge | 16/16 passed; 0.177 s |
| Related palette, numeric ownership, GP10, universal routing, fidelity, transparent fallback and public planner policies | 74 methods: 71 passed, three existing physical-hardware skips; 1.674 s |

The typed OpenCL facade substitutes only context/buffer/transfer/kernel
boundaries. It checks actual buffer flags, layouts, dtypes, scalar arguments,
raw upload bytes and tile sizes and supplies a deterministic numerical result.
Actual route selection, session ownership, fallback and the public
`DrawBot.make_plan` caller remain in use. It is not a physical GPU.

The regression set retains exact raster, metadata, geometry and source checks,
the 262,144-pixel chunk boundary plus tail, CPU and CUDA preparation counts,
native buffer cleanup before fallback, Stop before and after native work, and
weak-reference checks while original errors remain referenced. The new actual
host-error case now observes `host`, not a native attempt followed by two host
preparations. These work counts do not imply a general speed improvement.

Logs: `batch26-opencl-host-after.log` and
`batch26-opencl-host-related.log`. Root and the independent rendering reviewer
read the complete merged source and the added actual-route tests and closed
their reviews without blockers. No redundant hardware test was substituted for
the existing hardware skips.

## Historical evidence and reusable comparison method

The original eight-method before run on `586e12d` produced eight expected
assertion failures across five methods, with three positive controls passing
in 0.116 s. An additional ninth method was added later; that original before
run is not represented as a nine- or eleven-method run. Its direct 128×96 and
public 48×32 OpenCL callers each prepared one unused RGB/mask pair, containing
159,744 B and 19,968 B respectively. Those are array payload sizes and work
counts, not measured peak memory. The incoming P2504 already removes this work.

The original retained-error correction and nine-method after gates, including
the independent root 9/9 run, are historical development evidence. The former
related gate was 67 methods: 64 passed and three hardware skips, 1.654 s.
Preserved files include `batch25-opencl-host-before.log`,
`batch25-opencl-host-before.json`, `batch25-opencl-host-after-initial.log`,
`batch25-opencl-host-after.log`, `batch25-opencl-host-root-review.log`,
`batch25-opencl-host-helper-after.log` and `batch25-opencl-host-related.log`.
They do not describe validation of the later incoming commit.

`benchmark_v148_platform_batch26_opencl_host.py` distinguishes two baselines:

- Complete `UniversalGpuAcceleration` from `586e12d`, used solely to reproduce
  the already-counted eager-versus-lazy optimization. The historical module is
  43,420 bytes, SHA-256
  `dddea3224ccf07a78ae75a12d10beb88fca6efe643d6765a4bc981fb27e8c42a`.
- Complete incoming `UniversalGpuAcceleration` from `5b0c22a`, used for a
  separate completion-parity comparison, including unchanged successful-route
  work counts. No new gain over that incoming baseline is asserted.

Both are linked through actual consumer imports while all sides use the same
current DrawBot and shared dependencies. This isolates the backend module; it
does not execute a complete historical planner. The verifier retains full
output and transfer comparisons for 692 cases per baseline and six additional
actual caller workloads. Kernel source and the host-compositing helper are
checked unchanged. Public-plan parity uses only the already-declared elapsed
paths in `VOLATILE_PATHS`; costs, geometry, diagnostics and raster bytes remain.

The earlier 692-case preliminary report and six workload comparisons passed on
the pre-integration tree. A later method check passed those functional
comparisons but correctly failed its final source-hash check during concurrent
benchmark editing. Its log remains
`batch25-opencl-host-verify-method-final.log`; it produced no accepted frozen
report. The renamed integration verifier must run on the coordinated final
source snapshot before its result is treated as final evidence.

If historical timing is run, it requires six balanced AB/BA pairs and separate
allocation probes. Setup, routing fixtures and module patches are outside the
timer; only the actual palette call or public planner is timed. Normalization,
parity checks and cleanup follow the timer. Tracing samples the original live
result before normalization and cleanup. The facade's host arithmetic remains
inside the call symmetrically and is explicitly synthetic CPU work. The
measurement boundary has been independently source-reviewed.

No physical GPU throughput, device latency, total GPU memory, process RSS or
target-app speed claim follows from this portable boundary. Final combined
validation and any source-bound historical reproduction are recorded by the
batch finalizer; previous commits' CI does not validate this new integration.


## Final frozen integration reproduction

The final integrated source completed **4,431 tests in 215.945 s: 4,361
passed and 70 existing platform/hardware cases skipped**. All 923 checked
source/configuration hashes remained unchanged. Ten actual Linux/Xorg native
UI cases passed in 5.238 s, together with the 5,000-cycle source gate, package
hygiene and eight exact existing-raster fixtures.

The [final raw report](v148-batch26-opencl-host-benchmarks.json) passed all
692 complete caller comparisons against each of the two historical GPU
modules, plus all six complete workload/transfer/work comparisons. The
incoming `5b0c22a` successful-route host counts are exactly the same as the
current implementation. That is completion evidence for P2504, not another
counted eager-to-lazy optimization.

The full regression subset, native gate, both final paired reports and the
existing-raster report share **873 unchanged root Python hashes**, canonical
manifest SHA-256
`e4057cf13bd9e97e52b07dbdba90f6962a9bbb012c0c78430d782418d8d0442d`.
This raw report's SHA-256 is
`16d81bbd15e274653b49a5ed7741db9061c6c9ca5223111383cf903a52a19c49`.

Every elapsed result below uses six balanced AB/BA pairs. Before refers to
`586e12d`; after refers to the current merged GPU module with the same current
planner on both sides. These timings reproduce the already-counted P2504
change. Incoming `5b0c22a` is checked for exact output, transfers and work,
not used as a timing baseline.

| Actual caller | Before median (ms) | After median (ms) | Change | Faster pairs |
| --- | ---: | ---: | ---: | ---: |
| opencl-opaque-1024x768 | 116.938 | 81.247 | -30.521% | 6/6 |
| opencl-mixed-alpha-512x384 | 72.716 | 62.259 | -14.381% | 6/6 |
| opencl-two-tiles-tail-1025x512 | 71.962 | 45.010 | -37.453% | 6/6 |
| cpu-mixed-alpha-control-512x384 | 57.054 | 57.501 | +0.784% | 3/6 |
| actual-public-pixel-opencl-96x72 | 65.706 | 63.661 | -3.112% | 4/6 |
| actual-public-pixel-cpu-control-96x72 | 55.829 | 56.249 | +0.751% | 3/6 |

Separate traces sample the raw result while it is still alive. All before and
after values, including small increases and slower CPU controls, are retained.

| Actual caller | Before peak (B) | After peak (B) | Before retained (B) | After retained (B) |
| --- | ---: | ---: | ---: | ---: |
| opencl-opaque-1024x768 | 44,121,020 | 33,897,500 | 2,365,892 | 2,365,980 |
| opencl-mixed-alpha-512x384 | 68,337,948 | 65,782,108 | 595,808 | 595,896 |
| opencl-two-tiles-tail-1025x512 | 29,450,410 | 22,628,158 | 1,580,752 | 1,580,892 |
| cpu-mixed-alpha-control-512x384 | 5,705,849 | 5,706,769 | 601,828 | 601,916 |
| actual-public-pixel-opencl-96x72 | 7,335,726 | 7,246,067 | 1,118,869 | 1,120,512 |
| actual-public-pixel-cpu-control-96x72 | 1,581,698 | 1,581,349 | 1,059,325 | 1,059,420 |

Successful OpenCL still needs zero host composites; CPU still needs one. The
CPU controls are slower in this run, while the whole public OpenCL caller has
a smaller median. Neither observation establishes a general planner speedup.
The facade performs numerical work on the CPU; no physical GPU throughput,
device allocation or total-RSS inference is made. The bounded/retained-error
completion is established by its actual failure and ownership tests above.
