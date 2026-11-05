# Security and runtime fixes — 2026-11-05

## Dependency remediation

The repository had 26 open Dependabot alerts, all in the Pillow requirement.
Every alert listed `13.0.0` as the patched version. The old range,
`Pillow>=11.2.1,<13`, explicitly excluded that version.

- Require `Pillow>=13.0.0,<14` and `requests>=2.34.2,<3`.
- Require Python 3.11+ for source runs and builds, matching [Pillow 13's Python support](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html#python-3-10).
- Upgrade transitive dependencies when the source launcher installs changed requirements or the user runs `Start.bat --update`, and when preparing release/build environments.
- Make PyInstaller's dependency visible in `requirements-build.txt`.
- Configure weekly Dependabot checks for pip and GitHub Actions.
- Audit application, test, build, OpenCL and optional CUDA dependency manifests in CI on Linux/Python 3.11 and Windows/Python 3.12.

Existing Python 3.10 source/build environments cannot install Pillow 13.
The launchers stop with an actionable migration message. Install 64-bit Python
3.11 or later and rename the old `.venv` or `.build-venv` before recreating it.
Existing environments already using a supported interpreter can be upgraded normally.

### Dependabot alerts

| Alert | Advisory | Fixed Pillow version |
| --- | --- | --- |
| [#1](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/1) | [GHSA-65qm-jvmh-6pqg](https://github.com/advisories/GHSA-65qm-jvmh-6pqg) | 13.0.0 |
| [#2](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/2) | [GHSA-462x-pgg6-55fp](https://github.com/advisories/GHSA-462x-pgg6-55fp) | 13.0.0 |
| [#3](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/3) | [GHSA-c6hw-5grf-ff96](https://github.com/advisories/GHSA-c6hw-5grf-ff96) | 13.0.0 |
| [#4](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/4) | [GHSA-q45j-58j2-45rg](https://github.com/advisories/GHSA-q45j-58j2-45rg) | 13.0.0 |
| [#5](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/5) | [GHSA-p4wg-p73j-c528](https://github.com/advisories/GHSA-p4wg-p73j-c528) | 13.0.0 |
| [#6](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/6) | [GHSA-j4m9-6w36-pw47](https://github.com/advisories/GHSA-j4m9-6w36-pw47) | 13.0.0 |
| [#7](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/7) | [GHSA-fc9g-5qg7-mf45](https://github.com/advisories/GHSA-fc9g-5qg7-mf45) | 13.0.0 |
| [#8](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/8) | [GHSA-rfgq-q3w2-pmv2](https://github.com/advisories/GHSA-rfgq-q3w2-pmv2) | 13.0.0 |
| [#9](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/9) | [GHSA-22hg-r758-rrw9](https://github.com/advisories/GHSA-22hg-r758-rrw9) | 13.0.0 |
| [#10](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/10) | [GHSA-5xm2-6676-qcp9](https://github.com/advisories/GHSA-5xm2-6676-qcp9) | 13.0.0 |
| [#11](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/11) | [GHSA-74r2-7ff9-mjj2](https://github.com/advisories/GHSA-74r2-7ff9-mjj2) | 13.0.0 |
| [#12](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/12) | [GHSA-w889-685w-c8fh](https://github.com/advisories/GHSA-w889-685w-c8fh) | 13.0.0 |
| [#13](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/13) | [GHSA-f2g6-542v-9j58](https://github.com/advisories/GHSA-f2g6-542v-9j58) | 13.0.0 |
| [#14](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/14) | [GHSA-254f-3936-288h](https://github.com/advisories/GHSA-254f-3936-288h) | 13.0.0 |
| [#15](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/15) | [GHSA-gg2r-wvfm-q9rx](https://github.com/advisories/GHSA-gg2r-wvfm-q9rx) | 13.0.0 |
| [#16](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/16) | [GHSA-jg86-v3jv-hrpm](https://github.com/advisories/GHSA-jg86-v3jv-hrpm) | 13.0.0 |
| [#17](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/17) | [GHSA-332p-7hrc-92wf](https://github.com/advisories/GHSA-332p-7hrc-92wf) | 13.0.0 |
| [#18](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/18) | [GHSA-78g4-xqwv-q3g8](https://github.com/advisories/GHSA-78g4-xqwv-q3g8) | 13.0.0 |
| [#19](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/19) | [GHSA-g4qv-2jxx-769h](https://github.com/advisories/GHSA-g4qv-2jxx-769h) | 13.0.0 |
| [#20](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/20) | [GHSA-v9pv-5gc8-w2m6](https://github.com/advisories/GHSA-v9pv-5gc8-w2m6) | 13.0.0 |
| [#21](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/21) | [GHSA-24rc-8hj2-v98c](https://github.com/advisories/GHSA-24rc-8hj2-v98c) | 13.0.0 |
| [#22](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/22) | [GHSA-p8hx-v2p6-rp84](https://github.com/advisories/GHSA-p8hx-v2p6-rp84) | 13.0.0 |
| [#23](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/23) | [GHSA-9v9v-9qvf-h2hj](https://github.com/advisories/GHSA-9v9v-9qvf-h2hj) | 13.0.0 |
| [#24](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/24) | [GHSA-4rm8-3hmm-39fg](https://github.com/advisories/GHSA-4rm8-3hmm-39fg) | 13.0.0 |
| [#25](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/25) | [GHSA-g842-9rc4-69pw](https://github.com/advisories/GHSA-g842-9rc4-69pw) | 13.0.0 |
| [#26](https://github.com/Vxiey/Image-Draw-Bot/security/dependabot/26) | [GHSA-mrfp-p49p-3hf2](https://github.com/advisories/GHSA-mrfp-p49p-3hf2) | 13.0.0 |

## Updater

Validate each redirect destination before sending a request. Require HTTPS,
trusted GitHub/API/CDN hosts, no embedded credentials and no unexpected ports.
Limit redirect hops and close rejected responses without consuming their bodies.

Release metadata is streamed with a 16 MiB limit on actual decoded bytes.
Malformed release/asset metadata and oversized version tags fail safely.
Installer downloads still require the published size, SHA-256 and Windows
executable header, and are rehashed before launch. Signed GitHub CDN query
parameters remain supported.

## Drawing-area guard

Remove the centroid-shrink fallback that could place points outside a concave
canvas. Require the full brush/edge margin and verify every inset vertex against
the inward edge constraints. Reject collapsed or unverifiable geometry before
mouse input. Preserve clearance when rounding slanted boundaries and preserve
ordinary rectangular behavior.

## Image drag and drop

Skip malformed URL candidates without losing later valid images. Decode HTML
attributes and image-search query parameters exactly once, preserving signed
URL escapes and valid trailing punctuation. Avoid building duplicate lists of
inline-image payloads. The existing image loader's 20 MB HTTP limit and
45-second download deadline remain in place.

## Mobile preview sessions

Generate a new URL token for each actual start and bind handlers to their exact
server session. Clear encoded images and invalidate pending encodes on stop.
Previously accepted connections cannot read a later session's images. Preparing
images before start and repeated start calls while already running remain
supported.

## Source archive privacy

Exclude source-run settings, calibration, histories, recovery data, saved picture
palettes and updater staging files from source archives. Keep the shipped palette,
resource scheduler, verified-color and golden-regression fixtures. Documented
examples in subdirectories remain included.

## Validation

Regression tests cover redirect chains using the real Requests machinery with
a recording transport, malformed metadata, download cleanup, drawing geometry,
preview session isolation, archive contents and stale build interpreters.

Local Python 3.12 validation: 1,720 test cases, no failures or errors, with eight
platform-dependent tests skipped. The Extra Fast benchmark, source-package
hygiene gate and 5,000-cycle release/lifecycle gate also passed.

The complete portable test suite also runs on Linux in CI. Its Paint calibration
test now replaces the native window monitor itself, so testing no longer tries
to construct a Windows API object on Linux.

The combined dependency audit on Python 3.12 checked 33 resolved packages across
application, test, build, OpenCL and optional CUDA manifests and found no known
vulnerabilities. These results cover the resolved package versions and
advisory data available on the audit date.

This patch updates the source. Existing published installers and portable ZIPs
keep their original bundled dependencies until a new release is built and published.

