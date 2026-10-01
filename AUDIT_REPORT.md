# Tokdash — Adversarial Engineering & Reliability Audit

> **FINAL REVIEW PASS (publication gate, after the third pass).** Every issue draft in
> [`issues/`](issues/README.md) was re-reviewed as a hostile maintainer: every inline
> reproducer executed as written (four drafts had broken reproducers or wrong numbers —
> fixed: I-001 Kimi→Gemini fixture, I-002 API names, I-003 latency precision via new
> exp24, I-016 same-window proof, I-007 S6 isolated-process numbers). Every claim was
> re-graded (demonstrated / inferred / proposed), "permanent" wording corrected to
> lasts-while-corrupt (I-006), and upstream status re-checked — I-011 now explicitly
> complements upstream #135/#136 rather than duplicating them, and I-009 cites PR #137
> and #124/#126. Final classifications live in [issues/README.md](issues/README.md):
> 10 READY_TO_FILE, 4 hardening/non-bug, 1 do-not-file (leads), plus
> testing-infra/consistency/design-note items. All cross-links resolve on the
> `audit` branch of Dhruv1401/better-tokdash.

**Target:** https://github.com/JingbiaoMei/Tokdash — `main` @ `0a179d0` ("Release v2.6.8"), audited 2026-09-30.
**Method:** read the core accounting pipeline in full (compute, usage_store, pricing, insights, dateutil, filelock, model_normalization, the Codex/Claude/Crush/Reasonix/Gemini/Kimi/DSH parsers, pi_forks, api security surfaces), then attacked it with adversarial fixtures, property/metamorphic tests, numeric+string fuzzing, time manipulation, race/fault injection, live API probes, a 12-mutation campaign against the test suite, performance scaling measurements, browser-based frontend probing, and raw-ASGI security probes. All experiments are reproducible one-command scripts under `output/`; all raw evidence is under `findings/`; all issue drafts are under `issues/`. Upstream code was never modified (mutations ran on a scratch copy).

**Baseline:** `python -m pytest tests` → **4 failed, 3054 passed, 9 skipped** on Windows 11/IST. The 4 failures are pre-existing on main (the maintainer says the same in PR #137): companion-packaging ×2 (environment) and Pi-fork-replay ×2 (timezone-fragile fixture — see T-002).

---

## A. Executive findings

| # | Finding | Confidence | Impact | Reproducibility | Subsystem |
|---|---------|-----------|--------|-----------------|-----------|
| F-004 | **Store defers an unterminated final line indefinitely** — persistent store undercounts the same file the live parse counts correctly (14/1260 vs 15/1350 demonstrated). Affects the five `append_jsonl=True` sources: Gemini CLI, Kimi, WorkBuddy, Qwen Code, MiniMax Code. | High (mechanism corrected and re-verified in final review) | Silent undercount on the default DB-on path, lasting while the file never gains another newline after the deferred line; store and live path disagree | Issue draft embeds a verified deterministic reproducer (`issues/I-001-tail-append-strands-last-line.md`) | `compute._complete_jsonl_tail` + `usage_store.sync_files` tail branch |
| F-003 | **`config.json` writes are unserialized read-modify-write with a shared `.tmp` filename** — concurrent writers crash with unhandled `PermissionError` on Windows (78.8% of writes under 4-thread contention; 53% cross-process) and silently lose updates anywhere. This is the *consent store* for provider network access. | High (measured, cross-process) | Crashed writes / silently reverted consent on the security-relevant config; Windows is a supported platform | One command (`output/exp10b_crash_rate.py`, `_f3_child.py`) | `sources/quota/config.py::_write_config` (+ `onboard/updatecheck.py`) |
| F-001 | **A single >2^63 token count poisons the persistent usage store** — every sync raises `OverflowError`; compute's bare `except` silently degrades every request to a full live reparse forever, with `source_errors=[]` and zero rows stored. No signal anywhere. | High (verified across 3 consecutive requests) | The documented performance index silently becomes a per-request tax; `tokdash db sync` hard-fails; diagnostics empty | One command (`output/exp04_overflow_store.py`; re-verified `output/` second-pass) | `sources/coding_tools.py::BaseParser._i` → `usage_store` executemany → `compute` fail-open |
| F-002 | **Date-range windows are anchored to the *current* fixed DST offset** — windows for dates in the other DST phase drift 1 hour (plus the "not-midnight" wall-clock skew), and disagree with the heatmap's true-localtime day bucketing | High (mechanism proven; needs a DST-zone machine for live end-to-end) | Hour of usage misattributed in every custom-range query/report on DST-observing machines for ~4 months/year; dashboard surfaces disagree | `output/exp07b_dst_e2e.py` (simulated NY September `now()` through the real code path) | `dateutil.parse_date_range`, `compute._date_range_from_args`, API custom-range endpoints |
| F-005 | **Unbounded numeric `period` values cause 500s with raw exception text** (`date value out of range`, and `Python int too large to convert to C int` for a 400-digit value) on `/api/usage`, `/api/tools`, `/api/insights`, `/api/sessions`; `/api/stats` returns 200 for the same input | High (live TestClient) | Unauthenticated 500s + internal-detail leakage; non-uniform semantics across the multi-server fan-out | `output/exp12_live_server.py` + follow-up probe | `compute.period_to_days/period_to_range_args`, `api.py` |

**Also delivered (third pass):** three new confirmed findings — DSH corrupt-file silent drop **with deletion of already-stored rows** (exp18 S9: 1→0 rows, no diagnostic), DSH Overview/Sessions divergence on duplicate files and non-adjacent `(turn,step)` duplicates, and the Reasonix split-file 50% undercount (T-001 upgraded from gap to bug) — plus the CDN-without-SRI/CSP hardening note from the live browser test, the parity-property harness (30/30 negative result on Codex), clean bills on all traversal probes and the pricing DB, and issue-ready drafts for everything in `issues/`.

**What I deliberately did not report:** the dependency/CI scan came back clean (actions SHA-pinned with version comments, scoped `permissions:`, `persist-credentials: false`, `textual` pinned `<9` with a written rationale); the frontend XSS sink audit came back clean (all 46 `innerHTML` sites route through `escapeHtml`/trusted translations, and the repo already pins specific sinks with regression tests — S-002 extends that tripwire rather than inventing a vuln); no issue was fabricated where the mechanism couldn't be demonstrated.

---

## B. Confirmed bugs

### F-004 — Store defers an unterminated final line indefinitely (mechanism corrected in final review)

**Given** a `session-*.jsonl` for any `append_jsonl=True` source (Gemini CLI, Kimi, WorkBuddy, Qwen Code, MiniMax Code) whose final line has no trailing `\n` at sync time, **when** the persistent store syncs (deterministic reproducer: binary writes, `TOKDASH_SIG_TTL=0`):

1. The tail reader (`_complete_jsonl_tail`) correctly emits nothing for the unterminated final line; the store records `size = safe_offset` at that line (measured 2721 recorded vs 2915 real bytes).
2. On every later sync while the file does not grow, the tail read starts exactly at that offset, again finds no *complete* line, and re-records the same state — the deferred line is re-examined each time but structurally cannot be emitted until another `\n` arrives after it.
3. Result: store holds 14 rows / 1260 input tokens across arbitrarily many at-rest syncs; a fresh full reparse of the identical bytes yields 15 / 1350. Recovery only when a later write adds a `\n` after the deferred line (even a lone terminator) — permanent for sessions that end unterminated and dormant, self-healing for active ones.

The F-004 issue draft (`issues/I-001-tail-append-strands-last-line.md`) embeds the full verified reproducer. NOTE: an earlier narrative here ("offset recorded past the last complete line", "mid-line fragment swallows msg-9", "never revisited") was a harness artifact (Windows text-mode `\r\n` appends + the 5-second `_timed_sigs` cache) and has been retracted; `exp11/exp11b` retain the flawed setup, cite the issue's reproducer instead. The old quote "Source logs remain the source of truth" does not appear in USAGE_CACHE_IDENTITY.md; the doc's actual wording is "the persistent cache behind Overview, Stats, `/api/usage`, `/api/tools` and `tokdash export`".

### F-003 — Config write race: crash on Windows, lost updates everywhere

`_write_config` does read-modify-write with one fixed `config.json.tmp` and no lock. 4 threads × 20 mixed consent/interval writes → **63 errors (78.8%)**; 2 independent processes × 30 writes → **16+16 errors (53%)**. On POSIX the same race silently reverts whichever writer lost (e.g. a just-granted `credential_scan` consent reverting to off). The file survives (tmp+replace), but intent doesn't. Full evidence and trigger paths (dashboard POST vs `tokdash quota consent` CLI vs poller vs companion app) in `findings/confirmed/F-003-…`.

### F-001 — One huge integer disables the entire usage index, silently

`10**25` in `input_tokens` (legal JSON, no bound check in `_i()`, passes `bool`-rejection) parses fine live but raises `sqlite3.OverflowError` on insert. Verified behavior across 3 consecutive sync attempts: every attempt fails, 0 rows stored for the whole source, and the top-level compute path returns plausible numbers from a full live reparse with `source_errors=[]`. The failure repeats on every request until the offending line disappears. The same bound-less int can also reach `timestamp` columns.

### F-002 — DST-anchored date windows

`parse_date_range` builds local midnights with `.replace(tzinfo=datetime.now().astimezone().tzinfo)` — a *fixed* offset captured now, not the target dates' zone. On a New York machine in September, `date_from=2026-01-05&date_to=2026-01-05` covers `Jan 4 18:30Z → Jan 5 18:30Z` instead of `Jan 5 05:00Z → Jan 6 05:00Z`; a Jan-5 23:30 EST event is excluded from the API window but bucketed on Jan 5 by the heatmap's `'localtime'` SQL. Control run on a fixed-offset (IST) machine confirms both helpers share the same anchor (correct there). Fix direction: localize with the IANA `ZoneInfo` (where `replace()` resolves per-date offsets), never with `now().tzinfo`.

### F-005 — Unbounded `period` → 500 + detail leakage

`period_to_days` accepts any integer; `period_to_range_args` then does `end_date - timedelta(days=days-1)` → `OverflowError`. `/api/usage?period=9999999` → 500 `'date value out of range'`; a 400-nines value → 500 `'Python int too large to convert to C int'`; `/api/stats` 200s on the same input. The project's own convention (D1: unrecognized input must resolve *visibly*, and the write guard "never 500s") argues for clamp-or-400 uniformly.

---

## C. Testing gaps

### T-001 — Reasonix occurrence-counter scope — **UPGRADED TO CONFIRMED BUG in the third pass (→ issues/I-008)**
The `:N` occurrence suffix that keeps byte-identical requests countable is scoped per `_parse_all()` call — per-file in the store path, per-source in the live path. The third pass built the missing metamorphic experiment (`output/exp21_reasonix_split.py`): the same two byte-identical rows in one file count correctly everywhere, but **split across two files the live path counts both (16,238 input) while the store path collapses them via the unique index (8,119)** — a silent 50% undercount of the default view. The gap was hiding a real bug.

### T-002 — main's CI is red for anyone east of UTC+2:27 (timezone-fragile fixture)
`test_pi_fork_replay::test_parent_fork_and_views` (both params) stamps the fork's own turn at `2026-09-17T21:33:00.000Z` and asserts it appears in the local-day window `2026-09-17..2026-09-17`. East of UTC+2:27 the turn is Sep 18 local → the Sessions filter returns `[]` → assertion fails. Reproduced on IST (output/exp05): the *accounting* is correct (both sessions load; the year window shows them); only the fixture's date assumption is wrong. **Cost:** the only end-to-end regression coverage for the #126 fork-replay double-counting fix is dead across all of Asia and much of Europe/Africa — the exact code most at risk of silent double-counting. Fix: build fixture stamps from local dates (or noon UTC), or pin the window injection.

### T-001 — Reasonix occurrence-counter scope (split-file metamorphic untested)
The `:N` occurrence suffix that keeps byte-identical requests countable is scoped per `_parse_all()` call — per-file in the store path, per-source in the live path. No test pins the intended scope, and the "split a day file into two files must not change totals" metamorphic property is untested for this parser (it holds for Codex — exp06 verified split/dup/order/idempotence all hold there).

### T-003 — `_sig_cache` unbounded + Kimi's path-bound identity contract undocumented
`_timed_sigs` never evicts (2,000 distinct scan keys → 2,000 retained entries, measured). Realistic cardinality is small, so this is design weakness, not a live leak — but it contradicts the project's own bounding policy elsewhere (`_OPENCODE_QUERY_CACHE_MAX=32`, `TOKDASH_CACHE_MAX_ENTRIES`). Related: Kimi `usage.record` rows hash the *file path* into the dedup key; the rename/move contract (double-count under durable mode vs. self-heal) is undocumented and untested, unlike Codex/Pi/Cline/Qwen which key on content.

### Mutation campaign — negative result (and why it matters)
12 semantic mutations across the supersede rule, replay dedup, aggregation, unpriced-row detection, cache-hit rate, period fallback, date validation, heatmap cost, billing fallback, store tie-breaks, and tail guards. Six survived *targeted* subsets — but **every one was killed by the full suite** (M1: 584 failures; M2/M6/M8/M9/M12: 154–157). Two conclusions: (1) the suite is mutation-strong for the sampled invariants — genuinely unusual and worth keeping; (2) mutation scores from targeted subsets are misleading — this audit initially produced six false "gaps" until full-suite verification. Harness preserved at `output/mutations.py` (runs on a scratch copy; upstream untouched).

---

## D. Architectural weaknesses (concrete, actionable)

1. **Fail-open without breadcrumbs** (`compute.get_tools_data_for_range`, `run_local_coding_tools_json`): `except Exception: pass` converts any store failure — including the F-001 poison — into an invisible per-request reparse. The `source_errors` mechanism already exists and is exactly the right shape; it just never sees store-layer failures. Wire `_sync_usage_store` failures into it (even as a generic `"usage-db"` pseudo-source) and F-001 becomes self-diagnosing.
2. **Two accounting backends with drift-prone seams.** The live path and store path each re-implement aggregation (Python vs SQL). The parity tests are good (and caught a real 20% output-loss bug before), but the seams where they disagree (F-004 tail offsets, per-file vs whole-source dedup scope) are precisely where no parity test runs. A standing "randomized corpus, DB-on vs DB-off totals must match" fuzz property test would mechanically catch this whole class.
3. **Config as unlocked shared state.** `config.json` is written by dashboard handlers, CLI commands, the background poller, and the companion app, with no serialization (F-003). The usage DB got `usage_db_process_lock`; the config store never did.

## E. Security findings

**Hardening (concrete contracts, no exploit needed):**
- **S-001:** `GET /api/quota/refresh` performs credentialed provider calls + snapshot DB writes + cache clears, but the `_write_guard` (loopback + Host/Origin + CSRF token) only covers POST/PUT/PATCH/DELETE. Any website can trigger it from a victim's browser (no-cors fetch), and on the documented read-only `--bind 0.0.0.0` mode any LAN device can force credentialed calls *from the victim's IP*. Bounded by the 60 s cooldown and consent gates — but it contradicts the README's explicit "read-only network access" contract at the point of egress. Direction: make it a POST under the guard, or apply the `/api/csrf-token`-style loopback+Host check, or at minimum drop `include_network=True` on non-loopback binds.
- **S-002:** XSS audit of all 46 `innerHTML` sites: **clean today** — every data-bearing interpolation routes through `escapeHtml` or trusted `t()` translations, and `test_round4_frontend_fixes.py` pins specific sinks after a real historical XSS. Residual risk is drift: the pinned-sink regexes cover named sinks only, and `display_name` (Codex conversation-derived text) flows through both text and `title=` attribute contexts. Extend the existing tripwire to *every* `${` inside an `innerHTML` assignment (escapeHtml-wrapped, numeric, or `t('…')`) so the safe state is mechanical.
- Also noted (within F-005): `except Exception as e: HTTPException(500, detail=str(e))` in `/api/session` echoes internal messages (paths) to clients — inconsistent with the fail-closed style used by `_origin_value`, and exposed on LAN binds.

**Confirmed clean:** CORS/Host/Origin/CSRF write-gate logic (well-built, scheme-aware, fail-closed), path handling in `/api/session` (no traversal found), CI workflow permissions and action pinning, service-worker/PWA surface.
- **S-003 (third pass):** `static/index.html` loads Chart.js 4.4.0, three.js 0.160.0, flatpickr 4.6.13 and the Tailwind Play CDN from public CDNs on every dashboard open, with no `integrity` attributes, no Content-Security-Policy anywhere, and a service worker that precaches only local assets. Found via the live browser fixture test (console shows Tailwind's own "not for production" and three.js deprecation warnings on every load). Impact: third-party request on every open undermines the local-only posture; CDN compromise executes in an origin that can read all `/api/*` data; offline/air-gapped machines lose charts and the date picker. Hardening, not a demonstrated exploit → issues/I-011.

## F. Performance findings (measured)

- **P-001:** Cold session assembly costs ~13.5 ms/session: 10 → 176 ms, 100 → 1.93 s, 1,000 → 14.7 s, 5,000 → **67.7 s** (`output/exp09_scaling.py`, empty store, live parse). Third-pass re-measurement under different machine load: 5,000 → 37.8 s — the absolute seconds vary with load; the **linear constant** is the finding. Linear, not quadratic (the earlier "superlinear" phrasing applies only to the single-file 100k-event parse onset and is softened accordingly). Warm path (store) is the mitigation and works; finding is about cold/first-run/fallback UX and missing scale budgets.
- Store poisons (F-001) turn the warm path into the cold path permanently — the two findings compound.

## G. Proposed GitHub issues — **final: all drafts live under `issues/` (I-001…I-018 + README index)**

Issue-ready, copy-pasteable, standard §32 structure, honest severity. Filing order:

1. **I-001** store defers an unterminated final line indefinitely (F-004) · **I-002** config write race (F-003) · **I-003** huge-int store poison (F-001) · **I-004** DST-anchored windows (F-002) — the four strongest, fully dissected.
2. **I-006 / I-007 / I-008** — the third pass's new findings: DSH corrupt-file silent drop with stored-row deletion; DSH duplicate-file Overview/Sessions divergence; Reasonix split-file 50% undercount (upgraded from testing gap T-001).
3. **I-005** unbounded `period` 500s · **I-009** timezone-fragile CI fixtures · **I-015** store-failure observability · **I-010** quota-refresh GET hardening · **I-011** CDN/SRI/CSP hardening.
4. **I-012** cold-assembly scale (measured, softened) · **I-013** parity-property harness (30/30 negative result included) · **I-014** sig-cache/Kimi identity contract · **I-016** OpenClaw boundary quirk · **I-017** XSS sink tripwire extension.
5. **I-018** — unconfirmed leads, explicitly do-not-file.

## H. Unresolved leads (unconfirmed)

- **Claude cross-file supersede order dependence:** `claude_usage_supersedes` resolves equal-total/different-split ties by *parse order* across files, while the store's unique-index `INSERT OR REPLACE` resolves them by *last-synced file*. No realistic Claude Code corpus was available to produce different content for the same `msg_id` across two files (backup/export mid-stream is the plausible vector); the parser-level and store-level rules demonstrably differ only under that contrived input. Kept as a lead, not an issue.
- **model_normalization asymmetry:** `opus`/`sonnet` get the `claude-` prefix added; `haiku` does not — if any client reports a bare `haiku-4-5`, it forms a separate combined-view key from `claude-haiku-4-5`. Unverified against real logs.
- **Semantics warts** (consistency observations, not defects): `_contributions_from_entries` counts messages per entry while `parse_entries_json` honors `messageCount`; `messageCount=0` normalizes to 1; float token counts truncate via `int()`; `msvcrt` lock degrades to no-op after 30 s (documented) leaving BEGIN IMMEDIATE as the only cross-process guard under extreme contention — untested here.
- **Windows msvcrt no-op degrade + long syncs:** if a sync exceeds 30 s while another process waits, the waiter proceeds unlocked; SQLite `BEGIN IMMEDIATE` should protect the write, but parse-before-lock duplication of work was not stress-tested.

---

## Reproducers index

| Experiment | Demonstrates |
|---|---|
| `output/exp04_overflow_store.py` (+ second-pass re-run) | F-001 store poison, permanent, silent |
| `output/exp10b_crash_rate.py`, `output/_f3_child.py` | F-003 78.8% in-process / 53% cross-process crash rate |
| `output/exp11_tail_append.py`, `exp11b_tail_dissect.py` | F-004 store/live divergence (⚠ superseded by the corrected reproducer in `issues/I-001-...md`; contains harness artifacts described in AUDIT_REPORT F-004) |
| `output/exp07_dst_window.py`, `exp07b_dst_e2e.py` | F-002 mechanism + end-to-end through real `parse_date_range` |
| `output/exp12_live_server.py` | F-005 500s + detail leakage; write-guard/Host behavior |
| `output/exp06_properties.py` | Codex properties: idempotence, order, split, duplicate-copy — all hold |
| `output/exp09_scaling.py` | P-001 scaling curves |
| `output/exp03_fuzz_numerics.py` | negative tokens → negative cost; NaN→0; huge-int acceptance |
| `output/mutations.py` (+ `mutation-full.log`, `mutation-rest.log`) | 12-mutation campaign, full-suite verdicts |
| `output/exp18_dsh_corruption.py` (**3rd pass**) | DSH: corrupt-frame whole-file skip, stored-row deletion (1→0), version-bump erasure, Overview/Sessions duplicate divergence, zero diagnostics |
| `output/exp19_static_traversal.py` (**3rd pass**) | Traversal probes: static mount, BasePathMiddleware, /api/session — all 404, symlink tradeoff documented |
| `output/exp20_parity_property.py` (**3rd pass**) | DB-on/DB-off parity over 30 randomized Codex corpora — 30/30 (negative result; harness = I-013) |
| `output/exp21_reasonix_split.py` (**3rd pass**) | Reasonix split-file undercount (T-001 upgraded to bug → I-008) |
| `output/exp17_openclaw_boundary.py` (**3rd pass**) | OpenClaw `until` boundary Overview/Sessions divergence (documented quirk → I-016) |
