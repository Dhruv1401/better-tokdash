# [api] Unbounded numeric `period` values cause 500s returning raw exception text; endpoints disagree on the same input

## Summary

The `period` parameter (a named period or an integer day count) is not bounded before use. `period_to_days` accepts any integer and `period_to_range_args` then computes date arithmetic that raises `OverflowError` for large values. `/api/usage` and `/api/tools` return HTTP 500 whose body is the raw exception text; `/api/sessions` returns 500 the same way once its required `tool` parameter is supplied; `/api/stats` returns 200 for the identical input. The exception strings leak Python internals (`date value out of range`, `Python int too large to convert to C int`) to any client, and the dashboard can be exposed unauthenticated on the LAN with `--bind 0.0.0.0`.

Severity: low. This is a robustness/consistency defect, not a security vulnerability — no data is exposed beyond the exception strings, and the primary deployment is loopback.

## Reproduction

Verified on v2.6.8 (`0a179d0`) with the real app via `fastapi.testclient.TestClient` (no server needed):

```python
import os, tempfile
from pathlib import Path
home = Path(tempfile.mkdtemp()); os.environ["TOKDASH_DATA_DIR"] = str(Path(tempfile.mkdtemp()))
os.environ["TOKDASH_USAGE_DB"] = "0"
import pathlib; pathlib.Path.home = classmethod(lambda cls: home)

from fastapi.testclient import TestClient
from tokdash import api as api_mod
client = TestClient(api_mod.app)

p = "9" * 400
for ep, params in [("usage", {}), ("tools", {}), ("insights", {}),
                   ("sessions", {"tool": "codex"}), ("stats", {})]:
    r = client.get(f"/api/{ep}", params={"period": p, **params})
    print(ep, r.status_code, r.text[:70])
```

Observed (verified verbatim):

```
usage    500 {"detail":"Python int too large to convert to C int"}
tools    500 {"detail":"Python int too large to convert to C int"}
insights 500 {"detail":"Python int too large to convert to C int"}
sessions 500 {"detail":"Python int too large to convert to C int"}
stats    200 ...
```

With `period=9999999` the same four endpoints return 500 `{"detail":"date value out of range"}` and `stats` still returns 200. (Note: `/api/sessions` requires its `tool` query parameter — without it the request fails validation with 422 before the period is ever used.)

## Expected behavior

Per the project's own stated conventions (the README/design language treats unrecognized input as something that must resolve *visibly*, and changelog 0.4.1 shows period-handling bugs being fixed and locked with regression tests), an out-of-range numeric period should produce a uniform 4xx with a stable message — not a 500 whose body is a Python exception string, and not different outcomes per endpoint for the same input.

## Actual behavior

- `period_to_range_args` in [`src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py) raises `OverflowError` (via `timedelta`/date arithmetic) for large integer periods; smaller-but-still-absurd values (9,999,999 days) raise `ValueError` from `date.min`/`date.max` arithmetic.
- The generic handler in [`src/tokdash/api.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/api.py) converts the exception to a 500 with `detail = str(e)`.
- `/api/stats` handles the same input and returns 200 — verified for both the 400-digit value and 9,999,999.
- Separately (same handler pattern): `/api/session` wraps arbitrary failures as `HTTPException(500, detail=str(e))`, which echoes internal messages such as filesystem paths — noted here as the same pattern, not separately reproduced with adversarial input.

## Impact

Demonstrated: unauthenticated 500s with internal exception text on a loopback service, reproducible from the URL alone; non-uniform semantics across endpoints. Requires crafted numeric input (malformed value, not ordinary use). No data exposure beyond the exception strings was demonstrated; the LAN-exposure framing applies only when the operator opts into `--bind 0.0.0.0`, which the docs already flag as cautious-use.

## Root cause

Established: no bound on the numeric period at the shared boundary (`period_to_days` / `period_to_range_args`), plus the handler passing `str(e)` into the response body.

## Evidence

- Inline reproducer above (verified verbatim; exact statuses and bodies shown).
- `period_to_range_args` arithmetic in [`src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py).
- Related in-repo precedent: changelog 0.4.1 — "period=all / period=year silently returned today only" was fixed and given a regression test; this is the remaining unbounded corner of the same parameter.

## Suggested direction

Clamp or reject at the shared boundary: values outside a documented range return a uniform 400 ("period out of range") for every route that accepts `period`, and the generic handler should stop placing `str(e)` into `detail` (log the traceback server-side, return a generic body).
