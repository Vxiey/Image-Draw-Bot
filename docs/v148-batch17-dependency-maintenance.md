# v1.0.148 dependency minimum maintenance

This maintenance raises three existing lower bounds to the versions proposed by
Dependabot PRs [#38](https://github.com/Vxiey/Image-Draw-Bot/pull/38),
[#40](https://github.com/Vxiey/Image-Draw-Bot/pull/40), and
[#41](https://github.com/Vxiey/Image-Draw-Bot/pull/41). It adds **zero improvement
groups**: these are dependency metadata changes, with no application API change,
new GPU capability, or performance claim.

| Manifest | Previous requirement | New requirement | Upstream Python support |
| --- | --- | --- | --- |
| `requirements-build.txt` | `pyinstaller>=6.22.2,<7` | `pyinstaller>=6.22.3,<7` | `>=3.8,<3.16` |
| `requirements-dev.txt` | `hypothesis>=6.100,<7` | `hypothesis>=6.170.14,<7` | `>=3.11` |
| `requirements-gpu-universal.txt` | `pyopencl>=2024.3,<2027` | `pyopencl>=2026.1.4,<2027` | `>=3.10,<4` |

The Python requirements above come from the upstream package metadata:
[PyInstaller 6.22.3](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/pyproject.toml),
[Hypothesis 6.170.14 source](https://github.com/HypothesisWorks/hypothesis/blob/255a880b2f626852a139934e7893479039db7d1e/hypothesis/pyproject.toml), and
[PyOpenCL 2026.1.4](https://github.com/inducer/pyopencl/blob/v2026.1.4/pyproject.toml).
All retain the project's Python 3.11 and 3.12 support. Hypothesis remains a test
dependency; the private release builder consumes the application, build, and
universal-GPU manifests, with the CUDA manifest added only for that variant.

## Existing exact-commit evidence

Before these minimum changes, the successful
[Windows CI job 128417518628](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42377334258/job/128417518628)
on commit `86fa125306b9c2db8e8125fec6a38270b09c8ff9` already resolved the newer
versions within the previous ranges:

- At `2026-11-07T13:31:46Z`, the source/test environment installed Hypothesis
  **6.170.15**, NumPy **2.5.4**, and TkinterDnD **0.7.0**.
- At `2026-11-07T13:35:58Z`, the private build environment installed PyInstaller
  **6.22.3**, its hooks package **2026.9**, and PyOpenCL **2026.1.4**.
- That job passed **3,851 tests with three skips**, the source self-test, bundle
  validation, and the packaged GUI/native drag-and-drop smoke test.

The same commit's
[Python 3.11 dependency job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42377334258/job/128417518804)
also passed. These are historical checks on the exact named commit, not a claim
that the newly edited manifests have already passed remote CI. The build
environment already upgrades its allowed dependencies eagerly; the lower bounds
also prevent an existing source/test environment from retaining versions below
these new minima. No dependency reinstall was performed for this maintenance.

The [PyInstaller patch notes](https://pyinstaller.org/en/v6.22.3/CHANGES.html)
include Windows launch and icon handling fixes. The
[PyOpenCL patch notes](https://github.com/inducer/pyopencl/releases/tag/v2026.1.4)
describe lazy Mako importing. Packaging and ordinary app startup do not establish
that an OpenCL kernel ran on physical GPU hardware; that requires a real driver
and device and is not claimed here.

## Preserved compatibility and gates

`requirements.txt` keeps `numpy>=2.0,<3`. NumPy 2.5.4 requires Python >=3.12 in
its [upstream metadata](https://github.com/numpy/numpy/blob/v2.5.4/pyproject.toml),
and [PR #37's Python 3.11 job](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42094564581/job/127481110624)
could not resolve `numpy>=2.5.4,<3`. The compatible range already selects 2.5.4
on Python 3.12 without removing Python 3.11 support.

The existing `ci.yml` strict dependency audit includes all three edited
manifests on Ubuntu/Python 3.11 and Windows/Python 3.12. Its full regression,
Windows build/self-test, and packaged GUI/native-DnD gates remain in place. A fresh
remote audit and Windows build are required on the published commit; no workflow,
version, registry, or existing test assertion is changed here.

## Existing property-gate completion (zero new groups)

The dependency check exposed a pre-existing discovery gap:
`test_raster_identity_property.py` defined two free Hypothesis functions, while
both CI commands use `unittest`. Merely naming that module ran neither function.
Two `unittest.TestCase` wrappers now invoke the existing decorated functions.
Their strategies, 1,000-example settings, deadline policies, independent integer
raster oracle, and assertions are unchanged.

Local validation with the already installed Hypothesis **6.170.15**:

- The two original functions passed when invoked directly, with 1,000 generated
  examples each.
- The CI-style explicit module command now ran **two tests**, passing in 4.110 s.
- `unittest discover -s . -p test_raster_identity_property.py -v` also ran **two
  tests**, passing in 3.494 s, with the same 1,000 examples per wrapper.
- The existing private-builder and universal-GPU/CPU-fallback modules passed
  **16 tests** in 0.209 s. No actual GPU execution is inferred from these tests.
- `ReleasePackage.py --check` passed with no missing or forbidden files and no
  warnings. `git diff --check` passed.
