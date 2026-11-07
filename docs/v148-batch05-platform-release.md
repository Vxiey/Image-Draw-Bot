# v1.0.148 batch 05 — source inventory and release publication

Date: 2026-11-06. Baseline: `5f3fcfb5c4519e5ed1b9b770ba951918819d725d`.

This batch contributes **five distinct behavior improvements**, PR01–PR05.
The LocalDumps transaction and updater available-body reads complete existing
SS04 and IW38 contracts; they add no new count. Tests, benchmark tooling,
documentation and fixture changes add no count. This is a development checkpoint
toward the requested 1,000 improvements, not a published release or an antivirus
verdict.

## Implemented behavior

| ID | Reproduced previous behavior | New behavior and implementation | Regression evidence |
| --- | --- | --- | --- |
| PR01 | `os.walk` silently ignored an unreadable included resource directory. Source validation could return success and publish a ZIP lacking its theme/assets even though all individually required files existed. | `ReleasePackage` propagates included-directory traversal errors in both validation walks and the final inventory. The previous complete archive remains intact and staging is removed. Excluded private trees remain excluded. | `release`: inject failure at each of the three inventory visits, preserve the prior ZIP byte for byte, assert no staging remnants; inaccessible excluded logs are never opened. |
| PR02 | `build_exe.py --help`, misspelled flags and unsupported positional arguments fell through to creating a virtual environment and installing/building packages. | Parse the supported `--onefile` and `--gpu` options before platform or build side effects. Help succeeds without building; unknown options fail immediately. | `release`: help on Windows/Linux and three malformed invocations perform no subprocess call. Existing builder tests still cover normal onedir/onefile/GPU behavior. |
| PR03 | The release workflow checked the versioned tag name and draft metadata but not the actual Git ref. GitHub ignores `target_commitish` when a tag already exists, so binaries from the current build could be published under a preexisting tag pointing elsewhere. | `ReleaseIdentity` resolves the exact ref, peels bounded nested annotated tags and requires the build SHA. Verification is read-only by default. The workflow may explicitly create only a missing tag at that SHA, re-read creation races, and use `gh release create --verify-tag`. A second read verifies identity immediately before publication. Existing refs are never updated or deleted. The helper is required by source packaging and the source gate. | `identity`: lightweight/nested tags, wrong commit, missing/read-only default, exact creation, 409/422 races, permission failures, malformed/cyclic objects and structured subprocess input. Workflow ordering verifies before creation and after upload. All API behavior is mocked; no live tag was created or modified by these tests. |
| PR04 | Main, tag and manual workflow runs used different ref-specific concurrency groups while they could resume the same versioned draft. Their clobbering uploads could interleave, mixing two independent builds' ZIP/installer/checksum/manifest assets. | Use one repository release-workflow concurrency group, `cancel-in-progress: false` and `queue: max`. Cooperating publishers run serially without replacing the sole pending request. | `identity`: a concrete mixed-build asset/checksum fixture, shared group expansion for main/tag runs, no running cancellation and queued-request policy. This is distinct from PR03: a correct shared commit does not make independently produced executable bytes identical. |
| PR05 | The one-shot source hygiene check traversed every private builder/output tree and treated an upstream `check_once.py` inside `.build-venv` or the frozen output as repository source. It also scanned `.git` fully before discarding findings. | Prune the same excluded directory names and links as source packaging. Keep genuine source and workflow one-shot detection, reject included-directory traversal errors and avoid per-file metadata queries for irrelevant filenames. | `release`: private directories are never opened; real root/workflow findings remain; similarly named workflow-backup directories are not misclassified; included traversal errors cannot appear as a clean tree. The paired benchmark below verifies identical source findings. |

## Existing-contract completions, not new improvements

- **SS04 — coherent LocalDumps undo transaction.** `CrashDumpConfig.configure`
  now holds `file_transaction` for the shared undo path across its backup read,
  backup publication, native writes/restoration and backup update. Previously,
  Disable could consume Enable's freshly saved undo before its registry writes,
  leaving the override active with no saved original. Event-controlled fake
  registry tests reproduce that interleaving and a partial native-write failure.
  The cooperating transaction preserves recoverable undo and releases its lock
  after failure. This does not claim an atomic transaction with arbitrary
  external registry editors or operations using a different user's backup path.
- **IW38 — updater reads available response data.** `UpdateCenter` now uses
  `urllib3.HTTPResponse.read1(..., decode_content=True)` for normal Requests
  responses. Both release metadata and installer transfers can check Stop and
  the elapsed budget while small chunks continue arriving. File-like custom
  transports retain Requests' `iter_content` compatibility. Real loopback HTTP
  regressions send one byte at a time, verify interruption before the full body,
  close the response and remove partial installer data. Compressed metadata
  remains decoded and subject to the decoded-size limit. A blocked connection,
  header or socket read still follows its existing network timeout; these are
  cooperative checks between available reads, not a hard wall-clock guarantee.

## Reproducible measurement

Run from the repository root:

```sh
python benchmark_v148_platform_release.py --output docs/v148-batch05-platform-benchmarks.json
```

The script extracts the historical hygiene function from the exact baseline
commit and creates a local synthetic tree with 402 included files and 6,000
excluded files under `.git`, `.build-venv` and `dist`. Both implementations must
return the same two intentional source findings. Five timing pairs alternate
execution order after warming imports and filesystem metadata. Allocation peaks
are measured separately from timing.

| Source-hygiene measurement | Baseline | Updated |
| --- | ---: | ---: |
| Median elapsed time | 192.760 ms | 0.805 ms |
| Peak traced Python allocation | 448,046 bytes | 10,036 bytes |

The raw samples, Python/platform identity and fixture description are in
`docs/v148-batch05-platform-benchmarks.json`. This result applies to the specified
synthetic local filesystem traversal. It is not an overall build, application,
Windows or GPU performance claim; traced Python allocation is not process RSS.

## Validation

The four new test modules contain **26 focused tests**:

- `test_v148_platform_batch05_release.py` — 7 tests.
- `test_v148_platform_batch05_dumps.py` — 2 tests.
- `test_v148_platform_batch05_identity.py` — 13 tests.
- `test_v148_platform_batch05_update.py` — 4 tests.

The combined new and related builder, source archive, release gate, variant,
cleanup, installer, LocalDumps and updater suite completed **181 tests in 3.914
seconds**, passing with four native-Windows checks skipped on this Linux host.
`git diff --check` passed for the owned changes. These are local test results;
the final combined checkpoint and native Windows CI remain integration gates.

Existing fixture changes only adapt `build_exe.main([])` to the explicit CLI
parser and include the new required identity helper in the synthetic source
tree. Historical application versions in fixtures remain unchanged.

## Review boundaries and primary references

- No release workflow was triggered and no tag, release, asset, registry entry,
  signing credential or installed package was changed during validation. Live
  HTTP tests use only a test-owned loopback server.
- Publication checks bind a tag immediately before operations; they cannot
  prevent an unrelated authorized external actor from later changing GitHub
  state. The concurrency group coordinates this repository's release workflow.
- The GitHub CLI metadata client has request timeouts and a parsed-body limit.
  `capture_output` still collects subprocess output before that limit; this is
  not claimed as a strict bound on subprocess-output memory.
- [GitHub create-release API](https://docs.github.com/en/rest/releases/releases#create-a-release): an existing tag makes `target_commitish` unused.
- [GitHub CLI release create](https://cli.github.com/manual/gh_release_create): `--verify-tag` requires the remote tag instead of implicitly creating it.
- [GitHub workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency): a shared concurrency group serializes publishers; `queue: max` retains multiple pending runs.
- [urllib3 HTTPResponse](https://urllib3.readthedocs.io/en/stable/reference/urllib3.response.html): `read1` supports available buffered reads and explicit content decoding.
