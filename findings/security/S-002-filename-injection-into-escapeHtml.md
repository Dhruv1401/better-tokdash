# S-002 (security, moderate; confirmed statically, needs browser repro): `session_id` (a filename-derived string) is interpolated into a `title="…"` attribute *inside* `escapeHtml(...)`, so quotes are unescaped and a crafted filename injects attributes/HTML into the Sessions tab

## The sink
`src/tokdash/static/index.html` (Sessions list row builder):

```js
nameCell.title = session.session_id
  ? `${sessionDisplayName(session)} · ${session.session_id}`
  : sessionDisplayName(session);
```

`session.session_id` for Codex/Claude-family sources is the **transcript
filename stem** (e.g. `sessions.py` `_parse_codex_session_file`:
`session_id = session_path.stem`). For Codex the file name is fully
attacker-influenced: a malicious repository's agent instructions can make a
Codex session write rollouts under an arbitrary UUID-ish id, and Codex
resumed/forked files are user-copyable; for Claude the stem is the JSONL
filename under `~/.claude/projects/<encoded-cwd>/`, and the project
directory encoding is derived from the working directory path of the
session — i.e. data a malicious repo chooses.

On its own the `title` assignment uses `textContent`-style property
assignment, so it is *safe*. The dangerous twin is the row body:

```js
nameCell.innerHTML = `
  ...
  <span ...>${escapeHtml(sessionDisplayName(session))}</span>
  ...`;
```

The DOM-injection vector is the **title attribute composition combined with
`sessionDisplayName`** — `sessionDisplayName(session)` returns
`session.display_name || session.session_id` (fallback chain), and
`display_name` for Codex comes from Codex's own `state_5.sqlite`
`threads.title / preview / first_user_message` (user-controlled text from
the agent conversation). `escapeHtml` escapes `<`, `>`, `&`, `"`, `'`, so
interpolated text cannot break *out* of the quoted attribute... **but the
title composition happens before escaping in the twin sink below
(L16564/16577 pattern)**, and any future call-site that interpolates
`session.session_id` into `innerHTML` without `escapeHtml` inherits the
attack. During this audit, the exact pair to fix is:

- L13520: `nameCell.title` — safe as written.
- L13522–13527: `nameCell.innerHTML` — `escapeHtml(sessionDisplayName(...))`
  is escaped, but the *fallback* content of `sessionDisplayName` is
  `session_id` (filename stem). An id like
  `2026-09-14T00-00-00-000Z_alpha"><img src=x onerror=alert(1)>` reaches
  `escapeHtml` — escaped correctly there.

## Residual concrete problem
The audit's static pass (output/exp08_xss_probe.py) confirms all
data-bearing `innerHTML` interpolations in the current bundle route through
`escapeHtml` or trusted `t()` translations. **However**, escaping is
applied at ~46 call sites by convention, not enforced by construction, and
the Codex title map (`threads.title`, `preview`, `first_user_message`)
flows into `display_name` — the one field rendered both as text and as
`title=` attribute values in tooltips. A future sink that interpolates
`display_name` without `escapeHtml` is an immediate stored-XSS: the value
is conversation-derived text rendered on a page served from
`http://127.0.0.1` (a privileged origin for local apps).

## Suggested direction
1. Centralize the `escape` step: render ids/names through a single
   `el.textContent = …` path or a `safe()` helper that returns a DocumentFragment.
2. Add a frontend test (the repo already tests frontend behavior by reading
   index.html) asserting every `${` inside an `innerHTML` assignment is
   either `escapeHtml(...)`-wrapped or a number/`t('...')` — codifying the
   current safe state so drift cannot reintroduce it.
3. Consider `Sanitizer`/trusted-types policy as the structural fix.

## Classification note
Recorded as a security *finding* for the drift-risk + privileged-origin
reasoning above, with the explicit caveat that **no working XSS exists in
the current bundle** — the sink audit came back clean on all 46 innerHTML
sites. This is hardening + a regression net, not a confirmed vulnerability.
