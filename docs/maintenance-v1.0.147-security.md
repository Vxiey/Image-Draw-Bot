# v1.0.147 security and release maintenance: improvements 026–050

These 25 entries describe changes to application behavior or release validation. Tests, documentation, version changes and equivalent DLL call sites are not counted as separate improvements.

## Implemented changes

| ID | Behavior improved | Code path | Regression coverage |
| --- | --- | --- | --- |
| 026 | Windows OS DLLs used by DPI, taskbar and shared native helpers load with `LOAD_LIBRARY_SEARCH_SYSTEM32` before PyInstaller can rewrite a bare filename into the bundle. OS directory discovery uses Windows APIs rather than environment variables. | `WindowsSystem.load_system_library`, `system_directory`, `program_files_directories`; `DpiSupport`, `TaskbarIdentity`, `CrashDumpConfig` consumers | `test_windows_system`: exact native flags and handle transport; invalid names; wrapper failure cleanup; native Windows same-named bundle-file regression; known-folder allocation cleanup |
| 027 | Failure to load the Windows DPI provider returns a safe 96-DPI default instead of aborting target inspection. | `DpiSupport.get_window_dpi_info` | `test_dpi_lookup_load_failure_retains_safe_default` |
| 028 | Taskbar properties reject a null COM store, avoid dereferencing null text and clear allocated PROPVARIANT output even when `GetValue` fails. | `TaskbarIdentity.WindowProperties` | Null-store, null-text and failed-GetValue cases in `test_windows_system` |
| 029 | A diagnostics ZIP appears at its final path only after collection and ZIP closure succeed; interrupted collection removes the temporary archive. | `DiagnosticsPackage._atomic_archive` | Failed-collection cleanup and pre-publication CRC/content validation |
| 030 | Settings and calibration collection limits each JSON input to 4 MiB and each summary to 100 files, preventing unbounded exports from corrupted local state. | `DiagnosticsPackage._json_input`, `_settings_summary`, `_calibration_summary` | Oversized valid JSON is skipped; summary file count is bounded |
| 031 | Diagnostics omit linked settings, calibration files and logs, including linked parent directories and Windows junctions. | `DiagnosticsPackage._regular_input` | Real file and directory symlink regressions |
| 032 | Diagnostics include the consolidated debug-error log and its rotated copy, with the same redaction as other exported logs. | `DiagnosticsPackage.create_diagnostics_package` | Both error-log generations appear without cookie values |
| 033 | Calibration version metadata cannot copy an arbitrary nested object into an otherwise summarized export; string versions are sanitized and limited. | `DiagnosticsPackage._calibration_summary` | Nested private values are omitted; oversized secret-bearing strings are sanitized and bounded |
| 034 | Cookie and Set-Cookie headers are redacted in plain logs and quoted JSON fields. | `LocalSanitization._COOKIE_RE`, `sanitize_text` | Multiple header casings, multi-cookie values and JSON preservation |
| 035 | Shared logs redact common Windows user paths on drives other than C, plus Linux and macOS home paths. Missing home-directory lookup does not disable other redaction. | `LocalSanitization.sanitize_text` | D/E-drive, `/home`, `/Users` and unavailable-home cases |
| 036 | Non-finite numeric context is omitted so diagnostics metadata remains valid strict JSON. | `LocalSanitization.safe_context` | NaN and both infinities; strict `allow_nan=False` serialization |
| 037 | Python-generated session, error and exception records redact credentials before writing them locally. Export sanitization remains a second boundary. | `CrashDiagnostics._record_text`, `log_event`, exception hooks | Persisted session/error and unhandled-exception files contain context but no signed-link/auth secrets |
| 038 | Individual application log records are limited to 64 Ki characters after sanitization; rotation considers the incoming record size. | `CrashDiagnostics._record_text`, `_rotate_if_large` | Long secret-bearing record and pre-append rotation tests |
| 039 | Direct worker-error writes, log rotation and Python exception-stream writes share the reentrant log lock. | `CrashDiagnostics._append_error`, exception hooks | Concurrent direct error writes remain complete; rotation is observed under the lock |
| 040 | Runtime ZIP validation rejects traversal, absolute paths, unexpected roots, alternate data streams, reserved Windows names and trailing-dot/space aliases. | `ReleaseCandidateHardening._safe_windows_parts`, `_validate_zip_entries` | Synthetic ZIPs for each unsafe path class |
| 041 | Runtime ZIP validation rejects duplicate paths under Windows case/separator rules and file-versus-directory collisions. | `ReleaseCandidateHardening._validate_zip_entries` | Exact, case and separator duplicates; file used as another entry's parent |
| 042 | Runtime ZIP validation rejects symbolic links and special-file metadata. | `ReleaseCandidateHardening._validate_zip_entries` | Symlink, FIFO and device entry fixtures |
| 043 | Release build and validation inspect only the two-byte executable header instead of reading whole EXEs into memory. Hashing and CRC validation continue to stream complete content. | `build_release.is_pe_executable`; `ReleaseCandidateHardening.validate_installer`, `validate_windows_zip` | Header checks succeed while whole-file and whole-member reads are forbidden |
| 044 | Checksum validation accepts only safe unique basenames and verifies exact coverage of the selected standard/CUDA release artifacts. | `ReleaseCandidateHardening.verify_checksum_file`, `validate_windows_release` | Unsafe reads blocked; duplicate, missing and unexpected targets rejected; existing variant fixtures retained |
| 045 | Manifest validation rejects malformed roots/rows, duplicate or unexpected artifacts, unsafe names, boolean schema values and non-integer sizes; generator inputs are fully verified. | `ReleaseCandidateHardening.validate_manifest` | Shape, duplicate, path, size/schema and generator/hash regressions |
| 046 | Source archive creation preserves a previous archive on failure and atomically replaces it on success. The destination is excluded even through a `..` path; an output symlink is replaced without changing its target. | `ReleasePackage.create_source_archive` | Interrupted write, self-inclusion and destination-symlink regressions |
| 047 | Under the same Python/zlib build, identical source contents produce identical ZIP bytes with fixed source-entry timestamps and permissions, independent of checkout mtimes and umask. | `ReleasePackage.create_source_archive` | Byte-for-byte equality after changing input mtimes and permissions |
| 048 | Source archives do not follow file/directory links or Windows junctions; runtime privacy exclusions also apply to Windows case variants. | `ReleasePackage._is_link`, `_parts`, `iter_release_files` | External file/folder links, junction tags, uppercase private files and preserved documentation examples |
| 049 | Isolated target results reject boolean/invalid native IDs, invalid or empty rectangles and inconsistent DPI scaling. An explicit HWND probe must return that same window. | `TargetCapture._native_id`, `_window_rectangle`, `_run`, `probe_handle_isolated` | Native-ID, rectangle, non-finite scale, wrong-window and non-object JSON cases; valid negative monitor coordinates retained |
| 050 | LocalDumps setup/restoration validates the complete saved configuration and all planned originals before any registry mutation. A changed later target can no longer leave an earlier target partially configured. | `CrashDumpConfig._validate_backup`, `configure` | Invalid later entries and changed later targets cause zero writes; undo-before-write and externally changed values remain supported |

## Validation and limits

Focused regression modules are `test_windows_system`, `test_diagnostics_maintenance_rc4`, `test_release_maintenance_rc4` and `test_native_safety_maintenance_rc4`. Existing diagnostics, DPI/taskbar, target-capture, source-release, checksum/manifest, standard-release and CUDA-release tests are also retained.

The combined scoped Linux run passed 162 tests with three native Windows tests skipped. `git diff --check` was clean. The repository-wide suite and Windows CI are separate integration gates.

The native Windows DLL test needs Windows. It creates a harmless text file with a DLL filename, models the frozen filename rewrite, loads the actual system library and checks the loaded module's path. Linux tests verify the loader boundary and error handling with mocks. Native integration and the packaged smoke test remain Windows CI checks.

The log-write changes cover Python-generated application text. Native `faulthandler` output still writes directly to its crash-log descriptor; diagnostics export sanitizes that text before sharing. Source ZIP reproducibility changes source-archive metadata only, not the timestamp or identity of an application executable.

The reviewed certificate-related code does not establish the cause of the external antivirus/Sigma certificate-store alert. `CrashDumpConfig` writes only the named application's values below `HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps`. Existing opt-in `CodeSigning.validate_certificate` reads a provisioned certificate from `Cert:\CurrentUser\My`; it does not import a root certificate. None of these changes introduces certificate creation, certificate import or trust-store edits.

## Primary references used in the native/archive design

- [Microsoft: LoadLibraryExW search flags](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw)
- [CPython 3.12.12: native ctypes LoadLibrary boundary](https://github.com/python/cpython/blob/v3.12.12/Modules/_ctypes/callproc.c)
- [PyInstaller 6.22.3: frozen ctypes filename rewriting](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/PyInstaller/loader/pyimod03_ctypes.py)
- [Microsoft: GetSystemDirectoryW](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getsystemdirectoryw)
- [Microsoft: SHGetKnownFolderPath allocation and cleanup](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath)
- [Microsoft: known-folder identifiers and architecture behavior](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid)
- [Microsoft: Windows file naming rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
- [Python: ZIP metadata and streaming archive access](https://docs.python.org/3.12/library/zipfile.html)
