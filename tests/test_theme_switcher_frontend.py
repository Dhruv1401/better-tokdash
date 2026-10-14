"""Behaviour tests for the theme switcher and the app's single theme key.

The settings dialog holds a 17-tile grid, painted from each theme's own ramp,
with one ring that slides to the selected tile. Two things are pinned here.

*Placement on open.* The grid sits inside a `<dialog>` that is hidden when the
bundle mounts, so every tile measures zero and the ring is parked until the panel
opens. The surface that reveals the grid calls `placeThemeSwitcher()` at that
moment, so the ring is already on the selected tile for the first painted frame.
A ResizeObserver delivery would need a rendering frame, and in a tab that is not
painting it never arrives.

*One owner for the theme choice.* The style (one of the 17) and the colour mode
(`dark` / `light` / `auto`) are one preference under one JSON key. The legacy
`tokdash-style-theme` pair is read once, folded in, and removed, so an existing
install keeps the exact look it had.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import tokdash

STATIC = Path(tokdash.__file__).parent / "static"
INDEX_HTML = STATIC / "index.html"
MODULES = STATIC / "js" / "animations"
SWITCHER_JS = MODULES / "theme-switcher.js"
DIALOG_JS = MODULES / "settings-dialog.js"
BARREL = MODULES / "index.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _module(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- Static contract --------------------------------------------------------

def test_ring_placement_is_called_by_the_dialog_open_path():
    """The revealer places the ring; the module owns the geometry."""
    switcher = _module(SWITCHER_JS)
    assert "export function placeThemeSwitcher()" in switcher
    assert "placeIndicator();" in switcher
    # The barrel re-exports it like every other module export.
    assert "./theme-switcher.js" in BARREL.read_text(encoding="utf-8")

    dialog = _module(DIALOG_JS)
    assert "import { placeThemeSwitcher } from './theme-switcher.js';" in dialog
    open_body = dialog.split("export function openSettingsDialog", 1)[1].split(
        "export function closeSettingsDialog", 1
    )[0]
    assert "showModal()" in open_body
    assert "placeThemeSwitcher()" in open_body
    # Placed after the modal is up, so the grid already has a box to measure.
    assert open_body.index("showModal()") < open_body.index("placeThemeSwitcher()")


def test_theme_choice_has_exactly_one_owner():
    src = _source()
    assert "const THEME_PREF_KEY = 'tokdash-theme';" in src
    assert "const LEGACY_STYLE_KEY = 'tokdash-style-theme';" in src
    # Nothing reads or writes the keys directly any more: both the format and the
    # legacy name are touched only through the helpers.
    for literal in (
        "localStorage.getItem('tokdash-theme')",
        "localStorage.setItem('tokdash-theme'",
        "localStorage.getItem('tokdash-style-theme')",
        "localStorage.setItem('tokdash-style-theme'",
    ):
        assert literal not in src, literal
    assert "localStorage.setItem(THEME_PREF_KEY, JSON.stringify(next))" in src
    assert "localStorage.removeItem(LEGACY_STYLE_KEY)" in src
    # Both writers route through the one helper, so one key carries both halves.
    assert src.count("writeThemePreference({ style: next })") == 1
    assert src.count("writeThemePreference({ mode: next })") == 2  # settings + header toggle


def test_boot_applies_the_single_key_and_migrates_the_legacy_pair():
    src = _source()
    assert "const bootTheme = readThemePreference();" in src
    assert "applyStyleTheme(bootTheme.style);" in src
    assert "applyTheme(bootTheme.mode === 'auto' ? getAutoTheme() : bootTheme.mode);" in src
    assert "if (bootTheme.migrated) writeThemePreference({});" in src
    # The two per-half default helpers are gone with the second key.
    assert "getDefaultStyleTheme" not in src
    assert "getDefaultTheme" not in src


def test_auto_mode_still_follows_the_system():
    """Absence of a stored mode used to mean auto; now `auto` is a stored value."""
    src = _source()
    assert "function themeModeIsAuto()" in src
    assert "return readThemePreference().mode === 'auto';" in src
    # Both followers — the media query and the five-minute sweep — use it.
    assert src.count("if (!themeModeIsAuto()) return;") == 2


# --- Behaviour (real module, stub DOM) -------------------------------------

_HARNESS = r"""
const MODULE_URI = process.argv[2];

function defineGlobal(name, value) {
  Object.defineProperty(globalThis, name, {
    value, writable: true, configurable: true, enumerable: false,
  });
}

function makeEl(tag) {
  const el = {
    tagName: String(tag).toUpperCase(),
    dataset: {},
    className: '',
    attributes: {},
    style: { setProperty(key, value) { this[key] = value; } },
    children: [],
    listeners: {},
    tabIndex: 0,
    textContent: '',
    offsetWidth: 0,
    offsetHeight: 0,
    offsetLeft: 0,
    offsetTop: 0,
    parentNode: null,
  };
  el.setAttribute = (k, v) => { el.attributes[k] = String(v); };
  el.getAttribute = (k) => (k in el.attributes ? el.attributes[k] : null);
  el.removeAttribute = (k) => { delete el.attributes[k]; };
  el.addEventListener = (type, fn) => { (el.listeners[type] = el.listeners[type] || []).push(fn); };
  el.removeEventListener = () => {};
  el.appendChild = (node) => { el.children.push(node); node.parentNode = el; return node; };
  el.append = (...nodes) => { nodes.forEach((node) => el.appendChild(node)); };
  el.focus = () => {};
  el.closest = () => null;
  el.querySelector = () => null;
  el.querySelectorAll = () => [];
  return el;
}

class ResizeObserverStub {
  observe() {}
  disconnect() {}
}

const html = makeEl('html');
html.classList = { contains: (name) => name === 'dark' };
defineGlobal('document', {
  documentElement: html,
  createElement: (tag) => makeEl(tag),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
});
defineGlobal('window', {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {},
  TOKDASH_THEME_CONFIG: {},
});
defineGlobal('ResizeObserver', ResizeObserverStub);
defineGlobal('getComputedStyle', () => ({ getPropertyValue: () => '' }));

const m = await import(MODULE_URI);

const root = makeEl('div');
const select = makeEl('select');
const VALUES = ['classic', 'elevated', 'paper'];
select.options = VALUES.map((value) => ({
  value, textContent: value, getAttribute: () => '',
}));
select.value = 'elevated';

const report = {};
const state = m.mountThemeSwitcher(root, { select });
report.mounted = state !== null;
report.tiles = state ? state.tiles.length : 0;

const indicator = root.children.find((child) => child.className === 'theme-switcher-indicator');
report.beforeReady = root.dataset.ready;
report.beforeWidth = indicator ? (indicator.style.width || '') : null;

// The dialog opens: the grid now has a real box, and the revealer asks for the
// ring. The checked tile is the one carrying tabIndex 0 (selection follows focus).
state.tiles.forEach((tile, index) => {
  tile.offsetWidth = 89;
  tile.offsetHeight = 64;
  tile.offsetLeft = index * 96;
  tile.offsetTop = 0;
});
const checked = state.tiles.find((tile) => tile.tabIndex === 0);
report.checkedTheme = checked ? checked.dataset.theme : null;

m.placeThemeSwitcher();
report.afterReady = root.dataset.ready;
report.width = indicator.style.width;
report.height = indicator.style.height;
report.transform = indicator.style.transform;
report.transitionAfter = indicator.style.transition;
report.expectedTransform = `translate3d(${checked.offsetLeft}px, ${checked.offsetTop}px, 0)`;
console.log(JSON.stringify(report));
"""


def _run(tmp_path: Path) -> dict:
    harness = tmp_path / "switcher.mjs"
    harness.write_text(_HARNESS, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), SWITCHER_JS.as_uri()],
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_node
def test_ring_lands_on_the_checked_tile_when_the_panel_opens(tmp_path: Path):
    report = _run(tmp_path)

    assert report["mounted"] is True and report["tiles"] == 3, report
    # Hidden panel: nothing to measure, so the ring stays parked and hidden.
    assert report["beforeReady"] == "false", report
    assert report["beforeWidth"] == "", report

    # The revealer's call places it exactly on the selected tile, silently.
    assert report["checkedTheme"] == "elevated", report
    assert report["afterReady"] == "true", report
    assert report["width"] == "89px", report
    assert report["height"] == "64px", report
    assert report["transform"] == report["expectedTransform"], report
    # The adoption suppressed the transition and then handed it back.
    assert report["transitionAfter"] == "", report
