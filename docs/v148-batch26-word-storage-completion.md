# Batch 26 — word dictionary round-trip completion (zero new IDs)

## Existing contract and observed gap

This completes UI20 / global 241, the existing bounded word-list contract. It
does not add a new numbered improvement. The actual `DrawBotApp.import_words`
callback uses `WordGuesser.load_words`, whose startup reader accepts at most
2,000,000 UTF-8 bytes. The callback previously checked only the incoming file,
then published normalized words with a final newline without checking the
serialized result.

Two real imports demonstrated the gap against the unchanged incoming import
flow from `5b0c22ac5dc620a911fa2a1f6216e272f644f7db`:

| Input | Accepted source | Published file before correction | Actual startup reader |
| --- | ---: | ---: | --- |
| 25,000 distinct ASCII phrases, no final newline | 2,000,000 B | 2,000,001 B | Rejected as too large |
| 12,000 distinct phrases containing `Ⱥ`, casefolded to `ⱥ` | 1,859,999 B | 2,760,000 B | Rejected as too large |

Both imports replaced the previous valid dictionary, adopted the new words in
memory, and invoked the result refresh. The saved dictionary would therefore
be ignored by the existing startup fallback. These observations use actual
UTF-8 normalization, actual atomic publication, and the actual startup reader;
they do not simulate an oversized `load_words` return value.

## Resulting behavior

The callback serializes the existing canonical format once and checks its
UTF-8 byte length against the same `MAX_WORD_LIST_BYTES` constant before
publication. An oversized normalized result displays “The normalized word
list can be at most 2 MB.” and preserves the old file, active tuple, source
label and visible result contents. No truncation or partial dictionary is
published. A serialized result of exactly 2,000,000 bytes remains accepted.

Ordinary imports retain the prior sort, deduplication, comments, Unicode
normalization, final newline and atomic replacement behavior. The saved file
is still published before the in-memory dictionary is adopted. The actual
atomic replacement failure path preserves the previous dictionary and removes
its temporary file.

## Verification

`test_v148_ui_batch26_word_storage.py` contains four public-flow tests: the
final-newline boundary, Unicode expansion, an exactly accepted saved boundary
with a reader/filter round trip, and canonical Unicode import followed by a
real atomic-writer replacement error. Before correction, two tests failed on
the changed destination bytes and two positive controls passed (four tests,
0.888 s, no test errors). An independent observation probe also recorded the
two published sizes and both startup-reader rejections above.

After correction, the four tests and the existing guesser/drop, complete word
result browsing and profile/Unicode selections completed **37 tests in
0.732 s: 36 passed and one Windows-only native case skipped**. The batch's
final whole-source and platform gates are recorded separately. This is a
persistence-correctness completion; no speed or allocation improvement is
claimed.
