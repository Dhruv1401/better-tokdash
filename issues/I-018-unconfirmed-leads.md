# [leads] Unconfirmed hypotheses — NOT for filing

> **Status: DO NOT FILE.** These did not reach confirmed-bug standard: either no live
> divergence was demonstrated, or the input required is contrived for the affected
> client. Preserved per the audit standard of separating findings from ideas, with a
> concrete next experiment for each. If you (the maintainer) want any of these chased
> to a demonstration, contact me.

## L-1. Claude cross-file supersede resolves ties by parse order; the store resolves them by last-sync order

`claude_usage_supersedes` lets a later-parsed entry supersede an earlier one when totals are equal but the bucket split differs. Live, parse order is sorted-path order; in the store, the `(source, entry_key)` unique index with `INSERT OR REPLACE` makes it last-synced order. If the same Claude `msg_id` appeared in two files with different splits (plausible only via backup/export mid-stream), the two backends could keep *different* rows. No realistic Claude corpus was available to demonstrate.

**Next experiment:** synthesize two Claude session files sharing a `msg_id` with different in/cache splits; compare live vs stored rows ([`src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py), ClaudeParser + [`src/tokdash/usage_store.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/usage_store.py)). If they diverge, decide the canonical rule (earliest timestamp, as Cline/Qwen do) and file with the reproducer.

## L-2. `model_normalization` prefix asymmetry: `opus`/`sonnet` get the `claude-` prefix, `haiku` does not

If any client reports a bare `haiku-4-5`, it forms a separate combined-view key from `claude-haiku-4-5` (two rows in the per-model table). Unverified against real logs — no supported client is known to emit the bare form today.

**Next experiment:** grep the parsers for bare-haiku emission paths; if none exists, this is at most a symmetry nit in [`src/tokdash/model_normalization.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/model_normalization.py); if one exists, file with the parser named.

## L-3. Semantics warts (consistency observations, individually too small to file)

- `_contributions_from_entries` (heatmap) counts messages per entry while `parse_entries_json` honors `messageCount` — the heatmap's per-day message counts and Overview's can disagree ([`src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py)).
- `messageCount=0` normalizes to 1 in `parse_entries_json` — a client emitting zero-message rows gets counted as one message.
- Float token counts truncate via `int()` (0.9 → 0) — no client is known to emit fractional tokens.

**Next experiment:** none scheduled; batch into one "entry semantics" issue only if a real corpus demonstrates divergence.

## L-4. `msvcrt` lock degrades to a no-op after 30 s; `BEGIN IMMEDIATE` becomes the only cross-process guard

The documented degrade ([`src/tokdash/filelock.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/filelock.py)) means a waiter proceeds unlocked if a sync exceeds 30 s. SQLite's `BEGIN IMMEDIATE` should still serialize the writes, but parse-before-lock work is duplicated under long-sync contention, and the behavior is untested on Windows.

**Next experiment:** two-process stress test with an artificially slowed parser (>30 s) verifying no corruption and measuring duplicated work. Only worth filing if corruption appears.

---

*From the adversarial audit of v2.6.8 (`0a179d0`). Deliberately kept out of the main issue set; see the audit's signal-density standard. Contact me if you want any of these driven to a confirmed/ réfuted state.*
