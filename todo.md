# Tokdash Adversarial Audit — COMPLETE (third pass, final state)

## Mission
Deep adversarial audit of https://github.com/JingbiaoMei/Tokdash (v2.6.8, 0a179d0).
Hunt silent correctness failures: bad input → no exception → plausible output → wrong result.
**Deliverable complete: `issues/` holds 18 issue-ready drafts (I-001…I-018) + README index.
Final report: `AUDIT_REPORT.md` (third-pass headers). Skepticism ledger: `findings/REVIEW.md`.**

## Environment
- Repo: `tokdash/` (main @ 0a179d0). Artifacts: `findings/`, `output/` (exp01–exp21, mutations, logs), `issues/`.
- Python 3.12 on Windows/IST. Run experiments from `tokdash/` as `PYTHONPATH=src python ../output/expNN_*.py`.
- Experiments isolated via Path.home monkeypatch + TOKDASH_DATA_DIR (caveat: Hermes reads platform dirs, leaks real data into sandbox aggregates — parity unaffected).

## Findings ledger (all issue-ready drafts exist under issues/)
- I-001 (F-004, confirmed, re-verified ×3) tail-append strands final unterminated line → DB-on undercount. output/exp11, exp11b.
- I-002 (F-003, confirmed) config.json unserialized RMW + shared .tmp → Windows PermissionError 78.8%/53% + lost updates. output/exp10b, _f3_child.
- I-003 (F-001, confirmed) huge int → store OverflowError → permanent silent live-reparse fallback. output/exp04. **3rd pass: also confirmed through the DSH path (exp18 S8).**
- I-004 (F-002, confirmed) date windows anchored to current DST offset; disagrees with heatmap 'localtime'. output/exp07, exp07b.
- I-005 (F-005, confirmed) unbounded period → 500 + detail leakage; /api/stats 200s. output/exp12.
- I-006 (**NEW 3rd pass**) DSH corrupt/unsupported file → whole-file silent drop AND deletion of previously stored rows (1→0); zero diagnostics (design doc's counter never added). output/exp18 S2/S7/S9/S10.
- I-007 (**NEW 3rd pass**) DSH duplicate files: Overview last-wins vs Sessions first-wins diverge (999/99 vs 100/10); non-adjacent (turn,step) dup: Overview 411 vs Sessions 511. output/exp18 S5/S6.
- I-008 (**T-001 UPGRADED 3rd pass**) Reasonix occurrence counter per-parse-call → split-file corpus halves DB totals (16,238 → 8,119). output/exp21.
- I-009 (T-002, kept) timezone-fragile pi-fork fixtures leave main red east of UTC+2:27. output/exp05.
- I-010 (S-001, kept) GET /api/quota/refresh side effects outside write guard vs "0.0.0.0 = read-only".
- I-011 (**NEW 3rd pass**, S-003) CDN scripts (Chart.js/three.js/flatpickr/Tailwind Play) no SRI/no CSP/no offline fallback; found via live browser fixture test.
- I-012 (P-001, softened) cold assembly ~13.5 ms/session linear → 68s @ 5k (37.8s on re-run; constant is the finding). output/exp09.
- I-013 (**NEW 3rd pass**) DB-on/DB-off parity property harness; 30/30 Codex corpora in parity (negative result delivered). output/exp20.
- I-014 (T-003, kept) _sig_cache unbounded (2k keys) + Kimi path-bound identity undocumented. output/exp14*.
- I-015 (arch, kept) store-sync failures invisible to source_errors (enabler of I-003's silence).
- I-016 (**3rd pass**) OpenClaw `until` boundary Overview-inclusive vs Sessions-exclusive (documented quirk). output/exp17.
- I-017 (S-002, kept) extend XSS sink tripwire (audit found 0 XSS across 46 innerHTML sites).
- I-018 (leads, do-not-file) Claude tie-break order, haiku prefix asymmetry, semantics warts, msvcrt degrade.

## Third-pass verification & new coverage (all clean bills where noted)
- exp18 (dsh corruption): corrupt interior frame → whole-file skip; **stored rows deleted 1→0**; version-bump erases session (4→3); 0 log records for any skip; huge-int OverflowError through sync_files (S8).
- exp19 (traversal, raw ASGI): static mount, BasePathMiddleware, /api/session — all 404/clean; follow_symlink=True escape = documented pipx/uv tradeoff (needs venv write access = already game over). Clean bill.
- exp20 (parity property): 30/30 randomized Codex corpora DB-on == DB-off (multiset + aggregate). Clean bill for stable-key sources; harness delivered as I-013.
- exp21 (Reasonix split): CONFIRMED the T-001 gap is a live bug (see I-008).
- pricing spot-check (exp22 folded into manual): 385 models, per-model source notes, provisional flags (glm-5.3), official-source citations — no manufacture-able finding; grok-4.20+ present; unpriced-row invariant already mutation-tested (M5 killed).
- Browser fixture test: `serve --dev-fixture dense` + Preview panel → page renders, 10 charts, no JS errors → surfaced I-011 (CDN tags) instead. Server killed (PID 2584) after test.
- All second-pass experiments re-verified by direct re-run (exp04, exp07b, exp09, exp10b, exp11/11b, exp12).

## Mutation testing (unchanged, final)
- 12 mutations, all KILLED by full suite (M1: 584 fails; others 154–157). Suite is mutation-strong for sampled invariants. output/mutations.py + logs.

## Baseline
- `4 failed, 3054 passed, 9 skipped` on Windows/IST (matches PR #137). output/test-baseline.log.

## Nothing remaining
All deliverables done: findings/ (evidence), issues/ (18 drafts + index), AUDIT_REPORT.md (3rd-pass headers), REVIEW.md (final verdicts), todo.md (this file).
