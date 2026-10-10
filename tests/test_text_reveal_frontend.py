"""Behaviour tests for the topbar text reveal & morph.

The dashboard's status line (`#lastUpdate`) starts as a shimmering "Loading…"
placeholder and is overwritten with real text when the dashboard resolves — the
success path (`updateTimestamp`) writes "Last updated: HH:MM", the failure path
(`setDashboardFetchStatus`) writes the load error. This module wraps those two
app writers so the FIRST resolve unveils the text character by character and any
LATER change cross-fades. It invents nothing and observes nothing global: only
those two functions are wrapped, and the app still writes the value it always
wrote.

These tests pin the markup/contract statically, then drive the real wrapped
writers in Node against a small DOM stub, so "revealed / morphed / swapped
instantly" is observed as the element's own children and state, not by reading
the module's bookkeeping.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import tokdash

STATIC = Path(tokdash.__file__).parent / "static"
INDEX_HTML = STATIC / "index.html"
MODULE_JS = STATIC / "js" / "animations" / "text-reveal.js"
BARREL = STATIC / "js" / "animations" / "index.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _module() -> str:
    return MODULE_JS.read_text(encoding="utf-8")


# --- Static contract --------------------------------------------------------


def test_module_exports_the_public_api():
    src = _module()
    for name in ("revealText", "morphText", "mountTextReveal", "textRevealState"):
        assert f"export function {name}" in src, name


def test_module_wraps_the_two_real_writers():
    src = _module()
    assert "wrapStatusWriter(window, 'updateTimestamp')" in src
    assert "wrapStatusWriter(window, 'setDashboardFetchStatus')" in src
    # It must not install any global observer (the codebase pins that for index.html).
    assert "MutationObserver" not in src


def test_module_is_exported_and_mounted():
    assert "./text-reveal.js" in BARREL.read_text(encoding="utf-8")
    html = _source()
    assert "mountTextReveal()" in html


def test_reveal_and_motion_css_exist():
    css = _source()
    assert ".tokdash-reveal-char" in css
    assert "@keyframes tokdash-reveal-char" in css
    assert ".tokdash-morph-out" in css
    assert "@keyframes tokdash-morph-out" in css
    assert "@keyframes tokdash-morph-in" in css
    assert "cubic-bezier(.16, 1, .3, 1)" in css
    # Reduced-motion swaps instantly: the reveal char is held still.
    guard = css.index("@media (prefers-reduced-motion: reduce) {\n      .tokdash-reveal-char")
    assert "animation: none" in css[guard:guard + 220]


def test_last_update_is_still_the_loading_placeholder():
    # The anchor is real: the topbar status ships as a shimmering placeholder.
    html = _source()
    assert 'id="lastUpdate"' in html
    assert 'class="tokdash-loading-placeholder' in html[html.index('id="lastUpdate"'):html.index('id="lastUpdate"') + 200]


# --- Behaviour (real module, stub DOM) -------------------------------------

_HARNESS = r"""
function makeText(v) { const t = makeEl('#text'); t.children = []; t._text = String(v); return t; }
function makeEl(tag) {
  const el = { tagName: tag, dataset: {}, attributes: {}, children: [], _text: '', classSet: new Set(),
    style: { props: {}, setProperty(k, v) { this.props[k] = v; } } };
  el.classList = { add: (...c) => c.forEach((x) => el.classSet.add(x)),
                   remove: (...c) => c.forEach((x) => el.classSet.delete(x)),
                   contains: (c) => el.classSet.has(c) };
  Object.defineProperty(el, 'className', { get: () => [...el.classSet].join(' '),
    set: (v) => { el.classSet = new Set(String(v).split(/\s+/).filter(Boolean)); } });
  Object.defineProperty(el, 'textContent', {
    get: () => (el.children.length ? el.children.map((c) => c.textContent).join('') : el._text),
    set: (v) => { el.children = [makeText(v)]; el._text = ''; } });
  el.appendChild = (n) => { if (n && n.__frag) el.children.push(...n.children); else el.children.push(n); return n; };
  el.insertBefore = (n) => { el.children.unshift(n); return n; };
  el.remove = () => {};
  el.setAttribute = (k, v) => { el.attributes[k] = v; };
  el.getAttribute = (k) => el.attributes[k] ?? null;
  const match = (node, sel) => sel.startsWith('.') && node.classSet && node.classSet.has(sel.slice(1));
  const walk = (node, out = []) => { (node.children || []).forEach((c) => { out.push(c); walk(c, out); }); return out; };
  el.querySelector = (sel) => walk(el).find((n) => match(n, sel)) || null;
  el.querySelectorAll = (sel) => walk(el).filter((n) => match(n, sel));
  el.ownerDocument = DOC;
  return el;
}

let currentEl = null;
const DOC = {
  createElement: (t) => makeEl(t),
  createDocumentFragment: () => { const f = makeEl('#frag'); f.__frag = true; return f; },
  getElementById: (id) => (id === 'lastUpdate' ? currentEl : null),
};
globalThis.document = DOC;

function withLoadingLabel() {
  const el = makeEl('p');
  const label = makeEl('span'); label.className = 'tokdash-loading-label'; label.textContent = 'Loading...';
  el.appendChild(label);
  return el;
}

const report = {};

// Scenario 1 (motion on): first resolve reveals, later change morphs.
{
  currentEl = withLoadingLabel();
  let stamp = 'Last updated: 11:07';
  globalThis.window = { document: DOC, matchMedia: () => ({ matches: false }),
    updateTimestamp: () => { currentEl.textContent = stamp; },
    setDashboardFetchStatus: () => { currentEl.textContent = 'Load failed: boom'; } };
  const m = await import(process.argv[2]);
  m.mountTextReveal();
  window.updateTimestamp();  // first resolve -> reveal
  const afterFirst = m.textRevealState(currentEl);
  stamp = 'Last updated: 11:08';
  window.updateTimestamp();  // later change -> morph
  const afterSecond = m.textRevealState(currentEl);
  report.motion = {
    wrapped: !!(window.updateTimestamp.__tokdashTextReveal),
    firstRevealChars: afterFirst.revealChars,
    firstPrev: afterFirst.prev,
    secondMorphing: afterSecond.morphing,
    secondHasOutgoing: afterSecond.hasOutgoing,
    secondPrev: afterSecond.prev,
  };
  // Failure writer morphs too.
  window.setDashboardFetchStatus();
  const afterFail = m.textRevealState(currentEl);
  report.motion.failHasOutgoing = afterFail.hasOutgoing;
}

// Scenario 2 (reduced motion): the text swaps instantly, no spans.
{
  currentEl = withLoadingLabel();
  globalThis.window = { document: DOC, matchMedia: () => ({ matches: true }),
    updateTimestamp: () => { currentEl.textContent = 'Last updated: 12:00'; },
    setDashboardFetchStatus: () => {} };
  const m = await import(process.argv[2]);
  m.mountTextReveal();
  window.updateTimestamp();
  const st = m.textRevealState(currentEl);
  report.reduced = {
    revealChars: st.revealChars,
    morphing: st.morphing,
    text: currentEl.textContent,
  };
}

console.log(JSON.stringify(report));
"""


@needs_node
def test_text_reveal_and_morph_behaviour(tmp_path: Path):
    harness = tmp_path / "reveal.mjs"
    harness.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), MODULE_JS.as_uri()],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])

    motion = report["motion"]
    assert motion["wrapped"] is True
    # First resolve unveiled the real text character by character.
    assert motion["firstRevealChars"] > 0
    assert motion["firstPrev"] == "Last updated: 11:07"
    # A later change cross-fades (an outgoing overlay is present).
    assert motion["secondMorphing"] is True
    assert motion["secondHasOutgoing"] is True
    assert motion["secondPrev"] == "Last updated: 11:08"
    assert motion["failHasOutgoing"] is True

    reduced = report["reduced"]
    assert reduced["revealChars"] == 0
    assert reduced["morphing"] is False
    assert reduced["text"] == "Last updated: 12:00"
