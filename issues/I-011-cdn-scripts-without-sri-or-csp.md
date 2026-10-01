# [security/hardening] Dashboard's CDN dependencies ship without SRI or a Content-Security-Policy — complement to the open CDN-failure issues (#135, #136)

## Summary

`src/tokdash/static/index.html` (lines 28–39) loads the dashboard's runtime dependencies from public CDNs on every page open: the Tailwind Play CDN, Chart.js 4.4.0, three.js 0.160.0, flatpickr 4.6.13, and Google Fonts. None of the script tags carries an `integrity` attribute, the server sends no `Content-Security-Policy`, and the service worker ([`src/tokdash/static/sw.js`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/static/sw.js)) precaches only local assets.

Open issue [#135](https://github.com/JingbiaoMei/Tokdash/issues/135) covers the *availability* consequence (no fallback/offline support when a CDN is unreachable) and open PR [#136](https://github.com/JingbiaoMei/Tokdash/issues/136) proposes *user-facing failure notices*. This report covers the distinct supply-chain exposure neither addresses: today the dashboard executes whatever those URLs serve, unverified, in an origin that can read every local API response. Pinning the versions in the URL prevents version drift but not tampering at the pinned version; only Subresource Integrity (or vendoring) detects that, and only a CSP can bound what a compromised dependency could load next.

This is a hardening finding — no compromise is demonstrated or alleged; the CDN dependency itself is the exposure.

## Reproduction

Static facts, verified against commit `0a179d0`:

- [`src/tokdash/static/index.html`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/static/index.html) lines 28–39: the five CDN references; `integrity=` appears nowhere in the file.
- [`src/tokdash/static/sw.js`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/static/sw.js): `CORE_ASSETS` is local-only (root, manifest, icons); no CDN caching or fallback.
- No `Content-Security-Policy` header anywhere in [`src/tokdash/api.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/api.py) or the static assets.
- [`src/tokdash/static/manifest.webmanifest`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/static/manifest.webmanifest): `"display": "standalone"` (PWA posture alongside CDN-only dependencies).

Behavioral corroboration (observed during a live dashboard session against `serve --dev-fixture dense`): the browser console shows Tailwind's own warning — "cdn.tailwindcss.com should not be used in production…" — and three.js's deprecation warning for `build/three.min.js` on every load; with the network unavailable, Chart.js/three.js/flatpickr fail to load and charts and the date picker are non-functional (the availability side already documented in #135).

## Expected behavior

Reasonable-robustness expectation for a local-first tool whose README emphasizes data staying on the machine: runtime third-party code should either ship with the package (Tokdash already vendors its own `static/js/anime.esm.js`, so the pattern exists in-repo), or carry `integrity` + `crossorigin` attributes, with a CSP (`script-src` limited to what the page actually needs) bounding execution to the intended sources. The current state satisfies none of the three.

## Actual behavior

- Every dashboard open performs third-party requests (jsDelivr, cdn.tailwindcss.com, fonts.googleapis.com), unverified and unbounded by policy.
- A modification at any pinned CDN version (publisher compromise, CDN compromise, on-path modification on a hostile network) executes with full access to the dashboard origin — which can read all of `/api/*` (usage history, sessions, projects).
- The PWA's `"standalone"` posture implies offline capability the CDN-only dependencies undercut (per #135).

## Impact

Static exposure, verified; no exploit demonstrated. Practical consequences if it were ever exploited: full read access to the user's local usage data through the unauthenticated API, plus the ability to act with the page's powers. Even absent attack, the Google Fonts request leaks a hit on every dashboard open — in tension with the local-only posture the project otherwise maintains carefully (loopback defaults, consent-gated egress). Related: #135 (availability/fallback) and #136 (failure notices) address the same dependency list from the reliability angle; this report's SRI/CSP/vendoring gap is complementary and would pair naturally with whichever fix lands there.

## Root cause

Not a code defect — a distribution choice: third-party runtime code is loaded unverified at page-load time rather than shipped or integrity-checked.

## Evidence

- [`src/tokdash/static/index.html`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/static/index.html) lines 28–39; no `integrity` attribute in the file.
- [`src/tokdash/static/sw.js`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/static/sw.js) `CORE_ASSETS`; [`src/tokdash/static/manifest.webmanifest`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/static/manifest.webmanifest) `"display": "standalone"`.
- No CSP header in [`src/tokdash/api.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/api.py).
- Upstream context: [#135](https://github.com/JingbiaoMei/Tokdash/issues/135) (open, availability), [#136](https://github.com/JingbiaoMei/Tokdash/issues/136) (open PR, failure toasts).

## Suggested direction

The invariant: code executing in the dashboard's origin should be verifiably the code the release shipped. Vendoring the five dependencies into `static/vendor/` (exact minified files, hash-verified at build time) satisfies it and simultaneously resolves most of #135; adding `integrity`/`crossorigin` to whatever remains remote, plus a `Content-Security-Policy` response header, closes the residual gap. The Tailwind Play CDN in particular has a supported production replacement (a build-time CSS artifact), and the project's own CI already applies this exact discipline to GitHub Actions (SHA-pinned with version comments).
