# [tests] Add a standing DB-on vs DB-off parity property test — it mechanically guards the exact seam where the tail-strand and split-file undercount bugs live

## Summary

The architecture's core promise — "source logs remain the source of truth; the DB is a local performance index" — is currently enforced by hand-written per-parser tests. The audit found two real violations of it ([I-001](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-001-tail-append-strands-last-line.md) tail-strand undercount; [I-008](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-008-reasonix-split-file-undercount.md) split-file halving) and, to map where the property *holds*, built the missing artifact: a randomized differential test comparing the store path against the live path over generated corpora.

Result on Codex (stable content keys): **30/30 randomized corpora in exact parity** — row multisets and aggregates identical — run twice across audit passes. That negative result is valuable in itself: it shows the content-keyed design is sound, and that the violations concentrate in the per-file-key sources (the `append_jsonl=True` parsers and Reasonix's per-parse-call occurrence counter), exactly where I-001 and I-008 live. Filing as a testing-infrastructure proposal so the property becomes a standing test rather than an audit one-off.

## Reproduction (the harness)

Full script: [`output/exp20_parity_property.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp20_parity_property.py) (~60 s; contact me if you want it). Core structure, ~30 lines:

```python
def run_mode(db_on: bool, seed: int):
    # isolated home + TOKDASH_DATA_DIR; corpus built from a seeded RNG:
    #   1-4 rollout files, 1-12 token_count events each, random model switches,
    #   duplicate timestamps, plus a resume-copy of one file into archived_sessions/
    build_corpus(home, random.Random(seed))
    tracker = CodingToolsUsageTracker()
    if db_on:
        store, stored_sources = _sync_usage_store(tracker)
        entries = store.query_entries(sources=stored_sources)
    else:
        tracker.collect(None, None)
        entries = tracker.entries
    return entries, parse_entries_json({"entries": entries})

# for each seed: fingerprint(live) must equal fingerprint(store) as multisets of
# (entry_key, model, input, output, cacheRead, cacheWrite, timestamp),
# and the parse_entries_json aggregates must match.
```

Observed: `result: 30/30 corpora in parity, 0 breaks` (Codex), reproduced twice.

## Expected behavior

If the property is adopted: for every supported source, a randomized corpus must produce identical row multisets and identical aggregates under DB-on and DB-off. Where it currently fails, the failure is exactly the confirmed bugs — so the test should initially xfail those sources with a reference to their issues, then flip to hard assertions as each is fixed.

## Actual behavior

No such standing test exists; parity is enforced per-parser by fixed fixtures, which cannot catch layout-dependent divergences (split files, unterminated tails, duplicate copies) because those layouts differ from the fixtures.
- The `hypothesis` library used for the audit prototype is **not** currently a project dependency (verified: absent from `pyproject.toml` and unused in `tests/`); landing this would add one dev dependency, or the generator can be ported to plain seeded `random` to stay dependency-free.

## Impact

Not a user-facing bug — infrastructure. The three accounting bugs found in this audit ([I-001](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-001-tail-append-strands-last-line.md), [I-007](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-007-dsh-duplicate-file-divergence.md)'s cross-surface analogue, [I-008](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-008-reasonix-split-file-undercount.md)) are all violations of this single property on some source; one parametrized property test over all sources subsumes the per-parser parity tests and would catch new violations at PR time, including in parsers that don't exist yet.

## Root cause

n/a (proposal).

## Evidence

- [`output/exp20_parity_property.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp20_parity_property.py) — 30/30 parity on Codex, deterministic (seeded), two runs.
- Violations the property would have caught: [I-001](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-001-tail-append-strands-last-line.md) (14 vs 15 rows, same file), [I-008](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-008-reasonix-split-file-undercount.md) (16,238 vs 8,119 input tokens, same corpus).

## Suggested direction

Port the generator into `tests/` as a hypothesis-driven property, per source, with the perturbations that found real bugs: appends *without* trailing newlines (finds I-001 on the five `append_jsonl=True` parsers), corpus splits across files (finds I-008 on Reasonix), duplicate session ids across roots with divergent content (finds the I-007 analogue on DSH), and byte-identical duplicate rows (occurrence counters). Start with Codex green; xfail the sources with known violations so the gap is visible rather than silent.
