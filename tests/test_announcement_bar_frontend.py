"""Behaviour tests for the top-of-surface announcement bar.

The dashboard already owns a real update signal: the update-check calls
``renderUpdateBadge(info)`` with ``update_available`` true and a version, and the
settings panel paints its own buried badge. The announcement bar promotes that
one signal to the top of the app surface — it wraps the app's *own*
``renderUpdateBadge`` (the exact function the network check invokes) and, only
for a genuine arrival, reveals an inline bar carrying the very message the
settings badge just painted. It invents nothing: without an update the slot
stays collapsed and the layout is identical.

These tests pin the markup/contract statically and then drive the real module
in Node against a stub of the DOM and the app's signal, so "the bar appeared /
did not appear" is observed as the slot's state and the live text, not by
reading the module's own bookkeeping.
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
MODULE_JS = STATIC / "js" / "animations" / "announcement-bar.js"
BARREL = STATIC / "js" / "animations" / "index.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _module() -> str:
    return MODULE_JS.read_text(encoding="utf-8")


# --- Static contract --------------------------------------------------------


def test_bar_slot_is_present_at_top_of_app_surface():
    html = _source()
    # The slot sits inside the max-width container, above the top-bar header.
    container = html.index('class="w-full max-w-[1680px] p-4 sm:p-6 lg:p-8 space-y-6"')
    slot = html.index('id="announcementBar"')
    topbar = html.index("<!-- Top bar -->", container)
    assert container < slot < topbar, "the bar belongs above the top bar"


def test_bar_slot_markup_contract():
    html = _source()
    assert 'class="announcement-slot" data-state="empty"' in html
    assert 'class="announcement-bar" role="status" aria-live="polite" aria-atomic="true"' in html
    assert 'class="announcement-text"' in html
    assert 'class="announcement-action"' in html
    assert 'class="announcement-close"' in html
    # The dismiss control must not reach for focus on reveal.
    assert "autofocus" not in html[html.index('id="announcementBar"'):html.index("<!-- Top bar -->")]


def test_bar_uses_shared_tokens_and_reduced_motion():
    css = _source()
    assert ".announcement-slot" in css
    slotblk = css[css.index(".announcement-slot {"):css.index(".announcement-bar {")]
    assert "height: 0" in slotblk, "empty slot must take no height"
    assert "overflow: hidden" in slotblk, "the slot clips the card as it animates"
    assert "transition: height var(--t-med)" in slotblk, "reveal rides the committed motion token"
    # The slot is a bare clip box; the card carries every bit of paint.
    barblk = css[css.index(".announcement-bar {"):css.index(".announcement-card {")]
    assert "overflow: hidden" in barblk and "min-height: 0" in barblk
    assert "padding" not in barblk, "padding on the clip box would prevent collapse"
    cardblk = css[css.index(".announcement-card {"):css.index(".announcement-mark {")]
    assert "--color-surface-glass" in cardblk
    assert "var(--radius-lg)" in cardblk
    assert "color-mix(in srgb, var(--color-primary)" in cardblk, "palette accent, never gray-only"
    # Reduced-motion guard holds the slot and the card still.
    guard = css.index("@media (prefers-reduced-motion: reduce) {\n      .announcement-slot,")
    assert ".announcement-card { transition: none; }" in css[guard:guard + 220]


def test_bar_is_exported_and_mounted():
    html = _source()
    assert "mountAnnouncementBar(document)" in html
    barrel = BARREL.read_text(encoding="utf-8")
    assert "./announcement-bar.js" in barrel


def test_module_exports_the_public_api():
    src = _module()
    for name in ("mountAnnouncementBar", "announceUpdate", "hideAnnouncement", "announcementState"):
        assert f"export function {name}" in src, name


def test_module_wraps_the_real_signal():
    src = _module()
    assert "window.renderUpdateBadge = wrapper" in src
    assert "original.__tokdashAnnouncement" in src


def test_i18n_keys_exist_for_every_language():
    html = _source()
    assert html.count("announcementDetails:") == 6
    assert html.count("announcementDismiss:") == 6


# --- Behaviour (real module, stub DOM) -------------------------------------

_ANNOUNCE_HARNESS = r"""
function el() {
  const listeners = {};
  return {
    dataset: {}, textContent: '', attrs: {}, hidden: false, focusCalls: 0,
    style: { setProperty(){}, removeProperty(){}, getPropertyValue(){ return ''; } },
    addEventListener(t, f) { (listeners[t] ||= []).push(f); },
    setAttribute(n, v) { this.attrs[n] = String(v); },
    getAttribute(n) { return this.attrs[n] ?? null; },
    removeAttribute(n) { delete this.attrs[n]; },
    focus() { this.focusCalls += 1; },
    click() { (listeners['click'] || []).forEach(f => f({})); },
    fire(t, ev) { (listeners[t] || []).forEach(f => f(ev)); },
  };
}

const text = el();
const action = el();
const close = el();
const slot = el();
slot.querySelector = (sel) =>
  sel === '.announcement-text' ? text
  : sel === '.announcement-action' ? action
  : sel === '.announcement-close' ? close
  : null;

const badge = el();
const releaseToggle = el();

globalThis.document = {
  getElementById(id) {
    if (id === 'announcementBar') return slot;
    if (id === 'updateBadge') return badge;
    if (id === 'releaseNotesToggle') return releaseToggle;
    return null;
  },
};

let originalCalls = 0;
globalThis.window = {
  renderUpdateBadge: function (info) {
    originalCalls += 1;
    // The real badge paints localized text; simulate that the app did its work.
    badge.textContent = (info && info.update_available && info.latest)
      ? `Update available: v${info.latest}` : '';
  },
  t: (k) => 't:' + k,
};

const store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};

const m = await import(process.argv[2]);
const mounted = m.mountAnnouncementBar(globalThis.document);

// Drive the app's OWN signal (now wrapped) exactly as the network check would.
function drive(info) { globalThis.window.renderUpdateBadge(info); }

const report = {};

// 1. A genuine arrival reveals the bar with the badge's real message.
drive({ update_available: true, latest: '9.9.9' });
report.appeared = {
  mounted: mounted != null,
  originalRan: originalCalls === 1,
  shown: slot.dataset.state === 'shown',
  message: text.textContent,
};

// 2. The reveal steals no focus.
report.noFocusSteal = close.focusCalls === 0 && action.focusCalls === 0;

// 3. Dismiss collapses the bar and remembers the version.
close.fire('click', {});
report.dismissed = {
  hidden: slot.dataset.state === 'empty',
  cleared: text.textContent === '',
  remembered: store['tokdash-announcement-dismissed'] === '9.9.9',
};

// 4. The same arrival does not nag again after a dismiss.
drive({ update_available: true, latest: '9.9.9' });
report.staysDismissed = slot.dataset.state === 'empty';

// 5. A NEW version does surface again.
drive({ update_available: true, latest: '9.9.10' });
report.newVersionShows = slot.dataset.state === 'shown' && text.textContent.includes('9.9.10');
close.fire('click', {});

// 6. No update => no bar, and the settings badge path is untouched.
drive({ update_available: false });
report.noUpdateStaysHidden = slot.dataset.state === 'empty' && originalCalls === 4;

// 7. programmatic state read reflects reality.
report.state = m.announcementState();
report.hideResult = m.hideAnnouncement();

console.log(JSON.stringify(report));
"""


@needs_node
def test_announcement_bar_behaviour(tmp_path: Path):
    harness = tmp_path / "announce.mjs"
    harness.write_text(_ANNOUNCE_HARNESS, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), MODULE_JS.as_uri()],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])

    assert report["appeared"]["mounted"] is True
    assert report["appeared"]["originalRan"] is True
    assert report["appeared"]["shown"] is True
    assert report["appeared"]["message"] == "Update available: v9.9.9"

    assert report["noFocusSteal"] is True

    assert report["dismissed"]["hidden"] is True
    assert report["dismissed"]["cleared"] is True
    assert report["dismissed"]["remembered"] is True

    assert report["staysDismissed"] is True
    assert report["newVersionShows"] is True
    assert report["noUpdateStaysHidden"] is True
    assert report["state"]["mounted"] is True
    assert report["hideResult"] is False  # already hidden at that point
