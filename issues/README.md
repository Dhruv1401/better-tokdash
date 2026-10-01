# Issue-ready drafts — final review state

One draft per finding, each written to be self-contained: a maintainer should be able to
reproduce it from the issue text alone (every draft embeds a verified, runnable
reproducer inline). File references appear as relative links so they resolve on GitHub;
full experiment scripts live in this branch under `output/` — **contact me** (or open a
discussion on this fork) if you want any of those files and the link doesn't resolve.

All drafts were re-verified in a final hostile-maintainer pass: every inline reproducer
was executed as written against `0a179d0`, every number below was re-measured or
re-derived, and upstream issue/PR status was re-checked on 2026-09-30.

## Classification

### READY_TO_FILE (10)

| Draft | One-line claim | Minimal reproducer in the issue? | Notes |
|---|---|---|---|
| [I-001](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-001-tail-append-strands-last-line.md) | Store defers an unterminated final line indefinitely while the file stays at that size → DB-backed totals undercount (14/1260 vs 15/1350 measured); self-heals if the session grows again | ✅ inline, run verbatim (deterministic: `TOKDASH_SIG_TTL=0`, binary writes) | Five affected sources (`append_jsonl=True`: Gemini CLI, Kimi, WorkBuddy, Qwen Code, MiniMax Code); realism of the trigger on live clients flagged as unproven |
| [I-002](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-002-config-write-race.md) | Unserialized `config.json` RMW + shared `.tmp` → `PermissionError` 62/80 in-process, 30+30/60 cross-process | ✅ inline, run verbatim | Crash demonstrated; POSIX lost-update labeled as inferred-from-code, not observed |
| [I-003](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-003-huge-int-poisons-store.md) | One >2^63 token row fails every sync for its source; API silently serves live data at parse-class latency (5–12 s/request measured) | ✅ inline + exp24 for latency | CLI raise ×3 verified; DSH path extension verified; latency split measured (200k events) |
| [I-004](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-004-dst-anchored-date-windows.md) | Custom date windows anchor to the *current* DST offset → wrong UTC window for opposite-phase dates (Jan 5 → Jan 4 18:30Z–Jan 5 18:30Z) | ✅ inline, run verbatim | Helper-level simulation; end-to-end corpus demo not captured (reporter's zone has no DST) — stated in the issue |
| [I-005](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-005-unbounded-period-500.md) | Numeric `period` unbounded → 500s leaking raw exception text; `/api/stats` 200s on same input | ✅ inline, run verbatim (exact statuses/bodies) | Low severity, honestly framed; `/api/sessions` requires `tool` param (noted) |
| [I-006](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-006-dsh-corrupt-file-silent-drop.md) | DSH: corrupt/unsupported file dropped whole; stored rows deleted (1→0) while unreadable; zero diagnostics (4→3 version-bump case) | ✅ inline, run verbatim | All 8 scrutiny points re-verified; "permanent" wording corrected to lasts-while-corrupt; design-doc counter citation |
| [I-007](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-007-dsh-duplicate-file-divergence.md) | DSH: duplicate copies win differently on Overview (999/99) vs Sessions (100/10); non-adjacent `(turn,step)` repeats diverge (411 vs 511) | ✅ inline, run verbatim | S6 numbers corrected in final pass (isolated process required); docstring contradiction cited |
| [I-008](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-008-reasonix-split-file-undercount.md) | Reasonix: split-file corpus halves DB-backed totals (16,238 → 8,119) | ✅ inline, run verbatim | Occurrence-counter scope vs per-file store parse; one-file control passes (why tests miss it) |
| [I-009](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-009-timezone-fragile-fixture-tests.md) | Pi fork-replay tests fail east of UTC+2:27; only end-to-end guard for the #124/#126 fix | ✅ commands + mechanism fixture | Boundary is derived arithmetic; failure demonstrated at IST only; Windows TZ caveat included; PR #137 linked |
| [I-015](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-015-store-failure-observability.md) | Store-sync failures never reach `source_errors` (corrupt DB and poisoned store both verified invisible) | ✅ inline, run verbatim | Two independent failure modes shown; pairs with I-003 |

### HARDENING / NON-BUG (4) — real, but explicitly not defects

| Draft | Claim | Upstream status |
|---|---|---|
| [I-010](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-010-quota-refresh-get-side-effects.md) | `GET /api/quota/refresh` does credentialed calls + DB writes outside the write gate, in tension with documented read-only posture | Route exemption is **documented as intentional** (REMOTE_ACCESS.md) — file as a discussion/design question, not a bug |
| [I-011](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-011-cdn-scripts-without-sri-or-csp.md) | CDN deps without SRI/CSP — the supply-chain gap beside #135 (availability) and #136 (failure toasts) | **Overlaps upstream**: cite #135/#136 and file only as a complement; do not file standalone |
| [I-012](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-012-p001-cold-assembly-scale.md) | Cold Sessions assembly ~10–13 ms/session (38–68 s @ 5k, three runs); no progress state, no scale budget | Measured, linear; file as performance observation if desired |
| [I-017](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-017-extend-xss-sink-tripwire.md) | Widen XSS sink tripwire from named sinks to every `innerHTML` interpolation (46 sites audited, all clean) | Hardening proposal; audit found zero XSS |

### DO_NOT_FILE (1)

| Draft | Why |
|---|---|
| [I-018](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-018-unconfirmed-leads.md) | Unconfirmed leads (Claude tie-break order, haiku prefix, semantics warts, msvcrt degrade) — preserved with next experiments; explicitly not filing material |

### Testing-infrastructure proposal (1) — file only if wanted

| Draft | Claim |
|---|---|
| [I-013](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-013-parity-property-testing.md) | Standing DB-on/DB-off parity property; 30/30 Codex corpora in parity (negative result) — would have mechanically caught I-001/I-008. Includes runnable harness sketch |

### Consistency nit (1) — documented behavior, file only if the team wants it closed

| Draft | Claim |
|---|---|
| [I-016](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-016-openclaw-until-boundary-inconsistency.md) | Row at exact `until` counts in Overview (1500/1 msg) not Sessions (`[]`) on identical bounds — documented in SUPPORTED_CLIENTS.md; one-operator fix | 

### Design notes (1) — no live failure

| Draft | Claim |
|---|---|
| [I-014](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-014-sig-cache-unbounded-kimi-rename-contract.md) | `_sig_cache` unbounded (2,000/2,000 retention) + Kimi path-bound hash contract undocumented/unpinned |

## Dedup check (final)

No two drafts file the same bug. I-006/I-007 both concern the DSH decoder but are
independent impacts (corruption/loss vs duplicate-winner divergence) with separate
reproducers; keep separate. I-003 and I-015 are cause and observability-gap
respectively — I-015 links to I-003 and stands alone. I-011 explicitly positions as a
complement to upstream #135/#136, not a duplicate (they cover availability/UX; it covers
integrity/policy).

## Recommended filing order

1. **I-001, I-002, I-003, I-008** — confirmed accounting/reliability bugs, verified reproducers, highest impact.
2. **I-006, I-007** — the DSH pair (new source, no upstream reports).
3. **I-004, I-005** — correctness/consistency with verbatim reproducers.
4. **I-009** — tests (kind framing: it helps them retire the PR #137 caveat).
5. **I-015** — observability (pairs naturally with whichever of I-003 lands).
6. Optional, maintainer's call: I-013, I-016, I-014, I-012.
7. I-010 / I-011 / I-017 — as discussions or complements to existing threads, not standalone bug reports.

## Provenance

Third-pass adversarial audit of Tokdash v2.6.8 (`main` @ `0a179d0`), Windows 11,
Python 3.12, IST. Every inline reproducer in every draft was executed as written
during the final review; experiment scripts under `output/` are retained in this
branch as supporting evidence.
