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
 * fit. The value's *transition* — morphing a changed string, counting a changed
 * number — is deliberately not here; that is `slot-text.js` and
 * `animated-counter.js`, which this module hands the value slots to.
 *
 * Markup contract: `data-metric-card` marks a card, `.metric-card-value` is the
 * slot whose text is the figure, `data-value-kind="text"` sizes a non-numeric
 * value (a model name) down to what it needs, and `data-variant="bare"` drops the
 * surface for cells that live inside a panel which is already one.
 */

import { mountTooltips } from './tooltip.js';

const HINT_SELECTOR = '[data-tooltip]';

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
