# Image Draw Bot v1.0.146-rc3 — Security & Windows Packaging

This release candidate publishes the dependency, security and Windows packaging
fixes merged after v1.0.146-rc2.

## Security and stability

- Require Pillow 13 and Requests 2.34.2 or newer within their supported major
  version ranges. Source runs and builds now require Python 3.11 or later;
  Windows installer and portable packages include their own Python runtime.
- Validate updater redirect destinations before contacting them, bound release
  metadata downloads, and preserve size and SHA-256 verification before an
  installer can run.
- Reject unsafe or unverifiable drawing-area geometry before mouse input and
  preserve brush clearance around slanted boundaries.
- Handle malformed image drag-and-drop candidates without losing later valid
  images, and preserve signed URL escaping.
- Isolate mobile-preview sessions so old tokens and connections cannot access
  images from a later session.
- Redact credentials, signed URL parameters and sensitive fragments from
  diagnostic exports, including long or truncated log entries.
- Open diagnostic tools safely from installation paths containing spaces or
  ampersands, with clear errors for missing files or launch failures.
- Keep user settings, calibration, recovery data and runtime artifacts out of
  generated source packages.

## Windows packaging and Paint automation

- Exclude historical source ZIPs from Windows bundles, including obsolete helper
  scripts in those archives, and preserve help files under their proper paths.
- Use the supported TkinterDnD2 packaging hook to include only the required
  native architecture, while retaining drag-and-drop resources and metadata.
- Replace Base64-encoded PowerShell command transport with readable script
  input. Control names remain literal data; Unicode handling, cancellation and
  the execution timeout are preserved and tested on Windows.
- Correct optional CUDA artifact validation to check the explicitly selected
  CUDA ZIP. Reject unsupported CUDA installer builds before starting build work.
- Build and smoke-test the actual portable Windows GUI in CI, including native
  drag and drop, in addition to the complete regression suite and dependency
  security audits.

## Downloads and verification

The Windows release provides a portable ZIP, a Setup installer, a SHA-256
checksum file and a release manifest. Publication is gated by source checks,
regressions, executable self-tests, package validation and a silent
install/self-test/uninstall round trip.

The Windows executables remain unsigned. A code-signing certificate is not
configured, so Windows may display an unknown-publisher or reputation warning.
These changes do not claim that every antivirus engine will return zero
detections. Scan the exact release artifact and compare its SHA-256; a result
for a source archive does not establish the result for the Windows executable.

For the investigation and implementation details, see the
[security review](https://github.com/Vxiey/Image-Draw-Bot/blob/v1.0.146-rc3/docs/SECURITY-HARDENING-2026-11.md),
[antivirus report review](https://github.com/Vxiey/Image-Draw-Bot/blob/v1.0.146-rc3/docs/ANTIVIRUS-REVIEW-2026-11.md),
[PR #33](https://github.com/Vxiey/Image-Draw-Bot/pull/33) and
[PR #42](https://github.com/Vxiey/Image-Draw-Bot/pull/42).
