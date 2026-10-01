# T-003 (testing gap / design weakness): `_sig_cache` is unbounded and there is no rename-portability metamorphic test for content-keyed parsers

## Two related observations

### 1. `_sig_cache` grows without bound (measured)
`coding_tools._timed_sigs` inserts `(cache_key → (timestamp, result))` and
never evicts: only the TTL check exists, and an expired entry is
*overwritten*, not removed. The key is the client home path(s) —
`"kimi:<dir>"`, `"codex:<dir>:<dir>"`, `"claude:<dir>"`, `"crush:…"`,
`"gemini:<root>"` — so a long-lived server process accumulates one entry
per *distinct data dir ever seen*. Measured: 2,000 distinct keys → 2,000
retained entries (exp14). In normal single-user operation the key set is
tiny (one entry per client), so this is a design weakness rather than a
live leak — but every comma-separated multi-root override
(`WORKBUDDY_DATA_DIR`, `DEVIN_CLI_DATA_DIRS`, `REASONIX_HOME`, …) builds a
joined key per root *list*, so reconfiguring roots between runs (tests,
multi-machine setups, `tokdash` invoked with different env from several
shells against one daemon-less CLI) adds entries unboundedly. Same pattern
as the caches the project *did* bound (`_OPENCODE_QUERY_CACHE_MAX = 32`,
`TOKDASH_CACHE_MAX_ENTRIES`), which suggests bounding was intended policy.

### 2. Content-keyed dedup is only stable while paths are stable — untested
Kimi Code's `usage.record` rows (no message id) dedup on
`sha1(path_str, ts_ms, model, usage)` — the parser's own docstring: "The
path keeps identical rows from distinct sessions/agents countable". That
is a deliberate *accounting* choice (two identical rows in different
files = two billable events), but it makes dedup identity **path-bound**:
- A user renaming/moving a Kimi session directory (or moving it between
  machines with different mount prefixes) turns the same rows into fresh
  keys. The parser treats them as new usage on every repath.
- In the persistent store the old rows remain (file_replace deletes by
  the *old* path when the path disappears, so this self-heals there);
  on the DB-off path there is no store at all — each `_parse_all` is
  self-consistent — so the exposure is the interaction: a *renamed* file
  syncs as a new path while the store still holds the old path's rows
  unless durable-mode deletion ran, i.e. with
  `TOKDASH_USAGE_DB_DURABLE=1` (default) a renamed/moved Kimi session
  double-counts until the original path's rows are reaped by a resync.

No test exercises: (a) rename/move of a session file for any
path-in-keyed parser, (b) `_sig_cache` eviction/bound, (c) durable-mode +
rename interaction.

## Evidence
- exp14 probe: 2000 distinct scan keys → 2000 retained `_sig_cache`
  entries with `TOKDASH_SIG_TTL=0`.
- `coding_tools.py` `_timed_sigs` (no eviction), Kimi `_entry_from_usage_record`
  (path in the hash), `SourceSyncCapability` docs vs Kimi's
  `append_jsonl=True` capability (tail parse reproduces the *same* path
  keys — consistent — but a rename breaks the identity chain).
- Contrast: Codex/Pi/Cline/Qwen explicitly key on *content* (session id +
  usage state / uuid), and Qwen documents "promotes a surviving copy when
  the canonical file is deleted" — Kimi's content-hash branch is the one
  place a path is load-bearing in identity.

## Suggested direction
- Bound `_sig_cache` (OrderedDict LRU with a small cap — mirrors
  `_OPENCODE_QUERY_CACHE_MAX`); evict expired entries on insert.
- Decide and document the rename contract: either drop `path_str` from
  the Kimi dedup hash (accept cross-session same-content collapse — the
  `:N` occurrence-counter pattern Reasonix uses solves the counting half)
  or add a rename-repro test pinning current behavior for durable and
  strict modes.
