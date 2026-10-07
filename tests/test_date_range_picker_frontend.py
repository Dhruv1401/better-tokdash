"""Behaviour tests for the rail's date range picker.

The calendar is the app's own module (static/js/animations/date-range-picker.js):
it draws the grid, moves a roving tab stop through it, and hands every selected
window to the app's single commit path. These tests drive the real module
against a stub DOM, so the grid maths, the selection rules and the popover
hand-off are checked as behaviour rather than as source text.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

import tokdash

STATIC = Path(tokdash.__file__).parent / "static"
INDEX_HTML = STATIC / "index.html"
PICKER_JS = STATIC / "js" / "animations" / "date-range-picker.js"
LANGUAGES = ("en", "zh", "ja", "ko", "es", "pt")

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# A DOM stub with only what the picker and the popover primitive touch: element
# attributes, dataset, listeners, the day grid's innerHTML setter (which is how
# the module publishes its buttons), and a document that records the capture
# listeners the popover binds so Escape can be driven for real.
_PICKER_DOM = r"""
const listeners = {};
let doc = null;

function makeEl(tag) {
  const el = {
    tagName: tag,
    attrs: {},
    dataset: {},
    children: [],
    hidden: false,
    tabIndex: 0,
    offsetWidth: 300,
    offsetHeight: 330,
    offsetParent: {},
    textContent: '',
    style: {},
    listeners: {},
    setAttribute(name, value) { this.attrs[name] = String(value); },
    getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; },
    removeAttribute(name) { delete this.attrs[name]; },
    hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    removeEventListener() {},
    dispatch(type, event = {}) { (this.listeners[type] || []).forEach((fn) => fn(event)); },
    appendChild(child) { this.children.push(child); child.parentElement = this; return child; },
    remove() {},
    contains(node) { return node === this || this.children.includes(node); },
    focus() { doc.activeElement = this; },
    getBoundingClientRect() { return { x: 0, y: 0, top: 0, left: 0, right: 300, bottom: 40, width: 300, height: 40 }; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
  };
  el.ownerDocument = doc;
  return el;
}

doc = {
  activeElement: null,
  createElement: () => makeEl('div'),
  addEventListener(type, fn) { (listeners['doc:' + type] ||= []).push(fn); },
  removeEventListener() {},
  getElementById: () => null,
};
doc.body = makeEl('body');
doc.documentElement = makeEl('html');
globalThis.document = doc;
globalThis.window = { innerWidth: 1440, innerHeight: 900, addEventListener() {}, removeEventListener() {} };

const trigger = makeEl('button');
trigger.dataset = {};
const panel = makeEl('div');
panel.id = 'dateRangePanel';
panel.hidden = true;
const month = makeEl('span');
const weekdays = makeEl('div');
const summary = makeEl('div');
const days = makeEl('div');

// innerHTML is how the module publishes the month: parse just enough of it back
// into buttons for the tests to click and read.
Object.defineProperty(days, 'innerHTML', {
  get() { return this._html || ''; },
  set(html) {
    this._html = html;
    this.children = [];
    const pattern = /<button type="button" class="([^"]*)" data-date="([^"]*)" tabindex="(-?\d+)" aria-pressed="([^"]*)"/g;
    for (const match of html.matchAll(pattern)) {
      const button = makeEl('button');
      button.className = match[1];
      button.dataset.date = match[2];
      button.tabIndex = Number(match[3]);
      button.attrs['aria-pressed'] = match[4];
      button.closest = (selector) => (selector.includes('[data-date]') ? button : null);
      this.children.push(button);
    }
  },
});
days.querySelectorAll = (selector) => (selector.includes('[data-date]') ? days.children : []);
days.querySelector = (selector) => {
  const match = /data-date="([^"]+)"/.exec(selector);
  return match ? days.children.find((button) => button.dataset.date === match[1]) || null : null;
};
days.contains = (node) => days.children.includes(node) || node === days;
// In the real DOM the grid, the head and the footer are the panel's descendants;
// the stub flattens them, so containment is spelled out. The popover asks it
// whether focus was inside before it decides to hand focus back to the trigger.
panel.contains = (node) => [days, month, weekdays, summary].includes(node)
  || days.children.includes(node);

const memo = {};
const control = makeEl('div');
const handles = {
  '[data-daterange-trigger]': trigger,
  '[data-daterange-panel]': panel,
  '[data-daterange-month]': month,
  '[data-daterange-weekdays]': weekdays,
  '[data-daterange-days]': days,
  '[data-daterange-summary]': summary,
};
control.querySelector = (selector) => (handles[selector] ||= makeEl('button'));
control.matches = (selector) => selector === '[data-date-range-control]';

// The app side: a range the picker previews, and the commit it hands it to.
let range = { start: new Date(2026, 2, 10), end: new Date(2026, 2, 10) };
const applied = [];
const closes = [];
const options = {
  lang: () => globalThis.__lang || 'en',
  summary: (start, end) => {
    const ymd = (date) => (date ? `${date.getFullYear()}.${date.getMonth() + 1}.${date.getDate()}` : '----.--.--');
    return `${ymd(start)}-${ymd(end)}`;
  },
  getRange: () => range,
  onRangeChange: (start, end) => { range = { start, end }; },
  // The app's own apply and reset both commit through the single range path,
  // which dismisses the picker: the panel is gone when the handler returns.
  onApply: () => {
    applied.push([range.start && range.start.toDateString(), range.end && range.end.toDateString()]);
    dismissDateRangePicker(control);
  },
  onReset: () => {
    applied.push('reset');
    dismissDateRangePicker(control);
  },
  onClose: () => closes.push(new Date().toISOString()),
};

const { mountDateRangeControl, syncDateRangePicker, dateRangePickerState, dismissDateRangePicker } =
  await import(process.argv[2]);

const report = {};
report.mounted = mountDateRangeControl(control, options);
report.remounted = mountDateRangeControl(control, options);
report.initial = dateRangePickerState(control);
report.monthLabel = month.textContent;
report.weekdayCells = (weekdays.innerHTML.match(/date-range-weekday/g) || []).length;
// Whole weeks: the grid reaches past the month on both sides instead of being
// clipped at its edges, so a range never looks like it stops at a month line.
report.keys = days.children.map((button) => button.dataset.date);
report.firstKey = report.keys[0];
report.lastKey = report.keys[report.keys.length - 1];

function clickDay(key) {
  const button = days.querySelector(`[data-date="${key}"]`);
  days.dispatch('click', { target: button, preventDefault() {} });
  return button;
}

// First pick sets the start, second sets the end, third starts over.
clickDay('2026-03-05');
report.focusAfterPick = doc.activeElement && doc.activeElement.dataset ? doc.activeElement.dataset.date : null;
report.afterFirstPick = dateRangePickerState(control);
clickDay('2026-03-12');
report.afterSecondPick = dateRangePickerState(control);
report.summaryText = summary.textContent;
clickDay('2026-03-20');
report.afterThirdPick = dateRangePickerState(control);

// Completing a window backwards keeps both picks and stores them in order.
clickDay('2026-03-02');
report.afterEarlierPick = dateRangePickerState(control);

// Apply hands the window to the app; reset asks for the preset back.
handles['[data-daterange-apply]'].dispatch('click');
// The panel took the focus with it when it closed, so the trigger must be
// holding it now rather than the document.
report.triggerFocusAfterApply = doc.activeElement === trigger;
handles['[data-daterange-reset]'].dispatch('click');
report.applied = applied;

// Keyboard: one roving tab stop, arrows walk it a day and a week at a time.
clickDay('2026-03-10');
const tabbable = () => ((days.children.find((button) => button.tabIndex === 0) || {}).dataset || {}).date;
const press = (key) => days.dispatch('keydown', { key, preventDefault() {}, altKey: false, ctrlKey: false, metaKey: false });
report.focusAfterClick = tabbable();
press('ArrowRight');
report.focusArrowRight = tabbable();
press('ArrowDown');
report.focusArrowDown = tabbable();
press('Home');
report.focusHome = tabbable();
press('End');
report.focusEnd = tabbable();
press('PageDown');
report.afterPageDown = dateRangePickerState(control);
report.focusPageDown = tabbable();
report.tabStops = days.children.filter((button) => button.tabIndex === 0).length;
report.dayCount = days.children.length;

// A language switch re-draws the labels the module owns.
globalThis.__lang = 'zh';
report.afterLanguage = syncDateRangePicker(control);
report.monthLabelZh = month.textContent;
globalThis.__lang = 'en';

// The panel is the popover primitive's: its own attributes come from the attach.
report.attached = {
  ariaControls: trigger.getAttribute('aria-controls'),
  ariaExpanded: trigger.getAttribute('aria-expanded'),
  panelPopover: panel.getAttribute('data-popover') || panel.dataset.popover,
};

// Escape closes through the primitive's document-level capture handler.
trigger.dispatch('click');
report.opened = dateRangePickerState(control);
const closesBeforeEscape = closes.length;
const escapeStatus = { key: 'Escape', stopPropagation() {} };
(listeners['doc:keydown'] || []).forEach((fn) => fn(escapeStatus));
report.afterEscape = dateRangePickerState(control);
report.closesFromEscape = closes.length - closesBeforeEscape;
report.panelHiddenAfterEscape = panel.hidden;
report.triggerFocusAfterEscape = doc.activeElement === trigger;

report.dismissed = dismissDateRangePicker(control);
// A closed panel records the month it will open on, not the one a half-finished
// pick left the grid showing.
report.closedMonth = report["dismissed"]["month"];
report.unmounted = {
  state: dateRangePickerState({ matches: () => false }),
  sync: syncDateRangePicker({ matches: () => false }),
  mount: mountDateRangeControl({ querySelector: () => null }),
};

process.stdout.write(JSON.stringify(report));
"""


@needs_node
def test_date_range_picker_behaviour(tmp_path: Path) -> None:
    harness = tmp_path / "picker.mjs"
    harness.write_text(_PICKER_DOM, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), PICKER_JS.as_uri()],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    report = json.loads(result.stdout)

    # One mount per control, six weeks always, and the range it was given.
    assert report["mounted"] == 1
    assert report["remounted"] == 1
    assert report["dayCount"] == 42, "six rows keep the panel's height steady"
    assert report["initial"]["month"] == "2026-03"
    assert report["initial"]["start"] == "2026-03-10"
    assert report["initial"]["end"] == "2026-03-10"
    assert report["weekdayCells"] == 7, "one header cell per column"
    # The grid starts on the locale's week boundary, runs 42 consecutive days and
    # therefore reaches into the neighbouring months on both sides.
    first = date.fromisoformat(report["firstKey"])
    last = date.fromisoformat(report["lastKey"])
    assert first.weekday() in (6, 0), f"must start on a week boundary, got {first}"
    assert (last - first).days == 41, "six whole weeks"
    # The whole month is drawn, and the grid reaches past its end rather than
    # stopping on the 31st. (Here the 1st is itself the week boundary, so the
    # grid opens on it; a month that starts mid-week opens in the previous one.)
    assert first <= date(2026, 3, 1) and last > date(2026, 3, 31)
    assert "2026-03-01" in report["keys"], "the month's own first day is drawn"
    assert "2026-03-31" in report["keys"], "so is its last"

    # First pick starts, second ends, third begins again.
    assert report["afterFirstPick"]["start"] == "2026-03-05"
    assert report["afterFirstPick"]["end"] == "2026-03-05"
    assert report["afterSecondPick"]["start"] == "2026-03-05"
    assert report["afterSecondPick"]["end"] == "2026-03-12"
    assert report["afterSecondPick"]["inRange"] == 6, "the span between is painted"
    assert report["summaryText"] == "2026.3.5-2026.3.12"
    assert report["afterThirdPick"]["start"] == "2026-03-20"
    assert report["afterThirdPick"]["end"] == "2026-03-20"

    # A second pick before the first completes the window in order: the later day
    # was chosen first, and the range is 02 → 20 rather than an inverted pair.
    assert report["afterEarlierPick"]["start"] == "2026-03-02"
    assert report["afterEarlierPick"]["end"] == "2026-03-20"
    assert report["afterEarlierPick"]["inRange"] > 0

    assert report["applied"][-1] == "reset", "the reset button asks the app for it"
    assert report["applied"][0] == ["Mon Mar 02 2026", "Fri Mar 20 2026"], (
        "Apply hands the picked window to the app's own commit path"
    )
    assert report["triggerFocusAfterApply"] is True, (
        "confirming closes the panel, so the trigger keeps the focus"
    )
    assert report["focusAfterPick"] == "2026-03-05", (
        "choosing a day leaves the keyboard on the calendar, not on the document"
    )

    # Keyboard: the roving stop moves a day, a week, and to its week's two ends.
    assert report["tabStops"] == 1, "one tab stop, not forty-two"
    assert report["focusArrowRight"] == "2026-03-11"
    assert (
        date.fromisoformat(report["focusArrowDown"])
        - date.fromisoformat(report["focusArrowRight"])
    ).days == 7
    assert date.fromisoformat(report["focusHome"]).weekday() in (6, 0), (
        "Home lands on the locale's week start"
    )
    assert (
        date.fromisoformat(report["focusEnd"])
        - date.fromisoformat(report["focusHome"])
    ).days == 6, "End lands on that week's last day"
    assert report["afterPageDown"]["month"] == "2026-04"
    assert report["focusPageDown"].startswith("2026-04")

    # A language switch re-draws what the module owns, not the app's range.
    assert report["afterLanguage"]["start"] == report["afterPageDown"]["start"]
    assert report["monthLabelZh"] != report["monthLabel"]

    # The panel belongs to the popover primitive, which also owns Escape.
    assert report["attached"]["ariaControls"] == "dateRangePanel"
    assert report["attached"]["panelPopover"] == "closed"
    assert report["opened"]["open"] is True
    assert report["afterEscape"]["open"] is False
    assert report["panelHiddenAfterEscape"] is True
    assert report["triggerFocusAfterEscape"] is True, "Escape returns focus to the trigger"
    assert report["closesFromEscape"] == 1, (
        "a close the primitive owns still settles the panel: the app is told"
    )
    assert report["afterEscape"]["month"] == "2026-03", (
        "and the grid settles on the month of the range it kept"
    )
    assert report["dismissed"]["open"] is False
    assert report["afterPageDown"]["month"] == "2026-04", "the open grid followed the keys"
    assert report["closedMonth"] == "2026-03", (
        "a closed panel reports the month of the range it holds"
    )

    assert report["unmounted"] == {"state": None, "sync": None, "mount": 0}


def test_picker_markup_carries_its_affordances() -> None:
    source = _source()
    panel = source[source.index('id="dateRangePanel"') :]
    panel = panel[: panel.index("</div>\n              </div>")]

    # One control with the presets beside it, opened from the trigger it belongs to.
    assert 'data-daterange-trigger' in source
    assert 'aria-haspopup="dialog"' in source
    assert 'data-daterange-panel' in source
    assert 'data-daterange-days' in panel
    assert 'data-daterange-summary' in panel
    assert 'data-daterange-apply' in panel
    assert 'data-daterange-reset' in panel
    assert 'aria-live="polite"' in panel

    # The arrows are icon-only, so each carries a real name and the committed hint.
    assert panel.count("data-daterange-prev") == 1
    assert panel.count("data-daterange-next") == 1
    assert 'data-i18n="previousMonth"' in panel
    assert 'data-i18n="nextMonth"' in panel
    assert 'data-tooltip' in panel
    assert 'data-i18n-title="previousMonth"' in panel
    assert 'data-i18n-title="nextMonth"' in panel

    # The reset returns to the Today preset rather than inventing a window.
    reset_start = panel.index("data-daterange-reset")
    assert 'data-i18n="today"' in panel[reset_start - 220 : reset_start + 220]
    assert 'data-i18n="apply"' in panel


def test_picker_labels_are_translated_everywhere() -> None:
    source = _source()
    for lang in LANGUAGES:
        block = source[source.index(f"      {lang}: {{") :]
        block = block[: block.index("\n      },") if "\n      }," in block else 40000]
        for key in ("previousMonth:", "nextMonth:"):
            assert key in block, f"{lang} is missing {key}"
    # The retired CDN key goes with the dependency.
    assert "cdnFlatpickrFailed" not in source


def test_picker_panel_uses_the_committed_vocabulary() -> None:
    css = _source()[: _source().index("</style>")]
    panel = css[css.index("    .date-range-panel {") :]
    panel = panel[: panel.index(".refresh-report-head")]

    # The same panel vocabulary the refresh report wears.
    assert "position: fixed;" in panel
    assert "z-index: 115;" in panel
    assert "border-radius: 16px;" in panel
    assert "var(--shadow-md)" in panel
    assert "backdrop-filter: blur(18px);" in panel
    assert "animation: refresh-report-in var(--t-fast) cubic-bezier(.16, 1, .3, 1);" in panel
    # And until the primitive places it, it anchors under its own control.
    assert ".date-range-panel:not([data-placement])" in panel
    assert "position: absolute;" in panel
    # The grid is the app's own calendar palette, not a new one.
    assert "var(--datepickr-panel-bg)" in panel
    assert "var(--datepickr-day-selected-bg)" in panel
    assert "var(--datepickr-day-range-bg)" in panel
    assert "var(--datepickr-day-today-bg)" in panel
    assert "var(--datepickr-weekday-fg)" in panel
    assert "var(--datepickr-footer-border)" in panel

    assert "export function mountDateRangeControl(" in PICKER_JS.read_text(encoding="utf-8")
