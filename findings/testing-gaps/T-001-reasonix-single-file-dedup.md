# T-001 (testing gap / live-path undercount): Reasonix occurrence counter is file-scoped, so DB-off parsing collapses byte-identical rows

## Classification
Testing gap with a real (low-severity) correctness consequence on the DB-off path.

## Summary
`ReasonixParser._parse_all` keys rows on a content digest plus an *occurrence
counter*. But `seen_digests` is initialized once per `_parse_all()` call while
the persistent-store path (`sync_files` → injected single-file scope →
`_parse_all`) calls `_parse_all()` **once per file**. The occurrence counter
therefore restarts at 0 for every file.

Consequences:
- **DB-off live path (all files, one call):** two byte-identical rows *in the
  same file* get distinct keys (`digest`, `digest:1`) — correct. But two
  byte-identical rows in *different files* (e.g. a day file duplicated across
  two `REASONIX_HOME` roots, or a copied/merged stats dir) ALSO get distinct
  keys — double-counted live, while the store (per-file scope) also
  double-counts. Consistent.
- **Store path:** byte-identical rows in the *same* file get distinct keys
  (correct), but the *same file parsed twice through different scopes* … still
  consistent because file_replace deletes rows per path before insert.
- The genuine divergence: the docstring promises occurrence keys are "stable
  under appends" — they are, but they are **not stable under reordering or
  splitting**, and the DB-off path applies them across the whole corpus while
  the store path applies them per file. A day file split into two files
  (rotation) changes DB-off keys but not store keys.

## Evidence
Experiment (output/exp02): two byte-identical Reasonix rows in one file.
- Live: 2 entries, keys `reasonix:c0eb41…`, `reasonix:c0eb41…` (distinct via
  `:1` suffix) → in=16238. Correct (two real requests).
- Store: 2 rows, in=16238. Correct here because both rows come from one file.

The gap: no test covers the *split-file* metamorphic case (same dataset split
across two day files), where DB-off and store identity rules diverge. A
byte-identical row in two files counts twice in both paths, but with different
keys — meaning `tokdash db verify` and the live path cannot agree on *which*
logical row is duplicated, and a future fix to one path cannot be regression-
detected by the other.

## Suggested direction
Decide and document the intended scope of the occurrence counter (per-file vs
per-source), and add a metamorphic test: "splitting a day file into two files
must not change totals" (currently true for the store, untested for the live
path; keys differ between paths either way).
