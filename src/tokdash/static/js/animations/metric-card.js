/**
 * TokDash v4 Animation System - Metric cards
 *
 * The same card, drawn by hand nine times in the Stats tab: a `.surface` with a
 * label and a value, sized by whichever utility classes that copy happened to
 * carry. Nothing owned the card, so the label colour drifted (hardcoded slate in
 * the Month Stats grid, the theme's label token in the row above it), the figures
 * landed at body size beside the KPI row's 30px numbers, and no card reserved a
 * line for its own value — a longer number pushed the card taller.
 *
 * `metric-card.js` owns the card as one surface: the label / value / meta rhythm,
 * the reserved value line, the tabular numerals that keep that line from moving
 * when a digit changes, and the hint chip that carries the detail a figure cannot
 * fit. It also owns *when* a value transitions: writers keep writing plain text
 * (so the tab is correct with no bundle loaded at all), and the render that just
 * finished calls `animateMetricValues`, which compares what each slot reads now
 * against what it read last. The moving itself belongs to `slot-text.js`.
 *
 * Markup contract: `data-metric-card` marks a card, `.metric-card-value` is the
 * slot whose text is the figure, `data-value-kind="text"` sizes a non-numeric
 * value (a model name) down to what it needs, and `data-variant="bare"` drops the
 * surface for cells that live inside a panel which is already one.
 *
 * The value slot is marked by its class, not by its card: `.metric-card-value`
 * carries the reserved line, the tabular numerals and the transitions, so a figure
 * that stands on its own can adopt the slot without a card around it. The Overview
 * KPI row keeps its own count-up (`animateOverviewCounter`), which is why nothing
 * else claims its values here — two animations on one figure is worse than one.
 */

import { mountTooltips } from './tooltip.js';
import { renderSlotText, slotTextState } from './slot-text.js';
import { renderCountedValue, countablePair, figureSeparators } from './animated-counter.js';

const HINT_SELECTOR = '[data-tooltip]';
// A value element this module has seen, and the text it currently stands for.
const seenValues = new WeakMap();

/** The card's value slot. One per card: the figure the card exists to show. */
export function metricValueElement(card) {
  if (!card) return null;
  return card.matches?.('.metric-card-value') ? card : card.querySelector('.metric-card-value');
}

/** The hint chip a card uses to explain itself, if it has one. */
export function metricHintElement(card) {
  if (!card) return null;
  return card.querySelector(HINT_SELECTOR);
}

/** Every value slot under `root`, in document order. */
export function metricValueElements(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return [];
  return [...root.querySelectorAll('.metric-card-value')];
}

/**
 * Hand every value that changed since the last call to a renderer.
 *
 * Called by the render that just wrote the figures, never by a timer: a writer
 * that sets `textContent` leaves a figure that is already correct, and this only
 * decides whether the change to it should be seen as a change. The first text an
 * element is ever seen with is adopted silently — the tab paints figures for the
 * first time when it opens, and a card that rolls up from zero every time it is
 * looked at is noise, not information.
 *
 * Which renderer runs is decided by the figure, not by the card: a quantity that
 * kept its unit and its shape counts up or down, because the travel is the news;
 * a figure that changed kind — a ratio, a date, a model name, a window that moved
 * from one month to another — morphs instead, because there is no travel between
 * two unrelated readings. `options.format` is the app's number formatter: it
 * renders the counting frames and says how the figure's separators are read.
 */
export function animateMetricValues(root = document, options = {}) {
  const values = metricValueElements(root);
  const format = typeof options.format === 'function' ? options.format : null;
  const separators = options.separators || figureSeparators(format);
  let morphed = 0;
  let counted = 0;
  values.forEach((element) => {
    const text = element.textContent;
    const previous = seenValues.get(element);
    if (previous == null) {
      // First sight of this slot: adopt what it says without animating it.
      seenValues.set(element, { text });
      return;
    }
    if (previous.text === text) return;
    // The element already holds the new text — the writer put it there — so the
    // figure to move away from is the one this module saw last.
    const countable = countablePair(previous.text, text, separators);
    const rendered = countable
      ? renderCountedValue(element, text, { from: previous.text, format, separators })
      : renderSlotText(element, text, { from: previous.text });
    previous.text = text;
    if (!rendered) return;
    if (countable) counted += 1;
    else morphed += 1;
  });
  return { values: values.length, morphed, counted, changed: morphed + counted };
}

/** One value slot's state: what it is showing and whether it is mid-morph. */
export function metricValueState(element) {
  if (!element) return null;
  const seen = seenValues.get(element);
  return { last: seen ? seen.text : null, ...slotTextState(element) };
}

/**
 * Mount every `[data-metric-card]` under `root`.
 *
 * Mounting is idempotent and non-destructive: a card already mounted keeps its
 * attachment, and a card whose hints are already covered by `mountTooltips`
 * keeps that one too, because `attachTooltip` returns the existing entry rather
 * than stacking a second set of listeners on the trigger.
 */
export function mountMetricCards(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return 0;
  let count = 0;
  root.querySelectorAll('[data-metric-card]').forEach((card) => {
    if (card.dataset.metricCard === 'ready') return;
    card.dataset.metricCard = 'ready';
    // A card mounted after the page-wide tooltip pass still gets its own hint
    // wired; mounting is idempotent, so this cannot double-attach a trigger.
    if (metricHintElement(card)) mountTooltips(card);
    count += 1;
  });
  return count;
}

/**
 * Where the value slot currently is, and what is in it.
 *
 * Card state as data rather than as a DOM read by the caller: sidebar counts,
 * tests and the value renderers all need the same few facts (is there a slot,
 * is it still a loading placeholder, what does it read right now), and each of
 * them re-deriving those from class lists is how the states drift apart.
 */
export function metricCardState(card) {
  if (!card || !card.matches?.('[data-metric-card]')) return null;
  const value = metricValueElement(card);
  const hint = metricHintElement(card);
  return {
    id: value?.id || '',
    label: card.querySelector('.metric-card-label')?.textContent?.trim() || '',
    value: value ? value.textContent.trim() : null,
    valueKind: card.dataset.valueKind || 'number',
    variant: card.dataset.variant || 'card',
    hint: hint ? hint.dataset.tooltipText || hint.getAttribute('title') || '' : '',
  };
}

/** Every mounted card's state, in document order. Exposed for tests. */
export function metricCardsState(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return [];
  return [...root.querySelectorAll('[data-metric-card]')].map((card) => metricCardState(card));
}
