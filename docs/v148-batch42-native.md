# v1.0.148 batch 42 — native input, delivery and capture comparison

## Scope and counting

Four independent product groups are verified against public commit
`e33fa67d17e3c33ccda8e736e7e16c2582d9fc06`, whose tree is identical to the
local batch41 checkpoint. The aggregate registry assigns their global IDs.
Individual keys, tools, test cases, cleanup paths and review corrections do
not receive separate IDs. The release version remains 1.0.148.

## N4201 — physical keyboard modifiers cannot alter a native gesture

WindowsMouse previously rejected externally held mouse buttons but allowed a
held Shift, Ctrl, Alt or Windows key to modify an ordinary authorized stroke
or control click. It now observes these keys before arming, pressing or sending
each cursor/SendInput move, including position retries. A modifier arriving
during drawing stops subsequent input. The bot still releases its own held
left button and does not synthesize key-up events for the user's keys.

The actual normal and modal keyboard guards also use this observation before
Ctrl+A, Delete, Escape and RGB writes. This closes the interval after the
preceding control click; it completes the same modifier ownership contract
without an extra ID. Native input remains explicitly armed, and an unsuccessful
arm requires a fresh explicit arm after the user releases the modifier.
Older injected cursor-only providers retain their established fallback.

Five methods cover every modifier, arming/pressing, both drag backends, a key
pressed during a retry, owned left-button release, explicit rearming and both
real keyboard-guard branches. The earlier mouse-button takeover and
keyboard-focus checks remain separate controls; this change does not claim an
atomic operating-system transaction against every possible focus/key race.

## N4202 — browser delivery needs evidence at multiple stroke sites

The browser delivery verifier reused Paint's nearest-color check. A single
matching pixel anywhere near a long stroke could therefore confirm delivery
of the whole segment. The committed small-detail raster reproduces exactly
one matching site among the five existing probe positions: Paint color
selection correctly reports a nearby matching color, but browser delivery now
reports one of five sites, below the required three.

GuardedMouse exposes a separate coverage inspection used by the actual browser
delivery policy. It requires at least 60% of distinct sampled sites in one
settling attempt. Evidence never accumulates across attempts. Each physical
pixel belongs only to its nearest site, so overlapping short-stroke patches
cannot turn one pixel into several votes. An incomplete fixed-size native
capture cannot shift samples into another site's membership. Target/Stop
checks remain before and after native observation.

Paint's original color-selection API and legacy injected inspector backends
remain compatible. Grouped native reads retain their bounded sparse and
cross-monitor fallbacks. Those fallbacks may observe sites successively: this
is a static-ink sampling heuristic, not an atomic display-frame proof or an
exact Pixel Accuracy Score. A matching old stroke is also not proof that a
new gesture caused that ink.

Six methods use existing raster samples through the real GDI buffer boundary,
including full matching coverage, one matching site, incomplete capture,
nonaccumulating attempts, disjoint physical-pixel ownership and Stop/focus loss
during GDI completion. The executor's failure message now explains partial
coverage even when the closest RGB is exact; that is part of this group.

## N4203 — concurrent DPI observations keep their own native signature

DpiSupport defined MONITORINFO anew for each call and rebound the cached
GetMonitorInfoW argument type on a shared DLL object. Two concurrent
WindowMonitor DPI observations could therefore pass the first call's pointer
to a function expecting the second call's incompatible structure class.
The actual ctypes conversion reproduces an ArgumentError against the baseline.

The monitor layout now has fixed Windows-width fields and a 40-byte structure.
Each observation binds a private indexed native function signature and reads
fresh monitor/work rectangles. No monitor metadata is cached. Full-width
handles, negative monitor origins and existing unavailable-provider fallback
are preserved. This is the separate DPI producer; P1801's memory-status ABI
correction did not cover it.

Two portable tests exercise deterministic overlapping real-ctypes calls and
layout/fallback behavior. A third test exercises the actual Windows monitor
API when available and is skipped on this Linux host. No native Windows
success is inferred from the portable boundary.

## N4204 — exact recording comparison with bounded export scratch

The recorder already coalesces identical retained frames (AY03/global732).
Its comparison still exported two entire rasters for every candidate. The
public append_recorded_frame operation now compares full-width strips of at
most 65,536 pixels, or one exceptionally wide source row. The actual recorder
caps width at 800 pixels. Small frames keep the old direct byte comparison.

Full-width strips preserve packed row semantics, including mode 1. A differing
strip ends comparison immediately. Dimensions, mode, RGBA palette and
transparency still gate raster comparison; durations and ownership transfer
are unchanged. Private strips close on success and on failures in either crop
or byte export, while both borrowed frames remain open. No global image hash
or mutable-frame cache is introduced.

Five methods check exact old byte semantics across eight modes and small/large
dimensions, actual 800×500 recorder bounds, early and late differences,
palette/transparency mismatch, the small no-crop path, and retained exception
ownership. Existing full recorder/GIF timeline tests also pass unchanged.

The six-case paired public-call benchmark retains all samples and controls.
For static 800×500 palette frames, traced peak drops from **1,200,769 to
132,210 bytes**, while median comparison time increases from **0.1664 to
0.3572 ms**. This is a deliberate bounded-memory tradeoff, not a speedup claim.
Changing the first pixel takes **0.1327 versus 0.0456 ms**. Small controls have
the same traced peak and modest timing noise/overhead. The large RGBA API
control improves too, but is not described as the recorder's actual workload.

Tracemalloc does not include Pillow core crop storage. At most two private
strip cores also exist; source/retained frames, capture, quantization and GIF
encoding remain outside this comparison measurement. No process-RSS or
whole-recording speed improvement is claimed.

## Evidence

- `verify_v148_native_batch42.py` compares four exact historical product paths
  with the new public/native boundary tests. The baseline produces 14 failed
  assertions/subtests and the real DPI ArgumentError; no historical case is
  falsely presented as a passing control.
- `v148-batch42-native-validation.json`: **19 methods, 18 passed, one Windows
  skip, zero failures/errors**, with unchanged focused product hashes.
- `v148-batch42-native-adjacent.json`: **145 methods, 144 passed, one native
  Windows sampling skip, zero failures/errors**, with unchanged selected
  product/test hashes. These overlapping selections are not added together
  into a distinct test total.
- `benchmark_v148_recording_batch42.py` and
  `v148-batch42-recording-benchmark.json`: six complete public-call parity
  workloads, six alternating timing pairs each, separate allocation samples,
  exact source/asset hashes and all slower controls.
- Independent runtime review covered native identity, distinct site ownership,
  modifier/keyboard completion and recording cleanup/count boundaries.

All pixel inputs are committed repository assets or in-memory derivatives.
The complete final integration gate and published-commit CI are separate;
neither this focused evidence nor a former green commit verifies physical
Windows/Paint/GPU behavior on the final branch.
