"""Contract and behaviour tests for the Sessions Explorer search field.

The field is the app's own input wearing two added affordances: a leading mark
that says what the box does, and a clear control that keeps a reserved slot so
the toolbar never re-measures when it appears. These tests keep that split
honest — the markup stays the app's filter path (the inline handler and
`filterSessionsBySearch`), and the module only ever re-dispatches the same
`input` event a keystroke sends.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import tokdash

STATIC = Path(tokdash.__file__).parent / "static"
INDEX_HTML = STATIC / "index.html"
SEARCH_FIELD_JS = STATIC / "js" / "animations" / "search-field.js"
ANIMATIONS_INDEX = STATIC / "js" / "animations" / "index.js"
LANGUAGES = ("en", "zh", "ja", "ko", "es", "pt")

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available"
)


def _source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _css_block(source: str, selector: str) -> str:
    """Slice one complete CSS block, braces balanced."""
    start = source.index(selector)
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated CSS block: {selector}")


# A DOM stub with only what the module touches: attributes, dataset, listeners
# and the two lookups the module performs. `dispatchEvent` routes back through
# the same listener list as typing does, so the harness sees the field's own
# re-dispatched event exactly as the app's inline handler would.
_SEARCH_FIELD_DOM = r"""
const el = (tag, attrs = {}) => ({
  tagName: tag,
  attrs: { ...attrs },
  dataset: {},
  value: '',
  tabIndex: 0,
  focused: false,
  listeners: {},
  setAttribute(name, value) { this.attrs[name] = String(value); },
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  },
  removeAttribute(name) { delete this.attrs[name]; },
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); },
  addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
  dispatch(type, event = {}) { (this.listeners[type] || []).forEach((h) => h(event)); },
  focus() { this.focused = true; },
});

const field = el('div');
const input = el('input');
const clear = el('button', { 'aria-hidden': 'true' });
clear.tabIndex = -1;

// The app's single filter path: the input keeps its own inline handler, and the
// harness records every query that handler is handed.
const filteredWith = [];
input.addEventListener('input', () => filteredWith.push(input.value));
input.dispatchEvent = (event) => { input.dispatch(event.type, event); return true; };

field.querySelector = (selector) => {
  if (selector === '.search-field-input') return input;
  if (selector === '[data-search-field-clear]') return clear;
  return null;
};
field.matches = (selector) => selector === '[data-search-field]';

const root = { querySelectorAll: (s) => (s === '[data-search-field]' ? [field] : []) };

const { mountSearchFields, searchFieldState } = await import(process.argv[2]);

const report = { mounted: mountSearchFields(root) };
report.initial = searchFieldState(field);

input.value = 'codex';
input.dispatch('input');
report.typed = searchFieldState(field);
report.typedAttrs = { ariaHidden: clear.getAttribute('aria-hidden'), tabIndex: clear.tabIndex };

clear.dispatch('click');
report.cleared = searchFieldState(field);
report.clearedAttrs = { ariaHidden: clear.getAttribute('aria-hidden'), tabIndex: clear.tabIndex };
report.focusReturned = input.focused;

// Escape is the keyboard's way out, and only acts on a query that exists.
input.focused = false;
input.dispatch('keydown', { key: 'Escape' });
const emptyEscape = searchFieldState(field);
input.value = 'claude';
input.dispatch('input');
input.dispatch('keydown', { key: 'Escape' });
const filledEscape = searchFieldState(field);

// A second mount must not double-bind, and clearing an already-empty box must
// not re-run the app's filter over every row.
const secondMount = mountSearchFields(root);
const beforeRedundantClear = filteredWith.length;
clear.dispatch('click');
report.redundantClearAdded = filteredWith.length - beforeRedundantClear;
input.value = 'pi';
input.dispatch('input');
clear.dispatch('click');

report.appFilterSaw = filteredWith;
report.emptyEscape = emptyEscape;
report.filledEscape = filledEscape;
report.secondMount = secondMount;
report.unmounted = {
  nullField: searchFieldState(null),
  plainObject: searchFieldState({ matches: (s) => s !== '[data-search-field]' }),
  emptyRoot: mountSearchFields({}),
};

// A field that was never mounted still reports its own value honestly.
const lone = el('div');
const loneInput = el('input');
loneInput.value = 'adhoc';
lone.querySelector = (s) => (s === '.search-field-input' ? loneInput : null);
lone.matches = (s) => s === '[data-search-field]';
report.lone = searchFieldState(lone);

process.stdout.write(JSON.stringify(report));
"""


@needs_node
def test_search_field_behaviour_report(tmp_path: Path) -> None:
    harness = tmp_path / "search-field.mjs"
    harness.write_text(_SEARCH_FIELD_DOM, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), SEARCH_FIELD_JS.as_uri()],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    report = json.loads(result.stdout)

    assert report["mounted"] == 1
    assert report["initial"] == {
        "ready": True,
        "query": "",
        "hasQuery": False,
        "clearVisible": False,
        "clearTabIndex": -1,
        "focused": False,
    }

    # Typing only makes the way out appear; the query itself is the app's.
    assert report["typed"]["hasQuery"] is True
    assert report["typed"]["clearVisible"] is True
    assert report["typedAttrs"] == {"ariaHidden": None, "tabIndex": 0}

    # Clearing empties the box, withdraws the control and hands focus back to
    # the input — through the app's own filter path, with the empty query.
    assert report["cleared"]["query"] == ""
    assert report["cleared"]["hasQuery"] is False
    assert report["cleared"]["clearVisible"] is False
    assert report["clearedAttrs"] == {"ariaHidden": "true", "tabIndex": -1}
    assert report["focusReturned"] is True

    # Escape on an empty box touches nothing; on a query it is the way out.
    assert report["emptyEscape"]["hasQuery"] is False
    assert report["filledEscape"]["query"] == ""
    assert report["filledEscape"]["hasQuery"] is False

    # One binding per mount: no duplicate filter calls after a second mount,
    # and an empty box costs the table nothing when the control is pressed.
    assert report["secondMount"] == 1
    assert report["redundantClearAdded"] == 0
    assert report["appFilterSaw"] == ["codex", "", "claude", "", "pi", ""]

    assert report["unmounted"] == {"nullField": None, "plainObject": None, "emptyRoot": 0}
    assert report["lone"]["ready"] is False
    assert report["lone"]["query"] == "adhoc"
    assert report["lone"]["hasQuery"] is True


def test_markup_keeps_the_apps_filter_path_and_adds_the_affordances() -> None:
    source = _source()
    field = source[
        source.index('<div class="search-field" id="sessionSearchField"') :
    ]
    field = field[: field.index("</div>")]

    # The id, the class that carries a theme's surface, and the app's own
    # handler all stay — this is the same box, not a replacement filter.
    assert 'id="sessionSearchInput"' in field
    assert "ui-input" in field
    assert "oninput=\"filterSessionsBySearch(this.value)\"" in field

    # A real label tied to the input, hidden by its own rule so it survives a
    # CDN failure, and a leading mark that is decoration only.
    assert 'for="sessionSearchInput"' in field
    assert 'class="search-field-label"' in field
    assert "sr-only" not in field
    assert 'class="search-field-icon"' in field
    icon = field[field.index("search-field-icon") :]
    assert 'aria-hidden="true"' in icon[:80]

    # The way out starts withdrawn: no tab stop, nothing announced.
    clear = field[field.index("search-field-clear") :]
    assert 'data-search-field-clear' in clear
    assert 'aria-hidden="true"' in clear
    assert 'tabindex="-1"' in clear

    # Search is the field's own type, and its own autocomplete is off.
    assert 'type="search"' in field
    assert 'autocomplete="off"' in field


def test_placeholder_and_label_are_translated() -> None:
    source = _source()
    assert 'data-i18n-placeholder="sessionsSearchPlaceholder"' in source
    assert 'data-i18n="sessionsSearchLabel"' in source
    assert 'data-i18n-title="sessionsSearchClear"' in source
    # The clear control's accessible name cannot ride on data-i18n (its mark is
    # decoration), so applyI18n sets it the way it labels the release-notes close.
    apply_body = source[source.index("function applyI18n()") :]
    apply_body = apply_body[: apply_body.index("\n    }\n")]
    assert "sessionSearchClear.setAttribute('aria-label', t('sessionsSearchClear'))" in apply_body

    for lang in LANGUAGES:
        block = source[
            source.index(f"      {lang}: {{") : source.index(f"      {lang}: {{") + 40000
        ]
        for key in (
            "sessionsSearchLabel:",
            "sessionsSearchPlaceholder:",
            "sessionsSearchClear:",
        ):
            assert key in block, f"{lang} is missing {key}"


def test_css_reserves_the_slot_and_drops_motion_on_request() -> None:
    source = _source()
    css = source[: source.index("</style>")]

    # The control is absolutely placed, so its arrival never moves the field.
    assert re.search(r"\.search-field-clear \{[^}]*position: absolute;", css)
    assert re.search(r"\.search-field-clear \{[^}]*pointer-events: none;", css)
    assert re.search(
        r'\.search-field\[data-has-query="true"\] \.search-field-clear \{[^}]*pointer-events: auto;',
        css,
    )
    # The field's own surface stays .ui-input's, so every theme keeps styling it.
    assert re.search(r"\.search-field-input \{[^}]*padding-left: 35px;", css)
    assert re.search(r"\.search-field-input \{[^}]*padding-right: 35px;", css)
    # Both native clear affordances are withdrawn; ours owns the slot.
    assert "::-webkit-search-cancel-button" in css
    assert re.search(r"::-webkit-search-cancel-button,\s*\.search-field-input::-webkit-search-decoration", css)

    # The field's own reduced-motion block, not the earlier one further up.
    field_css = css[css.index("Search field: the app's own input vocabulary") :]
    reduced = _css_block(field_css, "@media (prefers-reduced-motion: reduce)")
    assert ".search-field-clear" in reduced
    assert "filter: none !important;" in reduced
    assert "transform: translateY(var(--search-lift)) !important;" in reduced

    # The mark follows the input's own focus lift, so it stays welded on focus.
    assert "--search-lift: -1px" in css
    assert "transform: translateY(var(--search-lift));" in css


def test_module_entry_exports_and_mounts_the_field() -> None:
    assert "export * from './search-field.js';" in ANIMATIONS_INDEX.read_text(
        encoding="utf-8"
    )
    source = _source()
    assert "Animations.mountSearchFields(document);" in source
    # The module never filters for itself: one path, and it is the app's.
    module = SEARCH_FIELD_JS.read_text(encoding="utf-8")
    assert "filterSessionsBySearch" not in module
    assert "input.dispatchEvent(new Event('input', { bubbles: true }));" in module
