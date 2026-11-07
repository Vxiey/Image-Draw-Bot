# Batch 18 — independent native physical-memory observations

## P1801: concurrent RAM probes retain their own native ABI

Diagnostics and the Universal Hardware Benchmark each declared a local
`MEMORYSTATUSEX` ctypes class. Both then assigned the signature of the same
attribute-cached `GlobalMemoryStatusEx` function on a cached system DLL.
If the second probe ran between the first probe's signature assignment and
native call, ctypes rejected the first pointer as belonging to the other
class. A valid physical-memory observation became `None` in that caller.

The baseline at `d7721a36975a36137b583beda9ff3c47c05208fd` reproduced both
orders with real concurrent consumers and real ctypes pointer conversion.
Both failed with `expected LP_MEMORYSTATUSEX instance instead of pointer to
MEMORYSTATUSEX`; the serial 32/64 GiB control passed. The same three-method
baseline also reproduced the available-memory consumer bypassing the system
loader. It completed in 0.024 seconds with three failing subcases across two
methods and one passing method. Only the OS buffer fill was supplied by a
small C callback; the argument conversion was not mocked.

`WindowsSystem.physical_memory_bytes()` now uses one fixed-width, 64-byte
structure and a private function object obtained by indexed DLL lookup. The
safe system DLL handle remains cached, while each observation and its function
signature are independent. The two total-memory consumers and the
available-memory consumer share this boundary. Available zero remains a real
measurement: it still rejects planning through the existing low-RAM policy.
API/loader failures, zero total memory and available memory greater than total
retain the callers' existing unavailable fallbacks. Portable system probes are
unchanged. There is no new dependency, cached memory value or scheduler policy.

## Evidence and scope

The focused command is:

```sh
.venv/bin/python -m unittest test_v148_platform_batch18_memory test_v148_resource_safety test_windows_system -v
```

It completed **43 tests in 0.052 seconds: 41 passed and two native Windows
cases were skipped** on the local Linux host. The new file contains six
methods covering the deterministic overlap in both orders, untouched cached
function signatures, fresh 64-bit observations, known-zero memory, native
failure and invalid-buffer boundaries, loader failure, and unchanged portable
consumers. Its native Windows method calls the real kernel32 API under the same
scheduled overlap; it neither fabricates OS return values nor demands equal
available-memory values from different moments.

An independent source review and separate six-method run closed without
blockers: five passed and the live Windows method was skipped (0.020 seconds).
The next Windows CI run containing this source remains necessary evidence for
the live native branch. Local ctypes conversion evidence is not represented as
a completed Windows gate.

This is **one behavior group**, P1801. SS22's consistent allocation snapshot,
SS23's low-RAM rejection and the original secure-System32-loader contract
remain in place. Routing the available-memory consumer through the existing
loader completes that earlier contract and adds no separate improvement ID.
Tests, shared code and removal of duplicate structure declarations add no IDs.

## Primary API contracts

- [Microsoft: GlobalMemoryStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)
  defines the success/failure result and the volatility of memory observations.
- [Microsoft: MEMORYSTATUSEX](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex)
  defines the two DWORD fields, seven DWORDLONG fields, initialized structure
  size and byte units.
- [Python 3.12: ctypes](https://docs.python.org/3.12/library/ctypes.html)
  documents cached function objects from DLL attribute access and fresh
  function objects from indexed lookup, along with argument-type conversion.
