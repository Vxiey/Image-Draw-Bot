# Batch41 integration provenance

The local batch40 checkpoint `fc3f927966d79c3f5d8cd04ea071c0670faa6ad0`
and its published Git commit object `1de270273975eced1996e39e85790822cf408afe`
have the identical Git tree `5b3df8ccbad22002ce57fdd6ab2c17600a720aab`.
The authenticated repository API authored the latter commit; metadata differs,
but every source, test and evidence blob in the baseline is byte-identical.
Its parent is the prior published `888116094b91758dded968a7e3b5559683db9ad7`.

Historical batch41 measurements and negative proofs name the local checkpoint
and retain their original hashes and raw observations. The standalone
`benchmark_v148_rendering_batch41.py` now names the equivalent public commit so
it is reproducible from a fresh repository clone. This one baseline-reference
change occurred after the focused measurements and before complete integrated
discovery. No algorithm, test assertion or measured value changed with it.

The earlier batch40 full runner aborted in Tcl and never produced a completed
gate. Its diagnostic and the separate initial missing-main-guard attempt remain
available. Two older test fixtures now release captured interpreter owners on
the creator thread; the repair is independently proved and adds no product ID.

At this integration checkpoint the register has 869 of the revised 900 distinct
improvements. No release or merge is implied by creation of the commit objects.
