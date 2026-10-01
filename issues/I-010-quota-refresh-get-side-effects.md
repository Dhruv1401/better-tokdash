# [security/hardening] `GET /api/quota/refresh` performs credentialed provider calls and DB writes outside the write gate — in tension with the documented read-only posture

## Summary

Tokdash's write gate (loopback bind + Host/Origin checks + per-process CSRF token) protects every `POST`/`PUT`/`PATCH`/`DELETE` ([`src/tokdash/api.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/api.py), `_write_guard` at line ~817, `_MUTATING_METHODS` at line ~697). `GET /api/quota/refresh` (line ~2092) is exempt as a read, but it is not read-only in effect: it performs credentialed network calls to the configured quota providers (`collect_enabled_snapshots(include_network=True, ...)`), writes the returned snapshots into the quota DB (`insert_quota_snapshots`), and clears caches.

The exemption is deliberate and documented: [`docs/guides/REMOTE_ACCESS.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/guides/REMOTE_ACCESS.md) states the route "is exempt from the write gate like any other read" so the Quota tab works over Tailscale Serve. The tension: the same docs market external-hostname access as **read-only** ("Tailscale Serve is read-only for state-changing API actions"; the README's `--bind 0.0.0.0` framing is "read-only network access"), while this route makes the *server* perform authenticated provider requests on behalf of any client that can reach it — a LAN device hitting `--bind 0.0.0.0` directly, or any external reader through a header-preserving proxy.

This is a hardening finding about an intentional trade-off, not a demonstrated vulnerability: exploitation requires the victim to have consented to quota polling, and the 60-second cooldown (`_QUOTA_REFRESH_COOLDOWN_SECONDS`) caps the rate.

## Reproduction

Static (code path, verified by reading [`src/tokdash/api.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/api.py)):

```python
# GET /api/quota/refresh (line ~2092):
#   collect_enabled_snapshots(include_network=True, store=store)  <- credentialed HTTP to providers
#   remember_current_snapshots(snapshots)                          <- DB write
#   store.insert_quota_snapshots(snapshots)                        <- DB write
#   _clear_cache()                                                 <- state change
# ...while _write_guard only inspects POST/PUT/PATCH/DELETE.
```

Behavioral check on the default loopback bind: `curl http://127.0.0.1:8765/api/quota/refresh` from any local page (e.g. via a no-cors `fetch`) triggers the same path subject to the consent gates and cooldown. I did **not** execute the cross-site/LAN attack against a real configured install, so the remote-trigger scenario below is derived from the code path and the documented proxy behavior, not observed end-to-end.

## Expected behavior

At minimum, the documented "read-only" property of external-hostname access should be accurate about egress: on non-loopback binds, a GET should not trigger credentialed network calls initiated by the server. The project's own conventions elsewhere (fail-closed Host/Origin checks, the CSRF-gated POST route for the same action) support treating egress as a side effect worth gating.

## Actual behavior

- The GET route triggers provider polling with stored credentials, snapshot persistence, and cache clears, subject to: quota tracking being enabled, per-provider consents, and the 60 s cooldown.
- The write gate never sees GET, so none of its checks apply.
- The route's own docstring/comment states the intent ("Read-only poll (no quota consumed)... intentionally GET"), which is accurate about the provider APIs being read-only endpoints but not about the server-side actions the route performs.

## Impact

Demonstrated: the code path and its exemption (source-verified). Derived, not demonstrated: any website can trigger the route from a victim's browser (no-cors GET), and on `--bind 0.0.0.0` any LAN device can force credentialed provider calls from the victim's IP at cooldown rate, with snapshot rows persisted locally. Bounded by consent gates, the cooldown, and the read-only nature of the polled endpoints. No secret exposure, no CSRF-protected state change, and no data exit was demonstrated.

## Root cause

Not a defect in the guard — the guard is functioning as designed. The finding is that this route's convenience GET concentrates the one combination (credentialed egress + persistence) that sits outside every gate, in tension with the documented read-only posture.

## Evidence

- Route and side effects: [`src/tokdash/api.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/api.py) line ~2092 (`collect_enabled_snapshots(include_network=True, ...)`, `remember_current_snapshots`, `insert_quota_snapshots`, `_clear_cache`).
- Gate scope: `_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}` (line ~697), `_write_guard` (line ~817).
- Documented exemption and read-only framing: [`docs/guides/REMOTE_ACCESS.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/guides/REMOTE_ACCESS.md) (lines ~69–72, ~369) and README (`--bind 0.0.0.0` "read-only network access", line ~384).

## Suggested direction

Behavior-level goal: egress-triggering actions should not be reachable by unauthenticated GET on non-loopback binds. Options (implementation choice is the maintainer's): make the mutating action POST-only under the existing gate; or keep GET but require loopback Host/Origin for `include_network=True`; or degrade the GET to `include_network=False` when bound non-loopback. The Tailscale Serve use case documented in REMOTE_ACCESS.md should be preserved either way — the current route exists to serve it.
