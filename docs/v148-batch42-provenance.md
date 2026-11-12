# Batch42 integration provenance

The frozen local batch41 commit `b75ef8e` and public Git commit object
`e33fa67d17e3c33ccda8e736e7e16c2582d9fc06` have the identical tree
`72e55f2a6d3dad971a13e9ab9141aa521cf15177`. The public object is the parent
used for the reproducible batch42 historical comparisons. Its parent is
`1de270273975eced1996e39e85790822cf408afe`, whose tree is identical to the local
batch40 checkpoint; the preceding integration record retains that mapping.

Batch42 records 17 distinct implemented groups, bringing the registry to
886 of 900. All preceding 869 entries are unchanged. Each area ledger identifies
its own source hashes, earlier-contract boundaries, initial diagnostics,
focused and adjacent results, and measured regressions or limitations.

The complete batch41 discovery ran in the frozen NEXT worktree. Its failed
result is retained as `v148-batch41-initial-full-validation.json`; its six
timeout-method follow-ups ran on that same unchanged source. Batch42 changes
were made in a separate FINAL worktree and did not participate in either run.
The later implementation work toward batch43 is excluded from this checkpoint.

Native facade and CPU simulation evidence is not a physical Windows, Paint,
CUDA or OpenCL device pass. Complete final discovery, source/package gates and
CI for the eventual published branch head remain separate validation steps.
Creating intermediate Git commit objects does not merge the draft PR, publish
a release or change its branch ref.
