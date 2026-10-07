"""Behaviour tests for the switch affordance.

The settings dialog's readable-tokens control is the app's real ``switch``: it
keeps ``role="switch"``, ``aria-checked``, its persistence write and its click
handler exactly where they were (``index.html`` and ``test_readable_tokens_frontend.py``
pin those). What it never had was the gesture the round thumb invites — dragging
it instead of clicking it. This module owns that gesture and nothing else: the
thumb follows the pointer within a travel the stylesheet's own numbers define,
a release past halfway was the decision (the click the platform was already
going to send does the committing, so the app's handler stays the only state
writer), a release short of halfway was a retreat and its trailing click is
stopped before it can reach a handler.

These tests drive the real module against a stub of the platform's pointer and
click piping, so the veto is observed as "the handler did / did not fire"
rather than by reading the module's own flags.
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
SWITCH_JS = STATIC / "js" / "animations" / "switch.js"
BARREL = STATIC / "js" / "animations" / "index.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# A stub platform per scenario, so the flags cannot leak between them (that
# leak is exactly what the tap-after-retreat check exists to disprove). The
# module is re-imported per scenario too, so its WeakMap state is fresh.
#
# The click walks the parent's capture listeners first — where the module's
# veto lives — and only reaches the control's bubble listeners, where the app
# handler is bound on the real page, if nothing stopped it.
_SWITCH_HARNESS = r"""
function platform(checkedAtStart) {
  const listeners = {};
  const appClick = [];
  const control = {
    tagName: 'BUTTON', dataset: {}, attrs: {},
    styleProps: {},
    style: {
      setProperty(n, v) { control.styleProps[n] = String(v); },
      removeProperty(n) { delete control.styleProps[n]; },
      getPropertyValue(n) { return control.styleProps[n] ?? ''; },
    },
    setAttribute(n, v) { control.attrs[n] = String(v); },
    getAttribute(n) { return control.attrs[n] ?? null; },
    removeAttribute(n) { delete control.attrs[n]; },
    matches(s) { return s === 'button[role="switch"]'; },
    addEventListener(t, f) { (listeners[t] ||= []).push(f); },
    querySelector() { return { getBoundingClientRect: () => ({ width: 28 }) }; },
    parentElement: { addEventListener(t, f) { (listeners['capture-click'] ||= []).push(f); } },
  };
  if (checkedAtStart) control.setAttribute('aria-checked', 'true'); else control.setAttribute('aria-checked', 'false');
  globalThis.window = { PointerEvent: function(){}, addEventListener(){}, removeEventListener(){} };
  globalThis.getComputedStyle = () => ({ getPropertyValue: n => (n === '--switch-inset' ? '2px' : '') });
  globalThis.document = { querySelectorAll: s => (s === 'button[role="switch"]' ? [control] : []) };
  return { control, listeners, appClick };
}

async function mount(checkedAtStart) {
  const plat = platform(checkedAtStart);
  const m = await import(process.argv[2]);
  const count = m.mountSwitches(globalThis.document);
  plat.mod = m; plat.count = count;
  return plat;
}

function pipeline(p, type, clientX) {
  const fns = p.listeners[type] || [];
  for (const fn of fns) {
    fn({ pointerId: 7, clientX, button: 0, target: p.control, preventDefault(){}, stopPropagation(){} });
  }
}

function click(p) {
  const ev = {
    _stopped: false, _prevented: false, target: p.control,
    preventDefault() { this._prevented = true; }, stopPropagation() { this._stopped = true; },
  };
  let vetoed = false;
  for (const fn of (p.listeners['capture-click'] || [])) {
    fn(ev);
    if (ev._stopped) { vetoed = true; break; }
  }
  if (!vetoed) {
    for (const fn of p.appClick) fn(ev);
  }
  return { vetoed, prevented: ev._prevented };
}

let appCalled = 0;
const arm = (p) => { appCalled = 0; p.appClick.push(() => { appCalled += 1; }); };
const report = {};

{
  const p = await mount(false); arm(p);
  pipeline(p, 'pointerdown', 101);
  pipeline(p, 'pointerup', 101);
  const c = click(p);
  report.tap = {
    mounted: p.count === 1, boundPointerListeners: (p.listeners['pointerdown'] || []).length > 0
      && (p.listeners['pointermove'] || []).length > 0 && (p.listeners['pointerup'] || []).length > 0,
    noClickListenerOnControl: (p.listeners['click'] || []).length === 0,
    handlerFired: appCalled === 1, parentSawClick: !c.vetoed,
    previewCleared: !p.control.style.getPropertyValue('--switch-drag-x'),
  };
}

{
  const p = await mount(false); arm(p);
  pipeline(p, 'pointerdown', 101);
  pipeline(p, 'pointermove', 102.5);
  pipeline(p, 'pointerup', 102.5);
  const c = click(p);
  report.wiggle = { handlerFired: appCalled === 1, notVetoed: !c.vetoed, previewCleared: !p.control.style.getPropertyValue('--switch-drag-x') };
}

{
  const p = await mount(false); arm(p);
  pipeline(p, 'pointerdown', 101);
  pipeline(p, 'pointermove', 112);
  const previewMid = p.control.style.getPropertyValue('--switch-drag-x');
  const datasetMid = p.control.dataset.switchDrag === 'true';
  pipeline(p, 'pointerup', 112);
  const c = click(p);
  report.dragCommit = {
    previewMid, datasetMid, handlerFiredOnce: appCalled === 1, notVetoed: !c.vetoed,
    previewCleared: !p.control.style.getPropertyValue('--switch-drag-x'),
  };
}

{
  const p = await mount(true); arm(p);
  pipeline(p, 'pointerdown', 141);
  pipeline(p, 'pointermove', 138);
  pipeline(p, 'pointerup', 138);
  const c = click(p);
  report.dragRetreat = {
    vetoed: c.vetoed, prevented: c.prevented, handlerSilent: appCalled === 0,
    previewCleared: !p.control.style.getPropertyValue('--switch-drag-x'),
    ariaUnchanged: p.control.getAttribute('aria-checked') === 'true',
  };
}

{
  const p = await mount(true); arm(p);
  pipeline(p, 'pointerdown', 141);
  pipeline(p, 'pointermove', 135);
  (p.listeners['pointercancel'] || []).forEach(fn => fn({ pointerId: 7 }));
  const c = click(p);
  report.cancel = { vetoed: c.vetoed, handlerSilent: appCalled === 0, previewCleared: !p.control.style.getPropertyValue('--switch-drag-x') };
}

{
  const p = await mount(true); arm(p);
  pipeline(p, 'pointerdown', 141);
  pipeline(p, 'pointermove', 135);
  pipeline(p, 'pointerup', 135);
  click(p);
  const afterVeto = appCalled;
  pipeline(p, 'pointerdown', 101);
  pipeline(p, 'pointerup', 101);
  click(p);
  report.tapAfterRetreat = { vetoDidItsJob: afterVeto === 0, nextTapCommits: appCalled === 1 };
}

{
  const p = await mount(false); arm(p);
  for (let i = 0; i < 3; i++) {
    pipeline(p, 'pointerdown', 101);
    pipeline(p, 'pointerup', 101);
    click(p);
  }
  report.tripleTap = { handlerFiredThrice: appCalled === 3 };
}

{
  const p = await mount(false); arm(p);
  const rearmed = p.mod.mountSwitches(globalThis.document);
  pipeline(p, 'pointerdown', 101);
  pipeline(p, 'pointerup', 101);
  click(p);
  report.remount = { stillOneGesture: rearmed === 1, noSecondPreviewChannel: (p.listeners['pointermove'] || []).length === 1, handlerFiredOnce: appCalled === 1 };
}

{
  const p = await mount(false); arm(p);
  const st = p.mod.switchState(p.control);
  report.state = {
    ready: st?.ready === true, checkedFalse: st?.checked === false,
    nullHandle: p.mod.switchState(null) === null,
  };
}

{
  // The settings dialog starts hidden: geometry only exists once it opens. The
  // listeners are bound at mount and the travel is measured per drag, so an
  // unmeasurable track leaves the click path exactly as the fallback contract
  // demands — nothing vetoed, the control still a plain working toggle.
  const listeners = {}; const appClick = [];
  globalThis.window = { PointerEvent: function(){}, addEventListener(){}, removeEventListener(){} };
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  const control = {
    tagName: 'BUTTON', dataset: {}, attrs: {},
    style: { setProperty(){}, removeProperty(){}, getPropertyValue(){ return ''; } },
    setAttribute(n, v) { control.attrs[n] = String(v); },
    getAttribute(n) { return control.attrs[n] ?? null; },
    matches(s) { return s === 'button[role="switch"]'; },
    addEventListener(t, f) { (listeners[t] ||= []).push(f); },
    querySelector() { return null; },
    parentElement: { addEventListener(t, f) { (listeners['capture-click'] ||= []).push(f); } },
  };
  control.setAttribute('aria-checked', 'false');
  globalThis.document = { querySelectorAll: s => (s === 'button[role="switch"]' ? [control] : []) };
  const m = await import(process.argv[2]);
  const mountCount = m.mountSwitches(globalThis.document);
  appClick.push(() => { appCalled += 1; });
  appCalled = 0;
  const ev = { preventDefault(){}, stopPropagation(){}, target: control };
  for (const fn of (listeners['capture-click'] || [])) fn(ev);
  for (const fn of appClick) fn(ev);
  report.unmeasurable = { mountCount, clickStillCommits: appCalled === 1 };
}

process.stdout.write(JSON.stringify(report));
"""


@needs_node
def test_switch_gesture_contract(tmp_path: Path) -> None:
    harness = tmp_path / "switch.mjs"
    harness.write_text(_SWITCH_HARNESS, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), SWITCH_JS.as_uri()],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    report = json.loads(result.stdout)

    # Mount: one gesture per control, pointer listeners on the control, the veto
    # on the parent's capture phase, and no click listener of its own — a tap
    # must pass through untouched, not through a layer this module added.
    tap = report["tap"]
    assert tap["mounted"] is True
    assert tap["boundPointerListeners"] is True
    assert tap["noClickListenerOnControl"] is True
    assert tap["handlerFired"] is True, "a tap commits through the app's own click handler"
    assert tap["parentSawClick"] is True
    assert tap["previewCleared"] is True

    # Movement inside the dead zone is still a tap.
    wiggle = report["wiggle"]
    assert wiggle["handlerFired"] is True
    assert wiggle["notVetoed"] is True
    assert wiggle["previewCleared"] is True

    # A real drag paints the thumb live and its release commits exactly once.
    commit = report["dragCommit"]
    assert commit["previewMid"].startswith("4.4"), "the thumb followed the pointer, minus the inset the drag starts from"
    assert commit["datasetMid"] is True
    assert commit["handlerFiredOnce"] is True
    assert commit["notVetoed"] is True
    assert commit["previewCleared"] is True

    # A drag withdrawn before halfway was a retreat: its trailing click is
    # stopped at the capture phase, the handler is silent, and aria-checked —
    # the app's own state — never moved.
    retreat = report["dragRetreat"]
    assert retreat["vetoed"] is True
    assert retreat["prevented"] is True
    assert retreat["handlerSilent"] is True
    assert retreat["previewCleared"] is True
    assert retreat["ariaUnchanged"] is True

    # pointercancel (a gesture the platform took back) is a retreat too.
    cancel = report["cancel"]
    assert cancel["vetoed"] is True
    assert cancel["handlerSilent"] is True
    assert cancel["previewCleared"] is True

    # One retreat gets one click stopped — the next tap the user means to land
    # commits, rather than being eaten by a stale veto.
    after = report["tapAfterRetreat"]
    assert after["vetoDidItsJob"] is True
    assert after["nextTapCommits"] is True

    assert report["tripleTap"]["handlerFiredThrice"] is True, "taps stay taps under a fast finger"

    remount = report["remount"]
    assert remount["stillOneGesture"] is True
    assert remount["noSecondPreviewChannel"] is True, "a second mount must not bind the gesture twice"
    assert remount["handlerFiredOnce"] is True

    state = report["state"]
    assert state["ready"] is True
    assert state["checkedFalse"] is True
    assert state["nullHandle"] is True

    # Without geometry the bind happens but the drag cannot start: the click
    # path is untouched and the app keeps its handler — the control is still a
    # granting toggle, which is the manual fallback for a hidden dialog.
    assert report["unmeasurable"]["mountCount"] == 1
    assert report["unmeasurable"]["clickStillCommits"] is True


def test_switch_avoids_the_real_handler_and_blends_in() -> None:
    source = _source()

    # The app's own handler and sync are untouched: the module adds the gesture,
    # the app keeps the state.
    assert "document.getElementById('readableTokensToggle')?.addEventListener('click'" in source
    assert "function syncOverviewReadableTokensToggle()" in source
    assert "aria-checked" in source

    # Wired like the rest of the bundle: exported through the barrel, mounted in
    # the animation module's init block, marked as the bundle's own.
    assert "export * from './switch.js';" in BARREL.read_text(encoding="utf-8")
    assert " Animations.mountSwitches(document);" in source
    assert "the switch stays a working click toggle" in source

    # The drag's own drawing keys off the aria-checked template the track
    # already had, so a theme repaints the same control either way.
    assert '[aria-checked="true"] .overview-readable-tokens-track::after { transform: translateX(12px); }' in source
    # The drag channel uses translate, never transform: one property for the
    # state template, one live channel for the finger.
    assert 'translate: var(--switch-drag-x, 0px) 0;' in source
    assert "transition: transform var(--t-fast) ease, translate var(--t-fast) ease;" in source
    # Reduced motion drops the slide, keeps the control.
    reduced = source[source.index("      .overview-readable-tokens-track,"):]
    reduced = reduced[: reduced.index("}") + 1]
    assert "transition: none;" in reduced
    # Travel is measured from the stylesheet's own numbers.
    assert "--switch-inset: 2px; --switch-thumb-size: 12px;" in source
    # Space, Enter and Tab are the button's own: the module binds no key events.
    switch_js = SWITCH_JS.read_text(encoding="utf-8")
    assert "addEventListener('key" not in switch_js
    assert "'keydown'" not in switch_js and "'keyup'" not in switch_js
