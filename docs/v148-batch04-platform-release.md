# v1.0.148 batch 04 — native input, helper lifecycle and diagnostic privacy

Date: 2026-11-06. Baseline: `1d48eabaf349a5fd8049a2c96ef5426745c3078c`.
The test-only CI correction `2aca72acb36b547d75e12a0a59d78325552c21a8`
was published during this batch and is not a product improvement.

This batch contributes **five distinct behavior improvements**, NR01–NR05.
Related failure cases, callback integration, tests and documentation are counted
once with their corresponding behavior. This is a development checkpoint toward
the requested 1,000 improvements, not a release or an antivirus verdict.

## Implemented behavior

| ID | Reproduced previous behavior | New behavior and implementation | Regression evidence |
| --- | --- | --- | --- |
| NR01 | `WindowsMouse.release` cleared ownership in `finally` even when Windows rejected LEFTUP. The existing release-then-disarm cleanup consequently made only one native attempt and could leave the application's press down. | Preserve the owned press until LEFTUP succeeds. A failed release revokes input authorization, disarm remains unconditional, and a later cleanup or explicit arm retries only the application's pending release. | `native`: failed release followed by successful disarm sends two LEFTUP attempts; persistent failure remains retryable and disarmed; an explicit new arm first resolves the pending press. |
| NR02 | UI disarm could complete between a worker's authorization check and native press/movement, allowing the worker's already-checked command to run after disarm returned. | A per-instance reentrant lock serializes arm, disarm, press, release and move. Disarm waits for an in-flight command, releases an owned button, then revokes authorization before returning. Later ordinary commands see the revoked arm. | `native`: event-controlled worker/UI interleavings for both button-down and cursor movement; no native command follows the completed disarm, and subsequent press/move is rejected. No physical input is emitted. |
| NR03 | A target-window helper used a fixed blocking subprocess call, so Stop could not interrupt a hung native probe until its normal timeout. | `TargetCapture` exposes an optional keyword-only `cancelled` callback. Its cancellable path checks before spawn, polls communication at most every 100 ms, rejects late completed results, and performs bounded terminate/wait/kill/reap cleanup on interruption. Root forwards the callback through four calibration worker call sites; both picture-palette probes before and after RGB calibration also receive it. | `processes`: pre-spawn Stop, late completion, deadline, terminate-to-kill escalation and cleanup-failure injection; an actual locally created Python child is cancelled and reaped. Picture-palette worker tests stop either probe and prevent later calibration publication/palette work. Existing calls without the callback keep their established behavior. |
| NR04 | A target helper timeout or spawn failure occurred before log publication, leaving a previous run's log in the diagnostic package. Partial timeout output may also be bytes despite text-mode process execution. | Every process failure records its current reason and available output through the existing sanitized, bounded log path. Bytes are decoded before sanitization. Diagnostic-storage failure cannot replace the actual operation exception. | `processes`: stale log replaced for timeout and spawn failure; credentials and private Windows profile names are absent; injected log-write failure preserves the original exception object. |
| NR05 | Standard JSON/repr escaping prevented Windows home-path redaction, exposing the profile name in logged command lists and exception strings. Bare quoted home paths also require a boundary that preserves following arguments. | `LocalSanitization` recognizes escaped separators, Unicode escapes and serialized custom home paths. It redacts within quoted-literal boundaries before handling ordinary paths, preserving legitimate apostrophes in names and the surrounding JSON/repr syntax. Escaped quotes cannot start new literals, avoiding repeated rescans of a malformed line. | `diagnostics`: JSON and `ast.literal_eval` round trips for full and bare Windows/POSIX homes, apostrophe/Unicode names, custom home locations, a quoted error message and an unterminated line with 10,000 escaped quotes. |

## Validation

The three new modules contain **19 focused tests**:

- `test_v148_platform_batch04_native.py` — 5 tests.
- `test_v148_platform_batch04_processes.py` — 9 tests.
- `test_v148_platform_batch04_diagnostics.py` — 5 tests.

The combined focused and related run completed **177 tests in 2.329 seconds**:
173 passed and four native-Windows checks were skipped on this Linux host.
The run includes existing mouse, capture, calibration UI, Paint preparation,
target lock/rebase, diagnostic privacy and storage regressions. `git diff
--check` passed for all owned changes. These are local measurements of test
execution, not application or Windows performance claims.

The independent root review covered native ownership/barrier semantics, helper
cleanup, late cancellation and quoted-path privacy. Its bare-home finding was
corrected within NR05 without adding a count. The CI fixture correction creates
a genuine temporary virtual environment using Python's bundled `ensurepip`
wheel; all six setup tests pass both from a base interpreter and from the
project virtual environment, without a network install.

The subsequent picture-palette callback integration adds one parameterized test
covering both worker probes. A final targeted integration run passes **147 tests
in 1.122 seconds**, including complete and partial execution-sequence resume and
the Detail Zoom visual-verification contract. Those two execution changes are
tracked under root AW27 and planner PB03 respectively; they do not add entries to
this five-item platform ledger.

## Boundaries and remaining work

- The new helper path has bounded polling and cleanup waits, not a promise that
  every operating-system process-creation/termination call can be interrupted
  within a hard wall-clock limit. Cleanup failures remain attached to the
  original error and are sanitized before logging.
- The 64 KiB helper-log limit bounds saved text. Captured subprocess output is
  still accumulated by `communicate`; total pipe-output memory is not claimed
  to be bounded by this batch. The helper is the application's own probe.
- Native Windows CI must verify the combined head, including packaged GUI and
  native dependencies. Portable tests use injected native APIs; the real child
  process test runs only a small test-owned Python script.
- No release, installer, signing, certificate, dependency, antivirus-rule or
  publishing behavior was changed. No installer or unknown binary was
  downloaded or executed. Broader packaging audit leads remain unimplemented
  and are not counted here.

## Primary platform references

- [Microsoft SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput): the return value reports accepted input events; failure does not establish that a button-up was delivered.
- [Python 3.12 subprocess](https://docs.python.org/3.12/library/subprocess.html): communication deadlines, explicit termination/reaping, text-mode behavior and byte-valued timeout output.

The selected-target Browser One-Click and Smart Canvas Drop paths also forward
their existing cancellation callback to the isolated probe.
`test_v148_browser_probe_cancellation.py` verifies Stop prevents subsequent
capture/calibration in both paths. This is an NR03 completion, not a new ID.

## Frozen integration checkpoint

Independent area and cross-area reviews are closed. Whole-program discovery ran
**2,934 tests in 75.509 seconds**, passing with 23 platform/hardware skips; source
hashes were unchanged during the run. The 5,000-cycle release source gate,
source-package hygiene and eight exact-raster engine fixtures also passed.
This batch is included in the 668-improvement development checkpoint. Its own
Windows/Linux CI is pending; 1.0.148 is not yet released.
