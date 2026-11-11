# v1.0.148 — UI readability and layout completion

## Scope and counting

This patch continues from `61f8d5812cfeb85df7ae432e3b5d704028e37aa6` on
`improve/v1.0.148`. It applies the requested UI review to the existing desktop
interface: readable selected values, consistent disclosure text, visible focus,
and actions that fit their panel. The existing renderer, profile callbacks,
safety decisions, settings schema and application version remain authoritative.

**Zero new improvement IDs. The total remains 843/1,000; 157 remain.**
The focus correction completes UK01/global739. Layout corrections extend the
existing UC08/global721 action-row and UC11/global724 workspace contracts;
typography and theme polish are not counted separately. The machine registry is
byte-for-byte unchanged. This is a reviewable draft continuation, not a release.

## Problems reproduced and changes

| Area | Observed baseline | Patch |
| --- | --- | --- |
| Main window | The launcher set CTk `fg_color` to `#edf2f5`. Studio changed only Tk `bg`, so transparent header/workspace frames inherited the light surface; the pale app title was difficult to read. | Set CTk `fg_color` to the Studio background before constructing frames. Plain Tk retains the `bg` path. |
| Settings rows | Labels and descriptions shared a horizontal pack with the selector. In the measured 270 px row, Drawing preset received only 94 px; Preview detail received 82 px and its native label area was 31 px. | Stack label/help above the selector, giving it the full 270 px row in the same measurement. Its native text area is 219 px. Wrap title/help to their allocated logical width. |
| Disclosure hierarchy | Group headings used size 10 and captions size 9. | Use size 12 bold headings and size 11 descriptions, with consistent inset spacing and scale-aware wrapping. Setting titles/values use size 12 and descriptions size 11. |
| Primary keyboard focus | Mint focus outline on mint fill had 1.000:1 contrast, or 1.193:1 on hover. | Use the existing dark primary text color for the primary focus outline: 9.359:1 normally and 11.162:1 on hover. Secondary/danger outlines and caller overrides are retained. |
| Error actions | Logs/Diagnostics/Help requested 268 px in a 242 px row. Help shrank to 52 px instead of its requested 78 px. | Reuse the existing coalesced responsive action-row helper. Help retains 78 px and moves to a second row when necessary. |

The dimensions above were measured in the real Linux Tk application at a
1280×900 client size and 100% widget scaling. They are evidence for the layout
defect, not claimed Windows font measurements.

No controls, variables or commands are replaced. `_setting_row`, profile scopes,
the original help descriptions and numeric commit behavior remain intact.
The existing sidebar rollback test fixture gained binding bookkeeping so it
still reaches its intended shell-pack failure; no rollback assertion was weakened.

## Verification actually executed

Python 3.12.14 and CustomTkinter 6.0.0 were used on Linux. Native tests ran on the
desktop display, not as headless skips. The same two new test modules were copied
unchanged to a separate baseline checkout for the before/after comparison.

| Selection | Result |
| --- | --- |
| Five new native methods on the baseline | 2 passed, 3 failed; 0 errors/skips. The failures reproduce focus contrast, settings/background layout and clipped error actions. |
| Same five methods with the patch | **5 passed**, 0 failures/errors/skips. |
| Adjacent existing selection | **35 passed**, 0 failures/errors/skips. |

Native command:

```bash
python -m unittest -v \
  test_v148_ui_batch33_settings \
  test_v148_ui_batch33_workspace
```

Adjacent command:

```bash
python -m unittest -v \
  test_v148_ui_batch06_workspace.WorkspaceLayoutTests \
  test_v148_ui_batch06_workspace.ActionBarTests \
  test_v148_ui_batch06_scaling.ScalingReplayTests \
  test_v148_ui_layout_batch04.SidebarTests \
  test_ui_compact_layout_v10144 \
  test_profile_isolation_v107 \
  test_profile_switch_safety \
  test_v148_ui_batch06_preview.PresentationTests \
  test_v148_ui_batch06_preview.ResponsiveTests
```

The five native methods cover actual button canvas focus/hover/disabled states,
explicit focus-color overrides, full-width settings and description wrapping at
100/125/150/175/200% widget scaling, Simple/Advanced/Developer visibility, and
Paint/Gartic/Skribbl profile transitions with real temporary settings files.
They assert retained widget/variable identity, profile scopes, Manual preview,
disarmed drawing and error-action bounds at 100/200%.

Each native case runs in a separate process. Application data is redirected to
a temporary directory before application imports. External mouse/hotkey input
and unrelated startup hardware/welcome/recovery actions are isolated; the UI,
settings persistence, profile application and layout are real production code.
No synthetic test images or generated artwork are used.

Manual desktop inspection compared the baseline and patched app. The dark
header is readable, selecting Masterpiece through the real popup shows the full
value and executes the existing settings callback, and all three error actions
are visible in the 200% compact Readiness panel. Linux font fallback in this
desktop makes this a layout check, not Windows typography sign-off.

The first adjacent run found two legacy fixture failures because its Widget
double lacked `bind`; the fixture interface was completed and the exact 35-test
selection was rerun successfully. Earlier default-Python/dependency attempts and
headless native skips are not counted as passing native verification.

## Review and limits

Independent source review found no remaining blocker in the product changes or
focused tests. Source-package hygiene and `git diff --check` pass. Source hashes,
exact selections, counts and log hashes are recorded in
[the local validation record](v148-batch33-ui-validation.json).

Opening native dropdowns logs an existing AppBranding warning about
`DropdownMenu.iconphoto` on this Linux runtime. It was observed on both the
unchanged baseline and patched app; the popup and selection still worked.
The warning was retained and is outside this focused layout patch.

No native Windows visual/DPI review, packaged executable run, physical drawing,
GPU test or full local test discovery was performed for this patch. The seven
successful GitHub checks for parent `61f8d58` belong to that parent. GitHub
validation for the current UI commit is reported separately in PR #46.

### Windows CI fixture correction

The first UI commit, `9d3c6553f4b88cab907c140d2d2e158ba065eef7`, passed
[Linux CI](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42933226023/job/130236839567)
with 4,586 tests (4,508 passed, 78 skipped). Its
[Windows run](https://github.com/Vxiey/Image-Draw-Bot/actions/runs/42933226023/job/130236839525)
reported 4,586 tests: 4,580 passed, three failed and three GPU tests skipped.
All three failures were the new workspace fixture attempting to remove its
temporary directory while the child still owned an open crash-log descriptor.
Windows self-test, bundle and packaged-GUI steps were skipped after that failure.

`CrashDiagnostics.install()` intentionally retains the faulthandler stream for
the process lifetime. The fixture now gives the parent process ownership of the
temporary directory and lets the child borrow it. Strict cleanup occurs after
the child exits and Windows releases its descriptors. Production logging is
unchanged; cleanup errors are not ignored. All 44 existing assertion sites
remain, with three additional checks for the parent-owned directory, real crash
log creation and completed directory removal.

The corrected tests were copied unchanged to the baseline again and the native
before/after comparison was rerun. It retains the same results: three of five
methods fail on the baseline and all five pass with the UI patch. The local
record retains both executions and the initial CI failure; the final Windows
result is reported against the current commit in PR #46.

## Design references applied

- [Figma UI design principles](https://www.figma.com/resource-library/ui-design-principles/): hierarchy, consistent controls, readable contrast and proximity.
- [Erik Kennedy, 7 Rules for Creating Gorgeous UI, Part 1](https://medium.com/@erikdkennedy/7-rules-for-creating-gorgeous-ui-part-1-559d4e805cda): a neutral structure, restrained accent color and deliberate spacing.
- [Frontend discussion supplied by the user](https://www.reddit.com/r/Frontend/comments/s8mj1a/how_do_i_make_beautiful_uis/): supporting context for typography and familiar patterns.

These inform the presentation changes; the regression evidence comes from the
actual application code and executions above.
