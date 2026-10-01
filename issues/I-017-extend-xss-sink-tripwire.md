# [tests/hardening] Extend the XSS sink regression net from named sinks to every `innerHTML` interpolation

## Summary

Not a vulnerability report — the frontend is clean as of `0a179d0`, by direct inspection: all 46 `innerHTML` assignment sites in [`src/tokdash/static/index.html`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/static/index.html) route their data-bearing interpolations through `escapeHtml`, numeric conversion, or trusted `t()` translation literals. The repo already knows this class of bug: a real XSS was fixed before, and [`tests/test_round4_frontend_fixes.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/tests/test_round4_frontend_fixes.py) pins `escapeHtml` at the specific sinks that were involved.

The residual risk is drift: those pins cover only the *named* sinks from that historical fix. A new panel or tooltip that interpolates unescaped data into `innerHTML` passes CI today. This proposal widens the existing tripwire to a structural invariant over every sink, so the safe state is enforced mechanically instead of re-audited by hand.

## Reproduction (the gap, not a bug)

Current net:

```python
# tests/test_round4_frontend_fixes.py — pins specific, named sinks, e.g.:
assert "escapeHtml(...)" in html        # the sinks fixed in round 4
```

A hypothetical new site added tomorrow is unconstrained:

```javascript
// anywhere in static/index.html or static/js/**
el.innerHTML = `<span>${session.project}</span>`;   // unescaped, unpinned, untested
```

No test fails. The data flowing into such sinks is attacker-influenceable by design — session logs are semi-trusted input, and fields like `display_name` (Codex conversation-derived text) flow through both text and `title="..."` attribute contexts — which is precisely why the historical fix happened.

## Expected behavior

Established by the repo's own practice (the round-4 regression tests): a returned XSS should be structurally impossible to reintroduce unnoticed. The natural extension of the existing technique is a fail-closed invariant over every assignment site, not a name list.

## Actual behavior

- The tripwire pins named sinks only; new sinks are unguarded.
- Manual audit baseline (this review, commit `0a179d0`): 46 `innerHTML` sites, all interpolations safe — so adding the invariant today would pass immediately and only constrain future regressions.

## Impact

None demonstrated — this is regression-prevention infrastructure for a class of bug the project has already shipped once and fixed. The cost asymmetry is the argument: one test file versus a manual sink audit per frontend change (the audit's 46-site sweep is exactly the work CI could do).

## Root cause

n/a (hardening proposal).

## Evidence

- Site census: 46 `innerHTML` sites in [`src/tokdash/static/index.html`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/static/index.html), all interpolating through safe forms (manual audit; probe script [`output/exp08_xss_probe.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp08_xss_probe.py) available on request).
- Existing named-sink pins: [`tests/test_round4_frontend_fixes.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/tests/test_round4_frontend_fixes.py).
- `display_name` trust path: Codex-derived titles rendered into text and `title=` attribute contexts in the same file.

## Suggested direction

Add a test that regex-extracts every `innerHTML` / `insertAdjacentHTML` assignment from the static assets and fails on any `${...}` interpolation that is not one of the safe forms (`escapeHtml(...)`, numeric conversion, boolean, `t('…')` literal) — and, fail-closed, on any assignment *form* it doesn't recognize. Keep the existing named-sink pins as documentation of the historical fix.
