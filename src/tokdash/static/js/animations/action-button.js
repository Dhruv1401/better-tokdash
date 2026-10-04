/**
 * TokDash v4 Animation System - Action Button
 *
 * The refresh control changes its own label as it moves through idle, pending
 * and acknowledged states ("Refresh" -> "Refreshing…" -> "Updated"). Written
 * naively that is an innerHTML swap, and the toolbar jumps by whatever the two
 * labels differ in width while the text snaps between them.
 *
 * This module keeps the icon in place and morphs only the text: layers are
 * stacked in one grid cell, the outgoing one blurs upward while the incoming
 * one rises into place, and the wrapper's width springs from the old label's
 * measured width to the new one's. Per-character spans stagger the incoming
 * text so a longer label resolves left to right instead of appearing at once.
 *
 * Everything is measurement-driven rather than hard-coded, because the same
 * control has to survive six languages whose labels differ wildly in length.
 */

import { respectsReducedMotion } from './reduced-motion.js';

// Keep in step with --t-fast / --t-med and the keyframes in index.html. The
// width spring has to outlast the incoming layer's fade or the label would be
// clipped mid-morph.
const LEAVE_MS = 180;
const ENTER_MS = 240;
const CHAR_STAGGER_MS = 16;
// Long labels are not worth one span per character; past this the stagger is
// invisible anyway and the node count only costs layout.
const MAX_STAGGER_CHARS = 14;

function isElement(node) {
  return !!node && typeof node === 'object' && node.nodeType === 1;
}

function labelWrapper(button) {
  if (!isElement(button)) return null;
  let wrapper = button.querySelector('.action-btn-label');
  if (wrapper) return wrapper;
  wrapper = document.createElement('span');
  wrapper.className = 'action-btn-label';
  button.appendChild(wrapper);
  return wrapper;
}

function currentLayer(wrapper) {
  return wrapper ? wrapper.querySelector('.action-btn-label-layer[data-active="true"]') : null;
}

// Layers are short-lived but the render paths are not: renderRefreshButton runs
// on every state change and every i18n pass, and each pass that saw a changed
// label used to leave its superseded layer in the DOM. The stack then grew
// without bound and the wrapper measured the sum of every label it had ever
// shown. Keep exactly the active layer and the one morphing in.
function purgeStaleLayers(wrapper, keep) {
  if (!wrapper) return;
  Array.from(wrapper.children).forEach((layer) => {
    if (layer !== keep && layer.dataset.active !== 'true') layer.remove();
  });
}

// A layer is a single line of text; splitting it into spans is what lets the
// characters rise individually. Whitespace is preserved as a plain text node so
// the label still wraps and spaces the way it did before.
function fillLayer(layer, text, { stagger }) {
  layer.replaceChildren();
  const label = String(text == null ? '' : text);
  if (!stagger || label.length > MAX_STAGGER_CHARS) {
    layer.textContent = label;
    return;
  }
  Array.from(label).forEach((char, index) => {
    if (char === ' ') {
      layer.appendChild(document.createTextNode(' '));
      return;
    }
    const span = document.createElement('span');
    span.textContent = char;
    span.style.display = 'inline-block';
    span.style.animation = `action-btn-char-in var(--t-med) cubic-bezier(.16, 1, .3, 1) both`;
    span.style.animationDelay = `${index * CHAR_STAGGER_MS}ms`;
    layer.appendChild(span);
  });
}

function makeLayer(wrapper, text, { active = false, stagger = true } = {}) {
  const layer = document.createElement('span');
  layer.className = 'action-btn-label-layer';
  layer.dataset.active = active ? 'true' : 'false';
  fillLayer(layer, text, { stagger });
  wrapper.appendChild(layer);
  return layer;
}

function measuredWidth(layer) {
  if (!isElement(layer)) return 0;
  const rect = layer.getBoundingClientRect ? layer.getBoundingClientRect() : null;
  return Math.max(0, Math.ceil((rect && rect.width) || layer.offsetWidth || 0));
}

/**
 * Give `button` its label stack if it does not have one yet, seeded with the
 * text already inside it so the first paint never flickers.
 */
export function mountActionButton(button, initialLabel) {
  const wrapper = labelWrapper(button);
  if (!wrapper) return null;
  if (!currentLayer(wrapper)) {
    const text = initialLabel != null
      ? initialLabel
      : (button.textContent || '').trim();
    const layer = makeLayer(wrapper, text, { active: true, stagger: false });
    wrapper.style.width = `${measuredWidth(layer)}px`;
  }
  return wrapper;
}

/**
 * Morph the button's label to `text`. A no-op when it already reads `text`, so
 * the many re-render paths that call this on every i18n pass do not re-animate
 * a label that did not change.
 */
export function setActionButtonLabel(button, text, { tone } = {}) {
  if (!isElement(button)) return;
  if (tone !== undefined) setActionButtonTone(button, tone);
  const wrapper = mountActionButton(button, text);
  if (!wrapper) return;

  const label = String(text == null ? '' : text);
  const active = currentLayer(wrapper);
  if (active && active.textContent === label) return;
  // Already morphing towards this exact label: a second pass must not stack a
  // duplicate layer on top of the one that is still animating in.
  if (wrapper.__incoming && wrapper.__incoming.textContent === label) return;

  const reduced = respectsReducedMotion();
  purgeStaleLayers(wrapper, active);
  const from = active ? measuredWidth(active) : 0;
  const incoming = makeLayer(wrapper, label, { stagger: !reduced });
  // Marked active immediately, so currentLayer() finds the newest label from
  // this point on and a repeat call short-circuits above instead of adding
  // another layer to the stack.
  incoming.dataset.active = 'true';
  wrapper.__incoming = incoming;

  // Freeze the spring at the outgoing width, force a layout read so the browser
  // has a resolved starting value, then release it to the new measurement. The
  // read is what makes this synchronous and deterministic: the previous version
  // deferred the second write to requestAnimationFrame, and rAF does not fire
  // in a background tab, so a refresh finishing while the tab was hidden left
  // every layer it had ever shown stacked in the wrapper.
  wrapper.style.width = `${from}px`;
  void wrapper.offsetWidth;
  const target = measuredWidth(incoming);
  wrapper.style.width = `${target}px`;
  wrapper.__incoming = null;

  if (active) {
    active.dataset.active = 'false';
    if (reduced) {
      active.remove();
      wrapper.style.width = '';
    } else {
      active.dataset.leaving = 'true';
      setTimeout(() => {
        active.remove();
        // Hand the wrapper back to its content so a later font or language
        // change cannot leave a stale pixel width behind.
        if (wrapper.__incoming == null) wrapper.style.width = '';
      }, LEAVE_MS);
    }
  } else {
    wrapper.style.width = '';
  }
}

export function setActionButtonTone(button, tone) {
  if (!isElement(button)) return;
  if (tone) button.dataset.tone = String(tone);
  else delete button.dataset.tone;
}

/**
 * Busy is the spinner state; disabled is the click-swallowing state. They are
 * separate on purpose: a cooldown is disabled but not busy, and the button must
 * keep focus through both, so neither uses the native disabled attribute.
 */
export function setActionButtonBusy(button, busy) {
  if (!isElement(button)) return;
  if (busy) button.setAttribute('aria-busy', 'true');
  else button.removeAttribute('aria-busy');
  button.dataset.busy = busy ? 'true' : 'false';
}

export function setActionButtonDisabled(button, disabled) {
  if (!isElement(button)) return;
  // aria-disabled rather than disabled: the button keeps keyboard focus through
  // the refresh, which is the whole point of showing pending on the control.
  if (disabled) button.setAttribute('aria-disabled', 'true');
  else button.removeAttribute('aria-disabled');
}

/** True while the control should swallow activation. */
export function actionButtonIsBlocked(button) {
  return !!isElement(button) && button.getAttribute('aria-disabled') === 'true';
}

export default {
  mountActionButton,
  setActionButtonLabel,
  setActionButtonTone,
  setActionButtonBusy,
  setActionButtonDisabled,
  actionButtonIsBlocked,
};
