# v1.0.148 batch16 — recovery uses the applied profile

This is an **uncounted completion of A1001** (existing global ID 766), not a
new improvement group. The deferred profile transaction and asynchronous PNG
publication already exist; this correction keeps their saved context coherent.
The relevant behavior is present in published batch15 baseline
`d1a5e3a709745ee64263b5801cf1b9089cd6b707`.

## Reproduced incomplete handoff

The profile menu changes its `game` variable before `change_profile` schedules
the actual `_apply_profile_change` operation with `after_idle`. Until that
callback runs, the accepted profile and its loaded settings are still the
previous profile. Recovery's state publisher read the menu value directly,
while reading the current settings and geometry from the application.

The regression reproduces this with real controller methods, temporary profile
JSON files, actual recovery snapshot publication and `load_snapshot`:

- Microsoft Paint is applied with High detail, contrast 1.25, brush 4 and its
  saved area. The user selects Other drawing app, whose pending idle callback
  has not loaded that profile's different settings yet.
- A previously scheduled recovery timer can now save a state naming Other
  drawing app while retaining Paint's options, geometry and exact source PNG.
- The same mismatch occurs when a real `RecoveryImageJob` has finished its
  private PNG and its `recovery_image_prepared` event is consumed before the
  profile callback.

Both affected cases verify the saved option values, saved area and decoded PNG
before asserting the incorrect profile. The unchanged implementation failed
these two assertions; a third positive case, consuming the PNG after the new
profile had really loaded, already passed. The initial gate ran three tests in
0.142 seconds with exactly these two failures.

## Correction

`_save_recovery_checkpoint` now uses `_active_profile_name` when present,
falling back to the existing menu value for compatible callers without an
applied-profile marker. This is the same applied-versus-selected distinction
already used by the P1404 diagnostics path.

The publisher continues capturing the latest settings at publication. It does
not capture an old profile when PNG encoding starts: after the idle callback
loads Other drawing app's saved settings, recovery stores that new profile
together with Quick sketch, contrast 0.75, brush 2 and its own area. The same
source PNG remains valid across the configuration-only profile change.

No encoder scheduling, source/job identity check, image ownership, persistence
format, safety state or profile-change behavior changes. No additional count
is assigned to this handoff correction.

## Regression coverage

`test_v148_application_batch16_recovery_profile.py` contains three actual-flow
tests:

1. A due timer publishes while a different profile's idle callback is pending;
   after applying that callback, the real post-profile timer publishes the new
   profile and its settings.
2. A completed real PNG job publishes before the profile callback; a later
   settings-only checkpoint uses the newly applied profile without re-encoding
   the image.
3. The completed PNG's event is delayed until after the profile callback; its
   publication uses the newly applied settings immediately.

All image results are decoded through the real recovery API and compared byte
for byte with the caller's source. Prepared-PNG cases reject any synchronous
fallback encoding and verify that private staging directories are removed.
The fixture uses the actual `change_profile`, `save_settings`, `read_settings`,
`_apply_profile_change`, timer, worker, event and persistence implementations;
only UI allocation and deterministic event scheduling are controlled.

Root integrated the targeted DrawBot patch. The new tests and the existing
A1001 preparation/lifecycle and subject-recovery suites passed together:
**27 tests in 0.246 seconds**, with no failures or skips.

```text
.venv/bin/python -m unittest -q test_v148_application_batch16_recovery_profile test_v148_application_batch10_recovery test_v148_application_batch10_recovery_lifecycle test_v148_application_batch05_subject_recovery
```

This includes compatible recovery callers without `_active_profile_name`,
cancelled and replaced sources, clear/shutdown behavior, failed publication,
subject-to-image identity and exact cached pixels. The correction's source and
the new tests are stable for independent review and the combined batch16 gate.
