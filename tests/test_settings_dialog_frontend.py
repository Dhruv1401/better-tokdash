"""Behaviour tests for the settings dialog.

The panel behind the settings trigger is a real ``<dialog>``: the platform owns
the modality (the rest of the document is inert, focus cannot leave, Escape
closes) and the animation bundle owns what the element cannot do alone — putting
focus inside on the way in, remembering which of the two settings triggers opened
it, handing focus back to that one, and holding the page still while it is up.

These tests drive the real module against a stub DOM, so the focus hand-off and
the scroll hold are checked as behaviour rather than as source text.
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
DIALOG_JS = STATIC / "js" / "animations" / "settings-dialog.js"
LANGUAGES = ("en", "zh", "ja", "ko", "es", "pt")

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# A DOM stub with only what the dialog module touches: a dialog element that can
# be shown and closed and that reports its own `close` event, an opener per
# settings trigger, a document element with a class list and a style object, and a
# viewport whose inner width is six pixels wider than the layout width — which is
# what a scrollbar is worth here, and what the scroll hold has to give back.
_DIALOG_DOM = r"""
let doc = null;

function makeEl(tag) {
  const el = {
    tagName: tag.toUpperCase(),
    id: '',
    attrs: {},
    dataset: {},
    hidden: false,
    open: false,
    isConnected: true,
    children: [],
    listeners: {},
    showCount: 0,
    closeCount: 0,
    focusCount: 0,
    style: {
      props: {},
      setProperty(name, value) { this.props[name] = value; },
      removeProperty(name) { delete this.props[name]; },
    },
    _classes: new Set(),
    setAttribute(name, value) {
      this.attrs[name] = String(value);
      if (name === 'hidden') this.hidden = true;
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
    },
    removeAttribute(name) {
      delete this.attrs[name];
      if (name === 'hidden') this.hidden = false;
    },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    focus() { this.focusCount += 1; doc.activeElement = this; },
    contains(node) { return node === this || this.children.includes(node); },
    appendChild(child) { this.children.push(child); child.parentElement = this; return child; },
    showModal() { this.showCount += 1; this.open = true; },
    close() {
      if (!this.open) return;
      this.closeCount += 1;
      this.open = false;
      (this.listeners['close'] || []).forEach((fn) => fn());
    },
  };
  el.classList = {
    add: (name) => el._classes.add(name),
    remove: (name) => el._classes.delete(name),
    contains: (name) => el._classes.has(name),
  };
  el.ownerDocument = doc;
  return el;
}

doc = {
  activeElement: null,
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
  removeEventListener() {},
  getElementById() { return null; },
};
doc.body = makeEl('body');
doc.body.id = 'body';
doc.documentElement = makeEl('html');
// 1440 of viewport over a 1434.4 layout: the scrollbar the lock takes away,
// as a fraction, because that is what the platform really reports.
doc.documentElement.clientWidth = 1434;
doc.documentElement.getBoundingClientRect = () => ({ width: 1434.4, height: 900 });
const EXPECTED_GUTTER = `${1440 - 1434.4}px`;
doc.activeElement = doc.body;
globalThis.document = doc;
globalThis.window = { innerWidth: 1440, innerHeight: 900, addEventListener() {}, removeEventListener() {} };

const {
  mountSettingsDialog,
  openSettingsDialog,
  closeSettingsDialog,
  settingsDialogState,
  unmountSettingsDialog,
} = await import(process.argv[2]);

const report = {};
const closes = [];

// A backdrop that cannot show a modal dialog is left to the app's own path.
report.unsupported = mountSettingsDialog({ querySelector: () => null }, makeEl('section'));

const backdrop = makeEl('dialog');
backdrop.id = 'settingsBackdrop';
backdrop.setAttribute('aria-labelledby', 'settingsPanelTitle');
backdrop.setAttribute('hidden', '');
const panel = makeEl('section');
panel.id = 'settingsPanel';
backdrop.appendChild(panel);

const mobileTrigger = makeEl('button');
mobileTrigger.id = 'mobileSettingsBtn';
const sidebarTrigger = makeEl('button');
sidebarTrigger.id = 'sidebarSettingsBtn';

report.mounted = mountSettingsDialog(backdrop, panel, { onClose: () => closes.push('close') });
report.remounted = mountSettingsDialog(backdrop, panel);
report.panelTabindex = panel.getAttribute('tabindex');
report.closedState = settingsDialogState();

// Opening from the phone-width mirror: that is the button the focus must return
// to, not the desktop one that is display:none at that width.
report.opened = openSettingsDialog({ opener: mobileTrigger });
report.afterOpen = {
  showCount: backdrop.showCount,
  hidden: backdrop.getAttribute('hidden'),
  panelFocused: doc.activeElement === panel,
  openerExpanded: mobileTrigger.getAttribute('aria-expanded'),
  sidebarExpanded: sidebarTrigger.getAttribute('aria-expanded'),
  scrollLocked: doc.documentElement.classList.contains('settings-dialog-open'),
  gutter: doc.documentElement.style.props['--settings-dialog-gutter'],
  expectedGutter: EXPECTED_GUTTER,
  open: settingsDialogState().open,
  stateOpener: settingsDialogState().opener,
  focusInPanel: settingsDialogState().focusInPanel,
  labelled: settingsDialogState().labelled,
};

// Opening again while it is up must not measure a gutter that is already gone,
// or the page would reflow inward by six pixels on the second open.
openSettingsDialog({ opener: mobileTrigger });
report.gutterAfterSecondOpen = doc.documentElement.style.props['--settings-dialog-gutter'];
report.showCountAfterSecondOpen = backdrop.showCount;

report.closed = closeSettingsDialog({ restoreFocus: true });
report.afterClose = {
  open: backdrop.open,
  closeCount: backdrop.closeCount,
  hidden: backdrop.getAttribute('hidden'),
  openerExpanded: mobileTrigger.getAttribute('aria-expanded'),
  focusOnOpener: doc.activeElement === mobileTrigger,
  focusOnSidebar: doc.activeElement === sidebarTrigger,
  scrollLocked: doc.documentElement.classList.contains('settings-dialog-open'),
  gutterCleared: !Object.prototype.hasOwnProperty.call(doc.documentElement.style.props, '--settings-dialog-gutter'),
  closes: closes.length,
};

// Reopening works, and this time the platform closes it on its own (Escape) —
// the app is never told, so the panel has to settle itself.
openSettingsDialog({ opener: sidebarTrigger });
doc.activeElement = panel;
backdrop.open = false;
(backdrop.listeners['close'] || []).forEach((fn) => fn());
report.platformClose = {
  openerExpanded: sidebarTrigger.getAttribute('aria-expanded'),
  focusOnOpener: doc.activeElement === sidebarTrigger,
  scrollLocked: doc.documentElement.classList.contains('settings-dialog-open'),
  open: settingsDialogState().open,
  closes: closes.length,
};

// ...and a second report for the same close must not hand focus over again.
doc.activeElement = mobileTrigger;
(backdrop.listeners['close'] || []).forEach((fn) => fn());
report.doubleReport = { focusUntouched: doc.activeElement === mobileTrigger, closes: closes.length };

// A close that asks for no focus leaves it where the user put it.
openSettingsDialog({ opener: sidebarTrigger });
doc.activeElement = panel;
closeSettingsDialog({ restoreFocus: false });
report.noRestore = { focusStillInPanel: doc.activeElement === panel, openerExpanded: sidebarTrigger.getAttribute('aria-expanded') };

// Shown without an opener, the control that had focus is the one it goes back to.
sidebarTrigger.focus();
openSettingsDialog();
report.fromActiveElement = settingsDialogState().opener;

report.unmounted = unmountSettingsDialog();
report.afterUnmount = {
  state: settingsDialogState(),
  scrollLocked: doc.documentElement.classList.contains('settings-dialog-open'),
  gutterCleared: !Object.prototype.hasOwnProperty.call(doc.documentElement.style.props, '--settings-dialog-gutter'),
};

process.stdout.write(JSON.stringify(report));
"""


@needs_node
def test_settings_dialog_focus_and_scroll_contract(tmp_path: Path) -> None:
    harness = tmp_path / "dialog.mjs"
    harness.write_text(_DIALOG_DOM, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), DIALOG_JS.as_uri()],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    report = json.loads(result.stdout)

    # One mount per dialog, and a backdrop the platform cannot show modally is
    # left alone so the app's own path stays in charge.
    assert report["unsupported"] == 0
    assert report["mounted"] == 1
    assert report["remounted"] == 1
    assert report["panelTabindex"] == "-1", "the panel is the focus target on the way in"
    assert report["closedState"]["open"] is False
    assert report["closedState"]["labelled"] == "settingsPanelTitle"

    # Opening puts focus inside the panel, tells the button that opened it, and
    # holds the page still — with the scrollbar's six pixels given back.
    opened = report["afterOpen"]
    assert opened["showCount"] == 1
    assert opened["hidden"] is None, "the hidden attribute is the fallback, not the open state"
    assert opened["open"] is True
    assert opened["labelled"] == "settingsPanelTitle"
    assert opened["panelFocused"] is True
    assert opened["focusInPanel"] is True
    assert opened["openerExpanded"] == "true"
    assert opened["sidebarExpanded"] is None, "only the trigger that opened it is updated"
    assert opened["stateOpener"] == "mobileSettingsBtn"
    assert opened["scrollLocked"] is True
    # The gutter is the scrollbar's real width, to the fraction: the integer
    # difference would leave the topbar 0.4px narrower under the lock.
    assert opened["gutter"] == opened["expectedGutter"]
    assert opened["gutter"].startswith("5.5")
    assert report["gutterAfterSecondOpen"] == opened["expectedGutter"], (
        "a second open must not re-measure a gutter that is already gone"
    )
    assert report["showCountAfterSecondOpen"] == 1, "showModal() twice is an invalid state"

    # Closing hands focus back to the button that opened it — the phone-width
    # mirror here, which is the one the user pressed — and lets the page move again.
    closed = report["afterClose"]
    assert closed["open"] is False
    assert closed["closeCount"] == 1
    assert closed["hidden"] == ""
    assert closed["openerExpanded"] == "false"
    assert closed["focusOnOpener"] is True
    assert closed["focusOnSidebar"] is False, "the desktop trigger is not where the focus came from"
    assert closed["scrollLocked"] is False
    assert closed["gutterCleared"] is True
    assert closed["closes"] == 1

    # Escape closes the dialog without the app: the panel still settles, hands
    # focus back, and reports the close exactly once.
    platform = report["platformClose"]
    assert platform["open"] is False
    assert platform["openerExpanded"] == "false"
    assert platform["focusOnOpener"] is True
    assert platform["scrollLocked"] is False
    assert platform["closes"] == 2
    assert report["doubleReport"]["focusUntouched"] is True
    assert report["doubleReport"]["closes"] == 2, "one close is one report"

    # Closing on purpose is not the only way out: a close that does not ask for
    # the focus must not take it.
    assert report["noRestore"]["focusStillInPanel"] is True
    assert report["noRestore"]["openerExpanded"] == "false"

    # Shown without a named opener, the control that had focus is the one that
    # gets it back.
    assert report["fromActiveElement"] == "sidebarSettingsBtn"

    # Unmounting releases everything it was holding.
    assert report["unmounted"] is None
    assert report["afterUnmount"]["state"] is None
    assert report["afterUnmount"]["scrollLocked"] is False
    assert report["afterUnmount"]["gutterCleared"] is True


def test_settings_dialog_is_a_real_modal_element() -> None:
    source = _source()
    backdrop_start = source.index('id="settingsBackdrop"')
    backdrop = source[backdrop_start - 200 : backdrop_start + 400]

    # The scrim is the dialog, so the modality the markup claims is the platform's.
    assert "<dialog id=\"settingsBackdrop\"" in source
    assert "<div id=\"settingsBackdrop\"" not in source
    assert 'aria-labelledby="settingsPanelTitle"' in backdrop
    assert "aria-modal" in backdrop
    # One label, one dialog: the panel inside is grouped content, not a second one.
    panel_start = source.index('id="settingsPanel"')
    panel_tag = source[source.rindex("<", 0, panel_start) : source.index(">", panel_start) + 1]
    assert panel_tag.startswith("<section"), panel_tag
    assert 'aria-labelledby="settingsPanelTitle"' not in panel_tag
    assert 'role="dialog"' not in panel_tag
    assert 'tabindex="-1"' in panel_tag

    # Both triggers point at the panel they open, and both publish their state.
    for trigger_id in ("sidebarSettingsBtn", "mobileSettingsBtn"):
        tag = source[source.index(f'id="{trigger_id}"') - 200 : source.index(f'id="{trigger_id}"') + 300]
        assert 'aria-controls="settingsPanel"' in tag, trigger_id
        assert 'aria-expanded="false"' in tag, trigger_id

    # The app's own path opens it modally, and delegates once the bundle is in.
    assert "showModal()" in source
    assert "backdrop.showModal" in source
    assert "typeof backdrop.close === 'function' && backdrop.open" in source
    assert "animations.openSettingsDialog({ opener: settingsDialogOpener(panel) })" in source
    assert "animations.closeSettingsDialog({ restoreFocus: returnFocus })" in source
    assert "panel.dataset.dialogMode = 'module'" in source
    assert "window.tokdashInitSettingsDialog = initSettingsDialog;" in source
    assert "window.tokdashInitSettingsDialog()" in source, "the bundle has to mount it"

    # A click that came without keyboard focus cannot name its opener, so the
    # fallback answers by layout width — the app's own breakpoint, below which the
    # mirror is the only settings trigger in the document that can take focus back.
    opener_fn = source[source.index("function settingsDialogOpener(") :]
    opener_fn = opener_fn[: opener_fn.index("return window.innerWidth < 768")]
    assert "window.innerWidth < 768" in opener_fn
    assert "getElementById('mobileSettingsBtn')" in opener_fn
    assert "getElementById('sidebarSettingsBtn')" in opener_fn

    # The close control is icon-only, so it carries a translated name and hint.
    assert "data-dialog-close" in source
    assert 'data-i18n-title="closeSettings"' in source
    assert "settingsDialogClose.setAttribute('aria-label', t('closeSettings'))" in source


def test_settings_dialog_css_answers_for_the_platform_and_blends_in() -> None:
    css = _source()[: _source().index("</style>")]
    start = css.index("    .app-modal-backdrop {")
    block = css[start : css.index(".app-modal-box")]

    # A modal dialog gets a UA cap and its own scroller; both would pull the scrim
    # off the window's edges, and an author `display: flex` would keep a closed
    # dialog on screen without the explicit guard.
    for declaration in (
        "position: fixed;",
        "inset: 0;",
        "max-width: none;",
        "max-height: none;",
        "margin: 0;",
        "overflow: hidden;",
        "border: 0;",
        "display: flex;",
        "align-items: center;",
        "justify-content: center;",
    ):
        assert declaration in block, declaration
    assert ".app-modal-backdrop:not([open])" in block
    assert ".app-modal-backdrop[hidden] { display: none; }" in block

    # The scrim keeps the theme's colour under its blur rather than flat black,
    # and the two halves come in on the committed motion tokens.
    assert "var(--shadow-md)" not in block
    assert "color-mix(in srgb, #0F172A 68%, transparent)" in block
    assert "backdrop-filter: blur(8px);" in block
    assert "animation: settings-dialog-scrim-in var(--t-fast) ease;" in block
    assert "animation: settings-dialog-panel-in var(--t-med) cubic-bezier(0.16, 1, 0.3, 1);" in block
    assert "translate: 0 8px;" in block, "the panel rises; it never animates transform"
    assert "transform" not in block.split("@keyframes settings-dialog-panel-in")[1]

    # The page cannot move behind it, and the gutter it gives up is put back.
    assert "html.settings-dialog-open { overflow: hidden; }" in css
    assert "html.settings-dialog-open body { padding-right: var(--settings-dialog-gutter, 0px); }" in css

    # Reduced motion keeps the dialog, drops the entrance.
    reduced = css[css.index("    @media (prefers-reduced-motion: reduce) {\n      .app-modal-backdrop[open]"):]
    reduced = reduced[: reduced.index("}") + 1]
    assert "animation: none;" in reduced

    # The panel itself keeps the committed surface instead of inventing one.
    panel_css = css[css.index("    .settings-panel {"): css.index("    .settings-panel-close {")]
    assert "border-radius: 16px;" in panel_css
    assert "var(--color-surface-glass, var(--color-bg))" in panel_css
    assert "var(--color-border)" in panel_css
    assert "position: static;" in panel_css


def test_settings_dialog_labels_are_translated_everywhere() -> None:
    source = _source()
    for lang in LANGUAGES:
        block = source[source.index(f"      {lang}: {{") :]
        block = block[: block.index("\n      },") if "\n      }," in block else 40000]
        assert "closeSettings:" in block, f"{lang} is missing closeSettings"
    assert DIALOG_JS.read_text(encoding="utf-8").count("export function") >= 5
