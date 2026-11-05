# Antivirus report review — 2026-11-05

## Artifact identified

The report linked in [issue #32](https://github.com/Vxiey/Image-Draw-Bot/issues/32)
concerns the portable Windows ZIP from
[v1.0.146-rc2](https://github.com/Vxiey/Image-Draw-Bot/releases/tag/v1.0.146-rc2).
Its SHA-256 matches GitHub's published release-asset digest:

| Artifact | SHA-256 | Report |
| --- | --- | --- |
| `ImageDrawBot-1.0.146-rc2-Windows-x64.zip` | `ae89acc95fc7490f50942deac76084c936e7ab9e0f20ce66daf51c1c7fe29818` | [VirusTotal ZIP report](https://www.virustotal.com/gui/file/ae89acc95fc7490f50942deac76084c936e7ab9e0f20ce66daf51c1c7fe29818) |
| Embedded `ImageDrawBot.exe` | `962193c4f79393ac004b46902636e0fa8c30f43d17d5aaa91c7b0cf242d07c28` | [VirusTotal executable report](https://www.virustotal.com/gui/file/962193c4f79393ac004b46902636e0fa8c30f43d17d5aaa91c7b0cf242d07c28) |

The release was published on 2026-09-13 from commit
`68b5894a25a838cf94104bdd0118e48f2e8f3d6b`. The review used repository source,
existing local dependency metadata, GitHub release metadata and the public
VirusTotal report pages. The reported ZIP and its executables were not downloaded
or executed during the review.

## What the reports show

At the time of review, the ZIP report displayed 2/62 detections, from Bkav Pro
(`W32.Malware.87A5D6BC`) and Zillya (`Trojan.Blank.Script.2228`), with a last
analysis date of 2026-10-26. Its Code insights summary described legitimate
CustomTkinter, PyOpenCL and TkinterDnD2 code but labeled the package
`customtkinter (whl)`. The exact hash establishes that the submitted artifact
is the application ZIP. That summary does not establish the runtime behavior
of the embedded executable.

The ZIP's Relations tab identifies the embedded executable above. Its separate
report, last analyzed on 2026-10-29, displayed 3/69 detections: the same Bkav Pro
label, SecureAge `Malicious`, and Skyhigh `BehavesLike.Win64.Backdoor.tc`.
Zillya reported that executable as undetected. Consequently, removing unrelated
files from the ZIP alone cannot establish that all reported detections are fixed.

The executable's Details page reports that it is unsigned. The Behavior page
shows informational capability matches; it does not show detected network
communications in the available report. Neither that absence nor the number of
engines reporting undetected is proof that an artifact is safe.

The ZIP also included TkinterDnD2 native extensions for multiple platforms.
Its win-x86 DLL had 2/56 detections and its required win-x64 DLL had 1/68 at
their respective July analysis dates. Those were different vendors from the
ZIP's two detections. Required native functionality must not be removed solely
to suppress a scanner result.

Both DLL hashes also matched the corresponding files already present in the
local TkinterDnD2 dependency installation. This establishes that the copies are
identical; it does not independently certify the dependency or the whole bundle.

## Source findings and fixes

### Windows bundle contents

The previous build recursively added `docs` at the bundle root. This included
three archived source releases and could collide with root documentation names.
Two archived `Collect-Diagnostics.bat` scripts still contained obsolete
`-ExecutionPolicy Bypass` commands that are absent from the current diagnostic
script. The archived scripts were inert bundled data; their presence is not
proof that they caused an antivirus detection.

The build now stages filtered documentation under `docs/`, preserving help paths
and assets while excluding `docs/history/archives`. The staging keeps the
PyInstaller command line bounded and is automatically cleaned up.

TkinterDnD2 now uses its supported PyInstaller hook instead of indiscriminately
collecting every platform's native extension. The required x64 DLL and Tcl
resources remain. CustomTkinter and PyOpenCL collection and package metadata
remain available for their runtime features and diagnostics.

The Windows ZIP gate rejects archived source releases and TkinterDnD2 native
extensions for other platforms. Standard builds continue to use `--onedir` and
`--noupx`.

The optional CUDA build also had a filename mismatch: it created a `-CUDA.zip`
but validated the standard ZIP name. Release validation now selects the requested
variant explicitly and rejects the unsupported CUDA installer combination before
starting a build. This prevents a valid CUDA package from failing its final gate
or accidentally validating an unrelated standard package.

### Paint preparation

The Paint helper uses Windows UI Automation to inspect Paint controls and select
tools or RGB controls. Its process-name checks, control identity checks, numeric
limits, cancellation and time limits remain in place. The PowerShell transport
is changed from Base64 `-EncodedCommand` to readable script input. JSON element
data remains literal data, including Unicode labels and quote characters.
No execution-policy override is added.

This makes the implementation more transparent; it is not a claim that a
particular vendor's signature has been identified or cleared.

### Diagnostic tool launch

The old `cmd /c start` command could interpret an ampersand in the application
directory as a command separator. The launcher now uses the Windows file-open
API with the tool path and working directory passed separately. It checks for
missing files and reports launch failures.

### Diagnostic privacy

Failed image downloads can include signed URLs in exception text. The previous
sanitizer could leave URL usernames/passwords and signed query values in an
exported diagnostics ZIP. The sanitizer now removes URL credentials, query and
fragment data, authorization credentials and credential-like fields. Logs keep
the host, resource path and error context where possible. Diagnostics are still
created locally and are not automatically uploaded.

## Validation and remaining limits

Regressions exercise diagnostic exports with synthetic credentials, Windows
tool launches from paths containing spaces and ampersands, and Paint script
parsing and transport without sending desktop input. Windows CI also builds the
actual portable bundle, validates its contents and runs the packaged GUI smoke
test, including native drag and drop. Validation results are recorded in the
associated pull request and GitHub Actions run.

Static review of the examined input, update, network, diagnostics and packaging
paths found no implementation of credential theft, unsolicited uploads,
antivirus exclusions or startup persistence. That is a scoped source finding,
not a certification of every dependency or of the previously published binary.

The reported release remains unchanged. A new release must be built and the
exact new artifacts rescanned before claiming that detections have disappeared.
Trusted publisher verification also requires a provisioned code-signing
certificate; metadata alone cannot supply it. See
[Windows code signing](WINDOWS-CODE-SIGNING.md). Existing support for signing
remains in place, and signing alone is not antivirus clearance.
