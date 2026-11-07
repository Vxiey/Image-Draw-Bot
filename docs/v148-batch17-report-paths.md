# Batch 17 — derive safety-report destinations from the selected local pair

Baseline: `e87bcf1b783b33ff866c2188e10c8b5d22a22707`.
This area implements **one verified behavior group, P1701**. Embedded path types, stale
destinations and external-file destinations are one report-opening authority
correction, not separate IDs.

## Reproduced behavior

`RuntimeSafetyReport.latest_report` validates bounded JSON evidence and derives
`json_path` from the file it actually loaded. When the adjacent `.txt` file
exists, it also derives `text_path` from that sibling. When the sibling was
missing, however, it retained a `text_path` already embedded in the JSON.

The actual `DrawBotApp.open_latest_safety_report` controller prefers
`text_path`. A valid report containing an unrelated existing path could
therefore direct the platform's file-opening call away from the selected
report. The real save implementation does not write either destination into
its JSON; they are return-value metadata, not stored report authority.

Before the correction, the new regression file ran four test methods. Three
subcases passed unrelated existing `.exe`, `.lnk` and `.txt` marker files to the
actual controller's `os.startfile` boundary. Four other subcases used truthy
boolean, numeric, list and dictionary path fields; each raised `TypeError`
instead of opening the valid JSON report. The genuine adjacent text and actual
saved-session controls already passed. All files were temporary harmless
markers, and the platform opening function was mocked; nothing was launched.

## Correction

Discard any stored `text_path` before adding the paths derived from the loaded
report and its actual adjacent text file. A missing/non-file text sibling falls
back to the selected JSON. A genuine text sibling remains preferred. The
bounded reader, report selection order, evidence validation, save format,
summary counters and file contents are unchanged.

This is separate from **DP48 / global 379**, which bounds JSON reads and
validates stored report evidence, and **DP49 / global 380**, which preserves
execution evidence when saving fails. The concurrently developed A1701 selects
the current execution's in-memory evidence; this change constrains destinations
when historical evidence is read from disk. These complementary paths must
continue to agree at the real Open action.

## Evidence and limits

`test_v148_platform_batch17_report_paths.py` exercises the real disk loader and
Open controller with only the final platform opening boundary replaced. It
also proves that the JSON bytes remain unchanged, ordinary saved report pairs
still round-trip, and a directory in place of the text sibling does not prevent
the JSON fallback.

The new and adjacent safety report tests passed **21 cases in 0.037 seconds**,
with no skips. Independent source and count/deduplication review closed without
blockers. After the current-run UI integration, the four path cases and its
15 initial controller cases passed together (**19 tests, 0.375 s**). The final
runtime/retry integration scope passed **100 tests, 1.003 s**, and an independent
cross-area run passed all **43 batch-17 behavioral tests, 2.741 s**, with no
skips. The final frozen-source whole-program gate is recorded in the batch
validation artifact. No native executable launch, broader filesystem isolation
or timing improvement is claimed.
