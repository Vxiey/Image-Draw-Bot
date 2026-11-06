# v1.0.148 batch08 — coherent releases and private builds

Baseline: `73788a51c1a3502f03f007e4d2ffe0152f56b7e6` (745 registered improvements).

Current batch scope: **two distinct improvements, BP01–BP02**. Tests,
documentation, individual failure cases and repeated caller substitutions do
not add counts. The InstanceLock and source-startup changes below complete
original026 and original022/GP01 at zero additional count.

## Changes and evidence

| ID | Previous public behavior | Implementation and regression evidence |
| --- | --- | --- |
| BP01 | `build_release.main` replaced the finished ZIP before compiling its installer or writing the related metadata. Starting with a complete gate-valid release and injecting an ISCC failure left a new ZIP beside the old installer, checksum and manifest; the previously valid set then failed its checksum gate. | Build every selected artifact and metadata file in one unique staging directory, direct ISCC output there with `/O`, and run the actual variant/checksum/manifest gate before publication. `ReleasePublication.publish_release` keeps the old files in a private backup while moving the complete new set into place under a cooperating file transaction. On move errors it restores previous files and previous absence. Retire only known obsolete standard/CUDA/installer outputs of this exact version; preserve unrelated notes and other versions. Real public-builder tests mock external tools only and use real ZIPs, hashes, manifests and gates. They inject compiler, signer, metadata, final-gate and every backup/candidate-move failure. |
| BP02 | `Build-Release.bat` selected base Python, then `build_release` upgraded pip and installed requirements into that caller environment. Release tests ran there while PyInstaller used a separate `.build-venv`, so the build could alter unrelated host packages and test different dependencies from those being bundled. | `BuildEnvironment.prepare_builder` creates/reuses the private environment, verifies its actual prefix, architecture, supported Python and isolated site directories, and applies the existing pip-target policy before any package changes. Install build/runtime/selected GPU requirements once into that interpreter. Both release test processes and `build_exe.build_application` use it and an explicit trusted source path. Direct `build_exe.main` uses the same preparation; the batch launcher ignores inherited Python startup overrides. Proxy, CA, index and ordinary pip configuration remain available, while target/prefix/root/user/interpreter relocation and inherited Python startup overrides cannot redirect installation. Public-entry tests replace external processes, assert that every pip operation targets the private interpreter, and check shared test/packaging execution. A real no-pip temporary venv probe also distinguishes isolated environments from ones exposing system site packages. |

### Distinct scope and preserved behavior

SR23 already made a single ZIP publication atomic and preserved old outputs on
early dependency/compression failures. It explicitly did not provide a
transaction across all assets. BP01 addresses the later compiler/metadata/gate
failure that previously left an inconsistent set, plus the corresponding
multi-file publication rollback. It does not recount the ZIP writer.

GP01 already isolated optional GPU package setup. BP02 reuses that established
pip policy in the separate public release-building flow, whose host dependency
installation and split test/bundle environments remained unchanged by GP01.
It is one build-environment behavior, not a count per pip flag or script.

`--skip-tests` still skips the explicitly requested duplicate source test run in
CI. It does not skip preparing the builder, constructing the executable, the
packaged `--self-test`, signatures when requested, or the final artifact gate.
Standard ZIP-only, standard ZIP+installer and separate CUDA ZIP builds remain
supported. The impossible CUDA+installer combination still fails before build
side effects.

## Failure and durability limits

- Publication performs a bounded number of moves for the small known artifact
  set; it does not read complete binary assets into memory. Existing bounded
  Windows replacement retry is reused.
- If exception rollback itself cannot restore a file, the original exception
  remains primary and identifies the private backup directory. Original bytes
  remain there for recovery instead of being erased by staging cleanup.
- Backup cleanup occurs after the commit point. A cleanup failure reports the
  retained backup location and leaves the new gate-valid set intact.
- This is exception rollback, **not power-loss atomicity across multiple
  filesystem names**. A crash during the move sequence can require recovery
  from the retained backup. Cooperating publishers share a stable file lock;
  this is not a claim that two simultaneous full builds can safely share their
  mutable PyInstaller `dist`/work directories.
- Private dependency installs still honor the repository's supported version
  ranges. This does not introduce a fully locked/reproducible dependency graph
  or claim that an intentionally skipped source suite ran in the new builder.
- Portable tests simulate external Windows tools. Actual Windows packaging,
  signing when configured, and native application checks remain CI gates.

## Existing-contract completion — zero new count

Original026: `InstanceLock` now obtains `kernel32` through
`WindowsSystem.load_system_library(..., use_last_error=True)` like the other
system-DLL consumers. The mutex name, already-running result and idempotent
close behavior are unchanged. Two focused tests preserve that behavior and
ensure loader failure has no bare-library fallback. The helper/instance suite
passed **14 tests, one Windows-only skip** locally.

Original022/GP01: the remaining plain pip calls in `Start.bat` allowed inherited
`PIP_TARGET` to select an external directory and `PYTHONPATH` to import an
unrelated startup hook. Both were reproduced with the real installed pip
parser and a harmless temporary marker, without installing a package.
`SourceStartup` now verifies the actual `.venv` prefix, minimum supported
Python and isolated site directories before dependency work. It reuses
`GpuSetupRuntime`'s private pip command/configuration policy, installs only the
source runtime requirements, and publishes the requirements stamp after a
successful dependency check. Application and optional GPU children receive a
controlled source path and Python startup settings. The batch entry retains
existing Python discovery, log location, exit/error presentation and explicit
`--gpu`/`--update`; normal cached startup does not install optional GPU packages.
Proxy/index/CA policy is retained, a pip-upgrade failure can still use the
existing pip, and optional GPU failure retains CPU startup. Source/runtime
requirements remain separate from release build requirements.

The source release's required inventory now includes these delegated startup
and build helpers, so a source ZIP missing its entry-point implementation
cannot pass the existing completeness gate.

Existing settings-save failure contract: `DrawBot._install_checked_update`
now respects `save_settings() is False` before consuming the pending request
or scheduling installation. Previously a real storage failure or protected
future-schema document could still lead to an installer launch and application
closure. `test_v148_platform_batch08_update_start.py` uses the actual settings
writer for injected disk failure, protected-schema refusal and successful
save/verified-launch scheduling. This is a caller completion, not another ID.

## Validation

New focused modules:

- `test_v148_platform_batch08_build.py`: six cases, including actual isolated
  venv probes created with `--without-pip` and no network installation.
- `test_v148_platform_batch08_release.py`: six cases, with multiple controlled
  failure positions exercised inside the real public release workflow.
- `test_v148_platform_batch08_instance.py`: two original026 completion cases.
- `test_v148_platform_batch08_startup.py`: six portable cases and one Windows
  batch-entry case. Public startup tests mock external setup/application
  processes; actual temporary-venv probes and pip option parsing use only
  Python's bundled ensurepip, without network installation. A Windows-only
  fixture runs the actual batch launcher with a harmless entry stub and checks
  flag forwarding, startup isolation and success/failure exit status.

Combined with existing release variants, documentation packaging, supported
builder rejection, batch02 release safety, batch05 release/CLI and batch03 pip
isolation tests: **55 tests passed, 5.084 seconds**, no skips in this combined
selection. Existing fixtures now intercept the prepared-builder boundary or
the staged ISCC output path; their resource/variant/privacy assertions remain.

The source-startup completion and related GPU/setup modules passed **46 tests
in 6.584 seconds**. Its final source-packaging selection passed **21 tests in
5.819 seconds, one native Windows skip**. Actual batch-file execution remains
part of the Windows run; it was not executed on this Linux host.
The updater-save completion plus existing settings/update/install modules
passed **46 tests in 0.022 seconds, one native Windows skip**.

No network package installation, signing operation, application EXE launch,
remote publication or repository staging/commit occurred in these tests. No
speedup or memory-RSS measurement is claimed for these correctness changes.

IW38 completion: raster downloads request `Accept-Encoding: identity` and reject
unrequested non-identity HTTP encodings before reading their body. Real
Requests/urllib3 reproduction with 8,000 empty gzip members plus a tiny valid
PNG consumed the whole 160 KiB wire stream inside one decoded read, postponing
the importer’s Stop/deadline checks. No unbounded gzip allocation was observed.
The final import now rejects that response without consuming body bytes; an
identity transfer returns to Stop/deadline checks after the available 4 KiB
chunk in the test transport. Relative redirects retain their existing unread-
body handling. A server that insists on HTTP compression must be downloaded
locally and opened as a file; local compressed raster formats remain supported.
Four real Requests/urllib3 transport regressions and related import/keyboard/
updater checks passed 29 tests with two Windows-only skips. This is a bounded
network cancellation completion, not a new counted feature.

## Primary implementation references

- [Python virtual environments](https://docs.python.org/3/library/venv.html):
  per-environment packages, interpreter/prefix behavior and creation.
- [pip configuration](https://pip.pypa.io/en/stable/topics/configuration/):
  environment/configuration precedence. The existing shared policy snapshots
  permitted settings rather than editing the user's configuration files.
- [Inno Setup compiler options](https://jrsoftware.org/ishelp/topic_compilercmdline.htm):
  the per-invocation output-directory override directs the installer into the
  same candidate workspace as its ZIP and verification metadata.
