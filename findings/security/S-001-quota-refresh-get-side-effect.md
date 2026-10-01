# S-001 (security, hardening-to-moderate): `GET /api/quota/refresh` is a side-effecting GET that performs provider network calls and quota snapshot writes — outside the write guard by design

## Classification
Security finding. Not RCE/CSRF-into-config — the GET's blast radius is
bounded (provider quota reads + local SQLite rows + cache clear) — but it is
the one route that both (a) mutates local state and (b) triggers
outbound authenticated network traffic, and it deliberately bypasses the
`_write_guard` middleware (which gates POST/PUT/PATCH/DELETE only).

## The mismatch
- `api.py` `_write_guard`: "Tokdash is not bound to loopback; **write
  endpoints are disabled**" — the README/REMOTE_ACCESS contract is that
  `--bind 0.0.0.0` gives *read-only* network access and "writes disabled".
- `GET /api/quota/refresh` (loopback or not, no CSRF token, no Host check):
  calls `collect_enabled_snapshots(include_network=True, ...)` → uses the
  user's locally stored provider credentials to call
  Anthropic/OpenAI/xAI/… quota endpoints, `remember_current_snapshots(...)`
  → writes config state, `store.insert_quota_snapshots(...)` → SQLite
  writes, then `_clear_cache()`.
- The route even acknowledges GET-abuse risk elsewhere: the update-check
  consent endpoint is deliberately POST "so it works over Tailscale … while
  the CONSENT endpoint (which writes config.json) stays loopback-guarded" —
  but quota refresh writes *quota_snapshots* rows and triggers network calls
  via plain GET.

## Attack paths (bounded but real)
1. **CSRF from any website** while a user browses with the dashboard open on
   loopback: any page can issue `fetch('http://127.0.0.1:55423/api/quota/refresh',
   {mode:'no-cors'})`; the browser sends it without Origin on some flows, and
   the endpoint has no Origin/Referer/token check (write guard doesn't apply
   to GET). The response is opaque, but the side effects happen: repeated
   credentialed calls to the user's AI providers (rate-limit burn, audit-log
   noise on the provider account, quota-snapshot history pollution).
   The 60s cooldown caps the flood; `_try_begin_quota_refresh` coalesces.
2. **`--bind 0.0.0.0` exposure** (documented as read-only): any LAN device
   can `curl http://victim:55423/api/quota/refresh` and force the victim's
   machine to make credentialed provider calls *from the victim's IP*,
   plus write rows. For an exposure mode advertised as "read-only", this is
   a write-ish channel and a proven-liveness oracle for the host.

## Why "hardening" and not "critical"
- No data leaves the machine except provider quota API calls the user has
  consented to; a CSRF trigger just re-runs a consented poll early.
- Cooldown + consent gates bound the damage; no config/credentials are
  readable or writable through it.

## Suggested direction
Either make refresh a POST under the existing guard (the TUI/tab callers
already have the token flow), or add the loopback+Host/Origin check that the
/csrf-token route uses to this GET. At minimum, skip `include_network=True`
when `_is_loopback(_effective_bind())` is false — restoring the documented
"network bind = read-only" invariant at the point of egress.

## Evidence
- `api.py` `refresh_quota()` (GET route shown above), `_write_guard`
  middleware gating only `_MUTATING_METHODS`, `_host_allowlist` used by
  `/api/csrf-token` and POSTs but not by this route.
- README: "An explicit `--bind 0.0.0.0` provides read-only network access".
