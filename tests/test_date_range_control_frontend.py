from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import tokdash  # type: ignore[import-untyped]

INDEX_HTML = Path(tokdash.__file__).parent / "static" / "index.html"


def _extract_js_function(source: str, signature: str) -> str:
    start = source.find(signature)
    assert start != -1, f"{signature} not found in index.html"
    body_start = start + len(signature) - 1
    assert source[body_start] == "{", f"{signature} must end at the function body"
    depth = 0
    for index in range(body_start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated JavaScript function: {signature}")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_date_range_trigger_text_is_localized_and_deterministic(
    tmp_path: Path,
) -> None:
    source = INDEX_HTML.read_text(encoding="utf-8")
    functions = "\n".join(
        _extract_js_function(source, signature)
        for signature in (
            "function sameLocalDate(left, right) {",
            "function formatDateRangeDate(date, lang = currentLang) {",
            "function formatDateRangeTriggerText(startDate, endDate, lang = currentLang) {",
        )
    )
    harness = tmp_path / "date-range-control.js"
    harness.write_text(
        "const LANG_LOCALES = { en: 'en-US', zh: 'zh-CN', ja: 'ja-JP', ko: 'ko-KR', es: 'es-ES', pt: 'pt-BR' };\n"
        "function langLocale(lang) { return LANG_LOCALES[lang] || 'en-US'; }\n"
        + functions
        + "\nconst cases = JSON.parse(process.argv[2]);\n"
        + "const result = cases.map(({ start, end, lang }) => "
        + "formatDateRangeTriggerText(new Date(`${start}T12:00:00`), new Date(`${end}T12:00:00`), lang));\n"
        + "process.stdout.write(JSON.stringify(result));\n",
        encoding="utf-8",
    )
    cases = [
        {"start": "2026-08-10", "end": "2026-08-10", "lang": "en"},
        {"start": "2026-08-03", "end": "2026-08-09", "lang": "en"},
        {"start": "2026-08-10", "end": "2026-08-10", "lang": "zh"},
        {"start": "2026-08-03", "end": "2026-08-09", "lang": "zh"},
        {"start": "2026-08-10", "end": "2026-08-10", "lang": "ja"},
        {"start": "2026-08-03", "end": "2026-08-09", "lang": "ko"},
        {"start": "2026-08-10", "end": "2026-08-10", "lang": "es"},
        {"start": "2026-08-10", "end": "2026-08-10", "lang": "pt"},
    ]
    result = subprocess.run(
        ["node", str(harness), json.dumps(cases)],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert json.loads(result.stdout) == [
        "Aug 10, 2026",
        "Aug 3, 2026 – Aug 9, 2026",
        "2026年8月10日",
        "2026年8月3日 – 2026年8月9日",
        "2026年8月10日",
        "2026년 8월 3일 – 2026년 8월 9일",
        "10 ago 2026",
        "10 de ago. de 2026",
    ]


def test_date_range_trigger_markup_and_localization_contract() -> None:
    source = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="dateRangeTrigger"' in source
    assert 'id="dateRangePresetLabel"' in source
    assert 'id="dateRangeExactLabel"' in source
    assert 'class="date-range-calendar-icon"' in source
    assert 'class="date-range-chevron"' in source
    assert 'aria-haspopup="dialog"' in source
    assert source.count("customRange: '") == 6
    assert source.count("selectRange: '") == 6


def test_range_switcher_shows_every_preset_without_a_disclosure() -> None:
    source = INDEX_HTML.read_text(encoding="utf-8")
    rail_start = source.index('<div class="topbar-control-rail">')
    quick_start = source.index("<!-- Range switcher: every preset is a segment")
    actions_start = source.index('<div class="topbar-actions">')
    tabs_start = source.index("<!-- Tabs -->")
    quick_markup = source[quick_start:actions_start]
    quick_css_start = source.index("    .quick-range-panel {")
    quick_css_end = source.index("    .topbar-actions {")
    quick_css = source[quick_css_start:quick_css_end]

    assert rail_start < quick_start < actions_start < tabs_start
    # Every preset is a segment of the one control, in one learned order.
    assert quick_markup.count('class="range-switcher-segment"') == 10
    assert quick_markup.index('data-range="today"') < quick_markup.index('data-range="last14days"')
    assert quick_markup.index('data-range="last14days"') < quick_markup.index('data-range="lastYear"')
    # The disclosure is gone outright: no toggle, no menu, no i18n key left
    # on the markup for a second control to grow behind.
    assert 'id="quickRangeMoreToggle"' not in quick_markup
    assert 'id="quickRangeMoreMenu"' not in quick_markup
    assert 'data-i18n="moreRanges"' not in quick_markup
    assert 'data-range-switcher' in quick_markup
    assert 'aria-labelledby="dateRangeControlLabel"' in quick_markup
    # Without the bundle the row is still a complete working toolbar.
    assert "display: flex;" in source
    assert "flex-wrap: wrap;" in quick_css
    assert "overflow: visible;" in quick_css
    assert "overflow-x: auto;" not in quick_css
    # The switcher's visual layer: an absolutely-placed pill under the
    # segments, sliding on the shared token clock, never scrolling.
    assert ".range-switcher-indicator {" in quick_css
    assert "position: absolute;" in quick_css
    assert "--t-med" in quick_css
    assert "z-index: 1;" in quick_css
    assert "position: relative;" in quick_css
    # Report chips stay plain: they wrap and carry no pill padding.
    assert "#reportPeriodChips { flex-wrap: wrap; padding: 0; }" in source
    # The slide belongs to the module, mounted by the init block - the app
    # markup carries only the static, already-working control.
    module = (
        Path(tokdash.__file__).parent / "static" / "js" / "animations" / "range-switcher.js"
    ).read_text(encoding="utf-8")
    assert "export function mountRangeSwitcher(" in module
    assert "export function syncRangeSwitcher(" in module
    assert "export function rangeSwitcherState(" in module
    assert "Animations.mountRangeSwitcher(document.getElementById('overviewQuickRanges'));" in source


def test_date_range_state_sync_does_not_fetch() -> None:
    source = INDEX_HTML.read_text(encoding="utf-8")
    sync = _extract_js_function(source, "function syncDateRangeControl() {")
    commit = _extract_js_function(
        source,
        "function commitDateSelection(startDate, endDate, options = {}) {",
    )
    i18n = _extract_js_function(source, "function applyI18n() {")

    assert "activeQuickRange || 'customRange'" in sync
    assert "formatDateRangeTriggerText(currentStartDate, currentEndDate)" in sync
    assert "document.querySelectorAll('.range-switcher-segment').forEach((segment) => {" in sync
    assert "segment.setAttribute('aria-pressed', String(segment.dataset.range === activeQuickRange));" in sync
    assert "animations.syncRangeSwitcher(document.getElementById('overviewQuickRanges'));" in sync
    assert "moreRanges" not in sync
    # The trigger always says what it does: the picker is the app's own now, so
    # there is no CDN failure branch left to carry a reason for.
    assert "trigger.setAttribute('title', t('selectRange'));" in sync
    # An open panel follows the same commit the trigger just took, so a preset
    # moves the calendar with it instead of leaving it on a stale selection.
    assert "animations.syncDateRangePicker(pickerControl);" in sync
    assert "fetch(" not in sync
    assert "updateDashboard" not in sync
    assert "rangeKey = null" in commit
    assert "activeQuickRange = rangeKey;" in commit
    assert "syncDateRangeControl();" in commit
    assert "syncDateRangeControl();" in i18n


def test_date_range_open_and_commit_contract() -> None:
    """The trigger opens an app-drawn panel, and every way out of it commits
    through the same call the presets use."""
    source = INDEX_HTML.read_text(encoding="utf-8")
    picker = _extract_js_function(source, "function initDateRangePicker() {")

    # The rail's control hands the panel to the module, which presents it through
    # the committed popover primitive: the panel is the popover's, not a dialog
    # of the picker's own.
    assert "mountDateRangeControl(dateControl, {" in picker
    assert 'id="dateRangePanel"' in source
    assert 'class="date-range-panel"' in source
    assert 'data-daterange-trigger' in source
    assert 'data-daterange-panel' in source
    assert 'aria-haspopup="dialog"' in source

    # Confirm applies the pending window; reset returns to the Today preset
    # rather than to a window of its own invention.
    assert "onApply: () => applyPendingDateSelection()" in picker
    assert "commitDateSelection(today, today, { closePicker: true, rangeKey: 'today' })" in picker
    assert "getRange: () => ({ start: pendingStartDate, end: pendingEndDate })" in picker
    # Closing without confirming drops the half-picked window instead of keeping it.
    assert "pendingStartDate = cloneDate(currentStartDate);" in picker
    assert "getDisplayRangeText(startDate, endDate)" in picker

    # Without the bundle the trigger is still a disclosure of the same panel, and
    # the summary is the app's own formatter either way.
    assert "panel.hidden = isOpen;" in picker
    assert "dateControl.dataset.dateRangeMode === 'module'" in picker
    assert "window.tokdashInitDateRangePicker = initDateRangePicker;" in source
    assert "window.tokdashInitDateRangePicker();" in source

    # The presets keep committing themselves with their own range key.
    assert "rangeKey: range" in source
    assert "let activeQuickRange = 'today';" in source
    assert "flatpickr" not in source
