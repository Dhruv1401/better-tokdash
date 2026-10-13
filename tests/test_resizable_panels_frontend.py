"""Behaviour tests for the Sessions Explorer column dividers.

Sessions Explorer has no side pane to drag between: each tool is a ``<details>``
whose body stacks a KPI row *above* one wide session table, and every one of
those tables is ``table-layout: fixed`` with its widths declared in a real
``<colgroup>``. The split the markup actually carries is the column groups, so
this module is a column splitter — drag the gap between two adjacent columns and
exactly those two columns move.

These tests pin the markup/contract statically, then drive the real module in
Node against a small DOM stub. "Dragged / clamped / keyboard-resized / persisted
/ reset / reduced-motion" are observed as the columns' own inline widths and the
divider's own attributes, never as a painted effect. Persistence is exercised
across two processes so the stored split really is re-read by a module that has
never seen it before.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import tokdash

STATIC = Path(tokdash.__file__).parent / "static"
INDEX_HTML = STATIC / "index.html"
MODULE_JS = STATIC / "js" / "animations" / "resizable-panels.js"
BARREL = STATIC / "js" / "animations" / "index.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _module() -> str:
    return MODULE_JS.read_text(encoding="utf-8")


def pct(value) -> float:
    """Read a column's inline width as a number; the module writes percentages."""
    return float(str(value).rstrip("%"))


# --- Static contract --------------------------------------------------------

SESSION_PANELS = (
    "codex", "claude", "opencode", "pi_agent", "mimo", "kimi",
    "dsh", "reasonix", "zcode", "kilocode", "omp", "grok",
    "hermes", "antigravity_cli", "cline", "qoder", "workbuddy",
    "qwen_code", "openclaw", "qoder_cli", "combined",
)


def test_module_exports_the_public_api():
    assert "export function mountResizablePanels" in _module()


def test_module_is_exported_and_mounted():
    assert "./resizable-panels.js" in BARREL.read_text(encoding="utf-8")
    assert "mountResizablePanels(document)" in _source()


def test_module_has_no_global_observers():
    # The codebase pins "no MutationObserver" for the bundle; this module needs
    # none because the divider's own `left` is a percentage of the same width
    # the columns are written in.
    assert "MutationObserver" not in _module()


def test_single_column_tables_bind_nothing():
    """A one-column table must be a no-op mount, not an error."""
    assert "cols.length < 2" in _module()


def test_divider_is_hosted_by_the_table_wrapper_not_a_header_cell():
    """A <th> child is destroyed by applyI18n(); a table child shifts the row."""
    src = _module()
    assert "closest('.overflow-x-auto')" in src
    # It must never push the table around: the table keeps its own parent.
    assert "appendChild(table)" not in src


def test_column_discovery_is_scoped_to_the_tables_own_colgroup():
    """A session table nests project-group tables in its body cells, and each of
    those carries its own <colgroup>. A subtree-wide query counted seven column
    groups against one header row; only the outer pair may be read."""
    src = _module()
    assert "querySelector(':scope > colgroup')" in src
    assert "querySelector(':scope > thead')" in src
    assert "table.querySelectorAll('col')" not in src


def test_split_is_persisted_under_a_tokdash_prefixed_key():
    src = _module()
    assert "'tokdash-sessions-split'" in src


def test_each_session_table_has_at_least_two_columns():
    """The splitter needs an adjacent column pair; confirm every panel qualifies."""
    source = _source()
    for panel in SESSION_PANELS:
        segment = source.split(f'data-panel="{panel}"', 1)[1].split("</table>", 1)[0]
        cols = re.findall(r"<col ", segment)
        assert cols, f"{panel} table has no colgroup cols"
        assert len(cols) >= 2, f"{panel} has only {len(cols)} col(s)"


def test_divider_css_is_present_and_on_palette():
    css = _source()
    assert ".tokdash-col-divider" in css
    # Focus ring from the committed palette, not a grey/black-and-white default.
    assert ".tokdash-col-divider:focus-visible" in css
    assert "outline: 2px solid color-mix(in srgb, var(--color-primary)" in css
    assert "cursor: col-resize" in css
    # The grip is held still for reduced motion, and the module's own drag/keyboard
    # transitions are the ones gated at runtime.
    guard = css.index("@media (prefers-reduced-motion: reduce) {\n      .tokdash-col-divider")
    assert "transition: none" in css[guard:guard + 200]


# --- Behaviour (real module, stub DOM) -------------------------------------

_HARNESS = r"""
const MODULE_URI = process.argv[2];
const MODE = process.argv[3] || 'write';

let REDUCE = false;
const STORAGE = { data: {} };

function defineGlobal(name, value) {
  Object.defineProperty(globalThis, name, {
    value, writable: true, configurable: true, enumerable: false,
  });
}

function makeEl(tag) {
  const el = {
    tagName: String(tag).toUpperCase(),
    dataset: {},
    attributes: {},
    style: { width: '', transition: '', left: '', height: '' },
    children: [],
    textContent: '',
    listeners: {},
    tabIndex: 0,
  };
  el.setAttribute = (k, v) => { el.attributes[k] = String(v); };
  el.getAttribute = (k) => (k in el.attributes ? el.attributes[k] : null);
  el.removeAttribute = (k) => { delete el.attributes[k]; };
  el.addEventListener = (type, fn) => { (el.listeners[type] = el.listeners[type] || []).push(fn); };
  el.removeEventListener = () => {};
  el.focus = () => {};
  el.setPointerCapture = () => {};
  el.releasePointerCapture = () => {};
  el.getBoundingClientRect = () => ({ width: 0, height: 0, left: 0, right: 0, top: 0, bottom: 0 });
  el.classList = {
    set: new Set(),
    add(...names) { names.forEach((n) => this.set.add(n)); },
    contains(n) { return this.set.has(n); },
    remove(n) { this.set.delete(n); },
  };
  Object.defineProperty(el, 'className', {
    get: () => [...el.classList.set].join(' '),
    set: (v) => { el.classList.set = new Set(String(v).split(/\s+/).filter(Boolean)); },
  });
  return el;
}

defineGlobal('document', { createElement: (tag) => makeEl(tag) });
defineGlobal('window', {
  PointerEvent: function PointerEvent() {},
  matchMedia: () => ({ matches: REDUCE }),
});
defineGlobal('localStorage', {
  getItem: (k) => (k in STORAGE.data ? STORAGE.data[k] : null),
  setItem: (k, v) => { STORAGE.data[k] = String(v); },
  removeItem: (k) => { delete STORAGE.data[k]; },
});
if (MODE === 'read') STORAGE.data['tokdash-sessions-split'] = process.env.RP_STORAGE || '{}';

// `currentTarget` is what the module's handlers dispatch on; a real DOM sets it
// to the listener currently running, so the stub has to as well.
function fire(el, type, event) {
  event.currentTarget = el;
  event.target = el;
  (el.listeners[type] || []).forEach((fn) => fn(event));
}

function makeCol(pctValue) { const c = makeEl('col'); c.style.width = pctValue + '%'; return c; }
function makeTh(label) {
  const t = makeEl('th');
  t.textContent = label;
  t.getBoundingClientRect = () => ({ width: 90, height: 44, left: 0, right: 90, top: 0, bottom: 44 });
  return t;
}

const LABELS = ['Session', 'Model', 'Input', 'Cache', 'Hit %', 'Output', 'Total', 'Cost', 'Active', 'Last updated'];

function makeTable(panel, pcts, width) {
  const table = makeEl('table');
  table.dataset = { panel };
  table._cols = pcts.map(makeCol);
  table._ths = pcts.map((_, i) => makeTh(LABELS[i] || ('Col ' + i)));
  table._w = width;
  table.getBoundingClientRect = () => ({ width: table._w, height: 500, left: 0, right: table._w, top: 0, bottom: 500 });
  table._colgroup = makeEl('colgroup');
  table._colgroup.querySelectorAll = (sel) => (sel === 'col' ? table._cols : []);
  table._thead = makeEl('thead');
  table._thead.querySelectorAll = (sel) => (sel === 'th' ? table._ths : []);
  // Only the scoped queries answer; a stray nested <colgroup>/<thead> must not.
  table.querySelectorAll = (sel) => (sel === ':scope > thead th' ? table._ths : []);
  table.querySelector = (sel) => {
    if (sel === ':scope > colgroup') return table._colgroup;
    if (sel === ':scope > thead') return table._thead;
    return null;
  };
  table.closest = (sel) => (sel === '.overflow-x-auto' ? table._wrap : null);
  const wrap = makeEl('div');
  wrap.classList.add('overflow-x-auto');
  wrap.children = [table];
  wrap.appendChild = (n) => { wrap.children.push(n); return n; };
  table._wrap = wrap;
  return table;
}

const root = {
  tables: [],
  querySelectorAll(sel) {
    return sel === 'table.session-table[data-panel]' ? this.tables : [];
  },
};

const CODEX = [16, 10, 9, 9, 8, 9, 10, 8, 9, 12];
const report = { mode: MODE };

const m = await import(MODULE_URI);

function dividersOf(table) {
  return table._wrap.children.filter((c) => c.tagName === 'BUTTON');
}
function widths(table) {
  return table._cols.map((c) => c.style.width);
}
function pointer(el, type, x, id) {
  fire(el, type, { pointerId: id, pointerType: 'mouse', button: 0, clientX: x, preventDefault() {} });
}
function key(el, k) {
  fire(el, 'keydown', { key: k, preventDefault() {} });
}

if (MODE === 'write') {
  const codex = makeTable('codex', CODEX, 1000);
  root.tables = [codex];

  report.mount = m.mountResizablePanels(root);
  report.baseline = widths(codex);
  report.pairSum01 = parseFloat(report.baseline[0]) + parseFloat(report.baseline[1]);

  const d0 = dividersOf(codex)[0];
  report.divider = {
    tag: d0.tagName,
    type: d0.type,
    role: d0.getAttribute('role'),
    orientation: d0.getAttribute('aria-orientation'),
    label: d0.getAttribute('aria-label'),
    tabIndex: d0.tabIndex,
    id: d0.id,
    className: d0.className,
    valuenow: d0.getAttribute('aria-valuenow'),
    valuemin: d0.getAttribute('aria-valuemin'),
    valuemax: d0.getAttribute('aria-valuemax'),
    left: d0.style.left,
    height: d0.style.height,
    wrappingClass: codex._wrap.className,
  };

  // Real pointer drag: +26px across a 260px pair (26% of a 1000px table).
  pointer(d0, 'pointerdown', 200, 7);
  report.dragTransition = codex._cols[0].style.transition;
  report.draggingFlag = d0.dataset.dragging;
  pointer(d0, 'pointermove', 226, 7);
  report.afterMove = widths(codex);
  report.afterMoveSum = parseFloat(report.afterMove[0]) + parseFloat(report.afterMove[1]);
  report.afterMoveLeft = d0.style.left;
  report.afterMoveValuenow = d0.getAttribute('aria-valuenow');
  pointer(d0, 'pointerup', 226, 7);
  report.afterUpTransition = codex._cols[0].style.transition;
  report.draggingFlagUp = d0.dataset.dragging;
  report.storageAfterDrag = STORAGE.data['tokdash-sessions-split'];

  // The pair total is conserved, so every neighbour keeps its declared width.
  report.neighbours = widths(codex).slice(2);
  report.declaredNeighbours = CODEX.slice(2).map((v) => v + '%');

  // Keyboard: ArrowRight widens the left column by the key step.
  key(d0, 'ArrowRight');
  report.afterArrow = widths(codex);
  report.afterArrowLeft = d0.style.left;
  report.afterArrowTransition = codex._cols[0].style.transition;
  report.afterArrowValuenow = d0.getAttribute('aria-valuenow');

  key(d0, 'Home');
  report.afterHome = widths(codex);
  report.afterHomeValuenow = d0.getAttribute('aria-valuenow');
  key(d0, 'End');
  report.afterEnd = widths(codex);
  report.afterEndValuenow = d0.getAttribute('aria-valuenow');
  report.bounds = {
    min: d0.getAttribute('aria-valuemin'),
    max: d0.getAttribute('aria-valuemax'),
  };

  // Reduced motion: the keyboard step must not queue a transition.
  REDUCE = true;
  key(d0, 'ArrowLeft');
  report.reducedTransition = codex._cols[0].style.transition;
  report.reducedWidth = codex._cols[0].style.width;
  REDUCE = false;
  key(d0, 'ArrowRight');
  report.motionTransition = codex._cols[0].style.transition;

  // Double-click puts the declared widths back and forgets the split.
  fire(d0, 'dblclick', { preventDefault() {} });
  report.afterReset = widths(codex).slice(0, 2);
  report.storageAfterReset = STORAGE.data['tokdash-sessions-split'];
  report.resetLeft = d0.style.left;

  // Drag once more so the reload process has a real stored split to read back.
  pointer(d0, 'pointerdown', 200, 9);
  pointer(d0, 'pointermove', 226, 9);
  pointer(d0, 'pointerup', 226, 9);
  report.storageFinal = STORAGE.data['tokdash-sessions-split'];

  // Mount is idempotent: a second pass claims nothing and duplicates nothing.
  report.remount = m.mountResizablePanels(root);
  report.dividerCount = dividersOf(codex).length;
} else {
  const codex = makeTable('codex', CODEX, 1000);
  root.tables = [codex];
  report.mount = m.mountResizablePanels(root);
  const d0 = dividersOf(codex)[0];
  report.storedWidths = widths(codex).slice(0, 2);
  report.storedLeft = d0.style.left;
  report.storedValuenow = d0.getAttribute('aria-valuenow');
  report.storedKeySeen = Object.keys(JSON.parse(STORAGE.data['tokdash-sessions-split'] || '{}'));
}

console.log(JSON.stringify(report));
"""


def _run(tmp_path: Path, mode: str, storage: str | None = None) -> dict:
    harness = tmp_path / "panels.mjs"
    harness.write_text(_HARNESS, encoding="utf-8")
    env = dict(os.environ)
    if storage is not None:
        env["RP_STORAGE"] = storage
    result = subprocess.run(
        ["node", str(harness), MODULE_JS.as_uri(), mode],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_node
def test_divider_drag_keyboard_reset_and_clamp(tmp_path: Path):
    report = _run(tmp_path, "write")

    # Ten columns give nine adjacent pairs, hence nine dividers.
    assert report["mount"] == 9, report
    assert report["baseline"] == ["16%", "10%", "9%", "9%", "8%", "9%", "10%", "8%", "9%", "12%"]
    assert report["pairSum01"] == pytest.approx(26.0)

    divider = report["divider"]
    assert divider["tag"] == "BUTTON"
    assert divider["type"] == "button"
    assert divider["role"] == "separator"
    assert divider["orientation"] == "vertical"
    assert divider["tabIndex"] == 0
    assert divider["className"] == "tokdash-col-divider"
    assert divider["id"] == "tokdash-col-divider-codex-c0"
    assert "Session" in divider["label"] and "Model" in divider["label"], divider["label"]
    # Initially parked exactly on the boundary it controls (16% of the table).
    assert divider["left"] == "16%"
    assert divider["height"] == "44px"
    assert divider["valuemin"] == "56"
    # The wrapper is claimed so the divider becomes its positioning context.
    assert "tokdash-col-wrap" in divider["wrappingClass"]

    # Drag +26px across a 260px pair -> left column 16% -> 18.6%.
    assert report["dragTransition"] == "none"
    assert report["draggingFlag"] == "true"
    after = report["afterMove"]
    assert pct(after[0]) == pytest.approx(18.6, abs=0.01)
    assert pct(after[1]) == pytest.approx(7.4, abs=0.01)
    assert report["afterMoveSum"] == pytest.approx(26.0, abs=0.01)
    assert report["afterMoveLeft"] == "18.6%"
    assert report["afterMoveValuenow"] == "186"
    assert report["afterUpTransition"] == ""
    assert report["draggingFlagUp"] == "false"

    # Nothing beside the divider moved by a pixel.
    assert report["neighbours"] == report["declaredNeighbours"]

    # The split was written to the tokdash-prefixed key.
    stored = json.loads(report["storageAfterDrag"])
    assert stored["sessions-split:codex:col:0-1"] == pytest.approx(18.6 / 26, abs=1e-3)

    # Keyboard steps move the same pair and carry the committed-token transition.
    assert pct(report["afterArrow"][0]) == pytest.approx(19.8, abs=0.05)
    assert report["afterArrowLeft"] == "19.8%"
    assert "var(--t-med)" in report["afterArrowTransition"]
    assert report["afterArrowValuenow"] == "198"

    # Min/max clamp holds at both ends of the track.
    assert report["afterHomeValuenow"] == "56"
    assert pct(report["afterHome"][0]) == pytest.approx(5.6, abs=0.01)
    assert pct(report["afterHome"][1]) == pytest.approx(20.4, abs=0.01)
    assert report["afterEndValuenow"] == "204"
    assert pct(report["afterEnd"][0]) == pytest.approx(20.4, abs=0.01)
    assert pct(report["afterEnd"][1]) == pytest.approx(5.6, abs=0.01)
    assert report["bounds"]["min"] == "56"
    assert report["bounds"]["max"] == "204"  # MIN_PX off the far side of a 260px pair

    # Reduced motion swaps instantly; motion-on uses the committed token.
    assert report["reducedTransition"] == "none"
    assert report["reducedWidth"] != report["afterEnd"][0]
    assert "var(--t-med)" in report["motionTransition"]

    # Double-click puts the declared widths back and forgets the split.
    assert report["afterReset"] == ["16%", "10%"]
    assert report["resetLeft"] == "16%"
    assert json.loads(report["storageAfterReset"]) == {}

    # A second mount claims nothing new and duplicates no divider.
    assert report["remount"] == 0
    assert report["dividerCount"] == 9


@needs_node
def test_stored_split_survives_a_reload(tmp_path: Path):
    """Two processes: the second never saw the drag, only the storage it left."""
    written = _run(tmp_path, "write")
    storage = written["storageFinal"]
    assert json.loads(storage), "the drag must have persisted a split"

    reloaded = _run(tmp_path, "read", storage=storage)
    assert reloaded["mount"] == 9, reloaded
    assert "sessions-split:codex:col:0-1" in reloaded["storedKeySeen"]
    # 0.7154 of a 26% pair -> the same split the drag ended on.
    assert pct(reloaded["storedWidths"][0]) == pytest.approx(18.6, abs=0.05)
    assert pct(reloaded["storedWidths"][1]) == pytest.approx(7.4, abs=0.05)
    assert pct(reloaded["storedLeft"]) == pytest.approx(18.6, abs=0.05)
    assert reloaded["storedValuenow"] is not None
