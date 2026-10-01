# Second-pass skepticism review (dedup + verification)

> **THIRD PASS UPDATE (final):** every second-pass verdict below was re-verified
> once more by direct re-run, then attacked with *new* coverage (exp18–exp22,
> browser fixture test, raw-ASGI traversal probes, pricing spot-check). Outcomes:
> **T-001 was upgraded from a testing gap to a confirmed bug** (exp21: split-file
> corpora halve the DB-backed totals — see issues/I-008); **three new confirmed
> findings** came out of the DSH decoder attack (exp18: corrupt-file silent drop
> with stored-row deletion; Overview/Sessions duplicate-file divergence — issues
> I-006/I-007); **one new hardening finding** from the live browser test (CDN
> scripts without SRI/CSP — I-011). Clean bills (do not manufacture): static
> mount/BasePath/session-path traversal, DB-on/DB-off parity on randomized Codex
> corpora (30/30), pricing_db provenance, mutation campaign (unchanged). All
> findings now have copy-pasteable issue drafts under `issues/` (I-001..I-018).

Each finding re-examined against: (a) is it real, (b) is it already known
upstream, (c) is the severity claim honest, (d) would a maintainer act on it?

| ID | Verdict | Notes |
|----|---------|-------|
| F-001 | **STRENGTHENED** | Verified the poison is permanent: 3 consecutive syncs all raise OverflowError; store ends with **0 rows** (not even the healthy ones — the whole-source batch fails before commit). Live reparse masks it with `source_errors=[]`. One line, whole index down, forever. Confirmed by direct re-run. |
| F-002 | **CONFIRMED, honest severity = low-moderate** | IST control run confirms the anchor is a fixed offset (`+05:30`), equal in `dateutil` and `compute` (both surfaces share one helper). The drift needs a DST-observing machine (demoed via NY-simulated `now()`); on fixed-offset zones the code is correct. The internal inconsistency (anchor vs `'localtime'` heatmap bucketing) is objective and matches the user-facing date-picker flow. |
| F-003 | **STRENGTHENED** | Cross-process re-run: 2 processes × 30 writes → 16 + 16 errors (53%). The Windows crash is not just an in-process thread race; dashboard + CLI concurrently crash today. Lost-update component stands on code reading (no lock anywhere). |
| F-004 | **CONFIRMED (mechanism corrected in final review)** | Deterministic reproducer (binary writes, `TOKDASH_SIG_TTL=0`): the store records `size=safe_offset` at the unterminated final line (measured 2721 vs real 2915 bytes) and re-defers it on every at-rest sync — it is re-examined but cannot be emitted until another `\n` arrives after it. Incremental ≠ full (14/1260 vs 15/1350), stable for dormant files; a lone later `"\n"` rescues it. Affects all five `append_jsonl=True` sources. The earlier "offset past the last line / mid-line fragment swallows msg-9 / never revisited" narrative was a harness artifact (text-mode `\r\n` appends + the 5-second `_timed_sigs` cache) and is retracted. |
| F-005 | **CONFIRMED** | Live TestClient probes: 4 endpoints 500 with `detail` = raw exception text; ~400-digit value leaks `Python int too large to convert to C int`; `/api/stats` returns 200 for the same input (non-uniform). Low severity, trivially reachable. |
| T-001 | **UPGRADED TO CONFIRMED (3rd pass, exp21)** | The split-file metamorphic *diverges*: live path counts byte-identical rows across files (16,238 in), store path collapses them via the unique index (8,119 in) — a silent 50% undercount. What was "untested" is actually broken. → issues/I-008. |
| T-002 | **KEPT as testing gap (CI red)** | Root-caused to the fixture's `21:33Z` stamp landing on Sep 18 local east of UTC+2:27; matches PR #137's "4 pre-existing main failures". Not a product accounting bug. The real cost: the only end-to-end fork-replay coverage is dead on ~half the world's clocks. |
| T-003 | **SPLIT: kept, honest severity = design weakness** | `_sig_cache` unbounded growth measured (2,000 keys retained), but realistic key cardinality is ~1 per client per process; the Kimi path-bound hash rename contract is undocumented. No user-visible failure demonstrated — labeled design weakness + missing metamorphic test. |
| S-001 | **KEPT as hardening (not vuln)** | GET side effects outside the write guard are real; blast radius bounded (consented provider poll re-run + snapshot rows + cooldown). The README's "--bind 0.0.0.0 = read-only" claim is the concrete contract violated. |
| S-002 | **RECLASSIFIED: keep as hardening/regression-net, explicitly NOT a vuln** | The repo already has XSS-sink regression tests (test_round4_frontend_fixes.py pins `escapeHtml` at specific sinks after a real XSS fix); my audit of all 46 innerHTML sites found no unescaped data-bearing interpolation. Value = extend that existing tripwire to *every* sink (count-pinned regexes cover only named ones) + a central escape policy. |
| P-001 | **KEPT, measured** | 13.5 ms/session cold assembly; 5k sessions = 68 s; 100k-event parse shows superlinear onset (24× for 10×). Warm path (store) is the mitigation and works; finding is about cold/first-run/fallback UX and missing scale budgets. |
| Mutation campaign | **NO FINDINGS STAND** — documented negative result (3rd-pass parity fuzz concurs: 30/30 Codex corpora in parity) | All 6 targeted-run survivors were killed by the full suite (M1: 584 failures; M2/M6/M8/M9/M12: ~154–157). The suite is mutation-strong for the sampled invariants. Worth stating in the report: the earlier "survivors" were an artifact of narrow subsets, and this is exactly why mutation scores must be full-suite. |
| CI/deps scan | **NO FINDING (do not manufacture)** | Actions are SHA-pinned with version comments, `permissions:` scoped per workflow, `persist-credentials: false`, pypublish uses pinned action. Dependency ranges are floor-style (`fastapi>=0.115.0`) but the app pins nothing dangerous; `textual` is deliberately capped `<9` with a rationale. |

## Final classification for the report (3rd pass, final)
- Confirmed bugs (reproducible): F-004 (I-001, mechanism corrected in final review — see the issue's reproducer, not exp11/exp11b), F-003 (I-002), F-001 (I-003), F-002 (I-004), F-005 (I-005), **DSH corrupt-file drop + row deletion (I-006), DSH Overview/Sessions divergence (I-007), Reasonix split-file undercount (I-008 — upgraded from T-001)**
- Testing gaps: T-002 (CI red, I-009), T-003 (I-014); parity property harness delivered (I-013, 30/30 negative result included); mutation-campaign negative result
- Security: S-001 (hardening, I-010), **S-003 CDN/SRI/CSP (I-011, 3rd pass)**, S-002 (hardening/regression net, I-017)
- Performance: P-001 (I-012, softened: linear with a heavy constant, not superlinear)
- Observability: store-failure invisibility (I-015); OpenClaw boundary quirk (I-016); leads (I-018, do not file)
- 3rd-pass clean bills: traversal probes (static mount, BasePathMiddleware, /api/session), pricing_db provenance, Codex-class DB/live parity
- Issue drafts: `issues/I-001..I-018` — file I-001→I-004 first, I-006/I-007/I-008 are the new third-pass findings.
