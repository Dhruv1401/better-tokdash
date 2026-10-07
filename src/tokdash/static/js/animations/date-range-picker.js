/**
 * TokDash v4 Animation System - Date range picker
 *
 * The rail could pick a preset but not a window of its own: the calendar behind
 * the trigger came from a CDN, so its layout, its colours and its keyboard
 * behaviour belonged to a library, and when that CDN was unreachable the whole
 * control was switched off — the trigger even carried a "picker unavailable"
 * title. On a dashboard whose every number is a date range, that is the one
 * control a user must always be able to reach.
 *
 * This is that calendar as the app's own. A month grid drawn in the committed
 * calendar palette (the same --datepickr-* tokens the old panel was themed
 * with), a range selection that marks its two endpoints and the span between
 * them, and keys that walk it a day, a week or a month at a time. It owns the
 * grid and nothing else: the app still owns the range, the commit path and the
 * fetch, so a picked window travels exactly the route a preset travels.
 *
 * The panel is presented by the popover primitive — placement, outside click,
 * Escape, focus return — and never by this module. Without the bundle the
 * trigger reveals the panel in place instead, which is why the panel's own CSS
 * anchors it under the control until the primitive marks it as placed.
 */

import { attachPopover, closePopover, openPopover, popoverFor, repositionPopover } from './popover.js';

const states = new WeakMap();
// Six rows always, so a month that needs five does not resize the panel under
// the pointer that is using it, and the popover never has to be re-placed
// mid-selection.
const GRID_ROWS = 6;
const WEEK_DAYS = 7;

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

function addMonths(date, months) {
  return new Date(date.getFullYear(), date.getMonth() + months, 1);
}

function isSameDay(left, right) {
  if (!left || !right) return false;
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate();
}

/** Day granularity: the picker never compares times of day. */
function isBefore(left, right) {
  return startOfDay(left).getTime() < startOfDay(right).getTime();
}

function dayKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

/** The first day of the week containing `date`, honouring the caller's week start. */
function startOfWeek(date, weekStart) {
  const day = startOfDay(date).getDay();
  const back = (day - weekStart + WEEK_DAYS) % WEEK_DAYS;
  return addDays(date, -back);
}

/** The six rows of days a month grid draws, including the neighbouring days. */
function monthGrid(month, weekStart) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const cursor = startOfWeek(first, weekStart);
  const days = [];
  for (let index = 0; index < GRID_ROWS * WEEK_DAYS; index += 1) {
    days.push(addDays(cursor, index));
  }
  return days;
}

function localeFor(lang) {
  return {
    en: 'en-US', zh: 'zh-CN', ja: 'ja-JP', ko: 'ko-KR', es: 'es-ES', pt: 'pt-BR',
  }[lang] || 'en-US';
}

/**
 * Who owns the first column: the locale knows, and a browser too old to say
 * gets Monday — which is what the rest of the app's calendars use.
 */
function weekStartFor(lang) {
  try {
    const info = new Intl.Locale(localeFor(lang)).weekInfo || new Intl.Locale(localeFor(lang)).getWeekInfo?.();
    if (info && typeof info.firstDay === 'number') return info.firstDay % WEEK_DAYS;
  } catch (err) { /* no week info: Monday-first */ }
  return 1;
}

function dayLabelFor(date, lang) {
  try {
    return new Intl.DateTimeFormat(localeFor(lang), { dateStyle: 'full' }).format(date);
  } catch (err) {
    return dayKey(date);
  }
}

function monthLabelFor(date, lang) {
  try {
    return new Intl.DateTimeFormat(localeFor(lang), { month: 'long', year: 'numeric' }).format(date);
  } catch (err) {
    return dayKey(date);
  }
}

function weekdayLabelFor(index, lang) {
  // 2024-01-07 was a Sunday, so index 0 addresses Sunday in every locale.
  const reference = new Date(2024, 0, 7 + index);
  try {
    return new Intl.DateTimeFormat(localeFor(lang), { weekday: 'narrow' }).format(reference);
  } catch (err) {
    return '';
  }
}

function rangeOf(state) {
  const range = state.options.getRange?.() || {};
  return { start: range.start || null, end: range.end || null };
}

/** The span the grid paints: a single endpoint still reads as a one-day range. */
function span(state) {
  const { start, end } = rangeOf(state);
  if (start && end) return isBefore(end, start) ? { start: end, end: start } : { start, end };
  if (start) return { start, end: start };
  if (end) return { start: end, end };
  return { start: null, end: null };
}

function elementFor(control, selector) {
  return control.querySelector(selector);
}

function paintSummary(state) {
  const { start, end } = rangeOf(state);
  const summary = state.parts.summary;
  if (!summary) return;
  summary.textContent = state.options.summary ? state.options.summary(start, end) : '';
}

/**
 * Draw the panel: head, weekday row and the day grid.
 *
 * `focusKey` is the day the roving tab stop sits on. Only one day is tabbable,
 * so a keyboard user lands on the calendar rather than on 42 tab stops, and the
 * two grid keys that mean "move" move the stop rather than replace it.
 */
function render(state) {
  const { parts, options } = state;
  const lang = options.lang?.() || 'en';
  const weekStart = state.weekStart;
  const today = startOfDay(new Date());
  const selected = span(state);
  const active = state.focusDate || selected.start || today;

  if (parts.month) parts.month.textContent = monthLabelFor(state.month, lang);

  if (parts.weekdays) {
    const labels = [];
    for (let index = 0; index < WEEK_DAYS; index += 1) {
      labels.push(`<span class="date-range-weekday" aria-hidden="true">${weekdayLabelFor((weekStart + index) % WEEK_DAYS, lang)}</span>`);
    }
    parts.weekdays.innerHTML = labels.join('');
  }

  if (!parts.days) return;
  const days = monthGrid(state.month, weekStart);
  const cells = days.map((date) => {
    const classNames = ['date-range-day'];
    if (date.getMonth() !== state.month.getMonth()) classNames.push('is-outside');
    if (isSameDay(date, today)) classNames.push('is-today');
    if (selected.start && isSameDay(date, selected.start)) classNames.push('is-start');
    if (selected.end && isSameDay(date, selected.end)) classNames.push('is-end');
    if (selected.start && selected.end
      && !isBefore(date, selected.start) && !isBefore(selected.end, date)
      && !isSameDay(date, selected.start) && !isSameDay(date, selected.end)) {
      classNames.push('is-in-range');
    }
    const isSelected = (selected.start && isSameDay(date, selected.start))
      || (selected.end && isSameDay(date, selected.end));
    const tabbable = isSameDay(date, active);
    return `<button type="button" class="${classNames.join(' ')}"`
      + ` data-date="${dayKey(date)}"`
      + ` tabindex="${tabbable ? '0' : '-1'}"`
      // aria-pressed, not aria-selected: the day is a real button, and a
      // selection state on a button role is the one the platform defines for it.
      + ` aria-pressed="${isSelected ? 'true' : 'false'}"`
      + (isSameDay(date, today) ? ' aria-current="date"' : '')
      + ` aria-label="${dayLabelFor(date, lang)}">${date.getDate()}</button>`;
  });
  parts.days.innerHTML = cells.join('');
  state.renderedFocusKey = dayKey(active);
}

/** Re-focus the roving tab stop after a re-render replaced the buttons. */
function restoreGridFocus(state) {
  const { parts } = state;
  if (!parts.days) return;
  const target = parts.days.querySelector(`[data-date="${state.renderedFocusKey}"]`);
  if (target) target.focus();
}

function dateFromKey(key) {
  const [year, month, day] = String(key).split('-').map(Number);
  return new Date(year, (month || 1) - 1, day || 1);
}

function isEmptyRange(start, end) {
  return !start && !end;
}

/**
 * Take a click (or a key) on one day and move the range to it.
 *
 * The first pick sets the start, the second sets the end, and a third begins
 * again — so a range that is already complete never silently grows when the
 * user meant to start over. A second pick *before* the first still completes
 * the range: the two days are stored in order, so choosing the later day first
 * is a way to pick a window, not a mistake to undo.
 */
function pickDay(state, date) {
  const day = startOfDay(date);
  const { start, end } = rangeOf(state);
  let nextStart;
  let nextEnd;
  if (!start || end) {
    nextStart = day;
    nextEnd = null;
  } else if (isSameDay(day, start)) {
    nextStart = day;
    nextEnd = day;
  } else if (isBefore(day, start)) {
    nextStart = day;
    nextEnd = start;
  } else {
    nextStart = start;
    nextEnd = day;
  }
  state.focusDate = day;
  if (day.getMonth() !== state.month.getMonth()) state.month = new Date(day.getFullYear(), day.getMonth(), 1);
  state.options.onRangeChange?.(nextStart, nextEnd);
  render(state);
  // The footer previews the window being built, so it is repainted with it
  // rather than only when the panel opens or the app re-syncs.
  paintSummary(state);
  // Re-rendering replaces every button, so the picked day is focused again: a
  // key chosen with the keyboard keeps the keyboard on the calendar instead of
  // dropping it on the document.
  restoreGridFocus(state);
}

function moveGridFocus(state, days) {
  const base = state.focusDate || span(state).start || startOfDay(new Date());
  const target = addDays(base, days);
  state.focusDate = target;
  if (target.getMonth() !== state.month.getMonth()) {
    state.month = new Date(target.getFullYear(), target.getMonth(), 1);
  }
  render(state);
  restoreGridFocus(state);
}

function onGridKeydown(state, event) {
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  const moves = {
    ArrowLeft: -1,
    ArrowRight: 1,
    ArrowUp: -WEEK_DAYS,
    ArrowDown: WEEK_DAYS,
  };
  if (event.key in moves) {
    event.preventDefault();
    moveGridFocus(state, moves[event.key]);
    return;
  }
  if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault();
    const weekStart = startOfWeek(state.focusDate || startOfDay(new Date()), state.weekStart);
    state.focusDate = event.key === 'Home' ? weekStart : addDays(weekStart, WEEK_DAYS - 1);
    render(state);
    restoreGridFocus(state);
    return;
  }
  if (event.key === 'PageUp' || event.key === 'PageDown') {
    event.preventDefault();
    const base = state.focusDate || startOfDay(new Date());
    const step = event.key === 'PageUp' ? -1 : 1;
    const target = new Date(base.getFullYear(), base.getMonth() + step, Math.min(base.getDate(), 28));
    state.focusDate = target;
    state.month = new Date(target.getFullYear(), target.getMonth(), 1);
    render(state);
    restoreGridFocus(state);
  }
}

function onGridClick(state, event) {
  const button = event.target.closest?.('[data-date]');
  if (!button || !state.parts.days?.contains(button)) return;
  pickDay(state, dateFromKey(button.dataset.date));
}

/** Open the panel under the trigger, with focus inside the calendar. */
function show(state) {
  const { panel, trigger } = state.parts;
  // The app seeds the window it is about to show before the panel paints, so the
  // first frame already carries the selection rather than an empty grid that
  // fills in a moment later.
  state.options.onOpen?.();
  state.month = (() => {
    const { start } = span(state);
    const anchor = start || startOfDay(new Date());
    return new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  })();
  state.focusDate = span(state).start || startOfDay(new Date());
  render(state);
  paintSummary(state);
  if (state.handle) {
    openPopover(state.handle);
    // The trigger owns the panel's lifetime, so the primitive's placement runs
    // first and focus lands on the day itself rather than on a nav arrow.
    restoreGridFocus(state);
  } else {
    panel.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    restoreGridFocus(state);
  }
}

/**
 * Everything a panel does as it goes away.
 *
 * The app resets the window it was previewing, and the grid settles on the month
 * that holds the range rather than keeping the month a half-finished pick
 * wandered into — so a closed panel reports the place the next open will show.
 */
function settleClosed(state) {
  state.options.onClose?.();
  const { start } = span(state);
  if (start) state.month = new Date(start.getFullYear(), start.getMonth(), 1);
}

function hide(state, { restoreFocus = false } = {}) {
  const { panel, trigger } = state.parts;
  if (state.handle) {
    // The primitive reports the close through the handle's own onClose, so this
    // path and the ones it owns (Escape, an outside click, a scroll) settle the
    // panel exactly once, the same way.
    closePopover({ restoreFocus }, state.handle);
    return;
  }
  panel.hidden = true;
  trigger.setAttribute('aria-expanded', 'false');
  if (restoreFocus) trigger.focus();
  settleClosed(state);
}

/**
 * A footer action is a confirmation: the app commits the window and closes the
 * panel with it, so the focus the panel was holding has to land somewhere. It
 * goes back to the trigger, which is the control that owns the panel — never to
 * the document, where the next Tab would restart at the top of the page.
 */
function returnFocusIfClosed(state) {
  if (partsOpen(state)) return;
  const { trigger } = state.parts;
  if (trigger && typeof trigger.focus === 'function') trigger.focus();
}

/**
 * Mount the control: one trigger, one panel, one grid.
 *
 * Idempotent. The panel is bound to the trigger through the popover primitive
 * when the bundle is there, and kept as an in-place disclosure when it is not,
 * so the trigger can always open the calendar it advertises.
 */
export function mountDateRangeControl(control, options = {}) {
  if (!control || typeof control.querySelector !== 'function') return 0;
  if (states.has(control)) {
    syncDateRangePicker(control);
    return 1;
  }

  const parts = {
    trigger: elementFor(control, '[data-daterange-trigger]'),
    panel: elementFor(control, '[data-daterange-panel]'),
    month: elementFor(control, '[data-daterange-month]'),
    weekdays: elementFor(control, '[data-daterange-weekdays]'),
    days: elementFor(control, '[data-daterange-days]'),
    summary: elementFor(control, '[data-daterange-summary]'),
  };
  if (!parts.trigger || !parts.panel) return 0;

  const state = {
    control,
    parts,
    options,
    weekStart: Number.isInteger(options.weekStart) ? options.weekStart : weekStartFor(options.lang?.() || 'en'),
    month: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
    focusDate: startOfDay(new Date()),
    handle: null,
    renderedFocusKey: '',
  };
  states.set(control, state);

  try {
    state.handle = attachPopover(parts.trigger, parts.panel, {
      align: 'start',
      // Whoever closes the panel — this module's own dismiss, the primitive's
      // Escape, an outside click — the panel settles the same way.
      onClose: () => settleClosed(state),
    });
  } catch (err) { /* the panel stays an in-place disclosure */ }

  parts.trigger.addEventListener('click', () => {
    const isOpen = state.handle
      ? popoverFor(parts.panel) && parts.panel.dataset.popover === 'open'
      : !parts.panel.hidden;
    if (isOpen) hide(state);
    else show(state);
  });

  control.querySelector('[data-daterange-prev]')?.addEventListener('click', () => {
    state.month = addMonths(state.month, -1);
    state.focusDate = new Date(state.month.getFullYear(), state.month.getMonth(), 1);
    render(state);
  });
  control.querySelector('[data-daterange-next]')?.addEventListener('click', () => {
    state.month = addMonths(state.month, 1);
    state.focusDate = new Date(state.month.getFullYear(), state.month.getMonth(), 1);
    render(state);
  });
  control.querySelector('[data-daterange-apply]')?.addEventListener('click', () => {
    state.options.onApply?.();
    returnFocusIfClosed(state);
  });
  control.querySelector('[data-daterange-reset]')?.addEventListener('click', () => {
    state.options.onReset?.();
    returnFocusIfClosed(state);
  });

  parts.days?.addEventListener('click', (event) => onGridClick(state, event));
  parts.days?.addEventListener('keydown', (event) => onGridKeydown(state, event));

  state.month = new Date(state.focusDate.getFullYear(), state.focusDate.getMonth(), 1);
  render(state);
  paintSummary(state);
  return 1;
}

/**
 * Re-draw from the app's current range and language.
 *
 * The app calls this wherever it used to re-sync a picker it owned: a range
 * commit, a preset click, a language switch. It never fetches anything itself —
 * the panel is a view of the range, not a second source of it.
 */
export function syncDateRangePicker(control) {
  const state = states.get(control);
  if (!state) return null;
  state.weekStart = Number.isInteger(state.options.weekStart)
    ? state.options.weekStart
    : weekStartFor(state.options.lang?.() || 'en');
  if (!partsOpen(state)) {
    const { start } = span(state);
    if (start) state.month = new Date(start.getFullYear(), start.getMonth(), 1);
  }
  render(state);
  paintSummary(state);
  if (state.handle && state.parts.panel.dataset.popover === 'open') repositionPopover(state.handle);
  return dateRangePickerState(control);
}

function partsOpen(state) {
  return state.handle ? state.parts.panel.dataset.popover === 'open' : !state.parts.panel.hidden;
}

/** Whether the picker is up, which month it shows, and what it has selected. */
export function dateRangePickerState(control) {
  const state = states.get(control);
  if (!state) return null;
  const selected = span(state);
  const days = state.parts.days ? [...state.parts.days.querySelectorAll('[data-date]')] : [];
  return {
    ready: true,
    open: partsOpen(state),
    month: `${state.month.getFullYear()}-${String(state.month.getMonth() + 1).padStart(2, '0')}`,
    start: selected.start ? dayKey(selected.start) : null,
    end: selected.end ? dayKey(selected.end) : null,
    days: days.length,
    inRange: days.filter((day) => day.className.includes('is-in-range')).length,
    tabbable: days.filter((day) => day.tabIndex === 0).length,
    empty: isEmptyRange(selected.start, selected.end),
  };
}

/** Close an open panel. Used by surfaces that rebuild under it. */
export function dismissDateRangePicker(control) {
  const state = states.get(control);
  if (!state) return null;
  hide(state);
  return dateRangePickerState(control);
}
