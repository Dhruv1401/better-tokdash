/**
 * TokDash v4 Animation System - Announcement Bar
 *
 * The dashboard already knows when an update arrives: the update-check calls
 * `renderUpdateBadge(info)` with `update_available` true and a version, and the
 * settings panel paints its own badge. That badge is buried inside the settings
 * dialog — a thing you only see if you go looking for it. An arrival that lives
 * that deep is not an announcement, it is a secret.
 *
 * This module promotes that one real signal to the top of the app surface. It
 * wraps the app's own `renderUpdateBadge` (the exact function the network check
 * invokes) and, when it fires with a genuine `update_available`, reveals an
 * inline bar above the top bar carrying the very message the settings badge just
 * painted — the real, already-localized text, never a paraphrase and never an
 * invented feed. It invents nothing: without an update the bar stays collapsed.
 *
 * Space is a grid that animates between 0fr and 1fr, so the bar grows out of a
 * zero-height slot and the neighbours below reflow as one smooth block instead
 * of jumping; when empty the slot contributes no height at all, so the layout is
 * identical whether or not an announcement exists. Dismissing remembers the
 * version (its own key, independent of the settings badge's skip), so the same
 * arrival never nags twice. The bar appears without taking focus, announces
 * politely through a live region, and yields the keyboard untouched.
 *
 * Fallback contract: with no `#announcementBar` in the host, mounting is a no-op
 * and the settings badge keeps working exactly as before.
 */

import { respectsReducedMotion } from './reduced-motion.js';

const SLOT_ID = 'announcementBar';
// The same key the settings update badge honours ("skip this version"): a top
// bar must not re-surface an update the user already told the app to skip.
const SKIP_KEY = 'tokdash-update-skipped';
// The bar's own memory, so a dismissed announcement stays dismissed for that
// version across reloads without leaning on the settings badge's flag.
const DISMISS_KEY = 'tokdash-announcement-dismissed';

const states = new WeakMap();
let appSlot = null;

function translate(key, fallback) {
  try {
    if (typeof window !== 'undefined' && typeof window.t === 'function') {
      const value = window.t(key);
      if (value && value !== key) return value;
    }
  } catch (_) { /* no translator in this host: the fallback stands */ }
  return fallback;
}

function setSlotState(slot, shown) {
  slot.dataset.state = shown ? 'shown' : 'empty';
}

function cardOf(slot) {
  return slot.querySelector('.announcement-card');
}

// The slot is a fixed clip that animates an explicit pixel height, measured off
// the card. That reflow is exact in both directions and, unlike an `fr` grid track
// in an auto-height container, the collapse reliably settles to zero.
function expand(slot) {
  const card = cardOf(slot);
  const target = card ? card.offsetHeight : 0;
  if (!target) { slot.style.height = '0px'; return; }
  if (respectsReducedMotion()) { slot.style.height = 'auto'; return; }
  slot.style.height = '0px';
  void slot.offsetHeight; // reflow, so the 0 -> target transition has a start
  slot.style.height = `${target}px`;
  const onEnd = (event) => {
    if (event.propertyName !== 'height') return;
    slot.removeEventListener('transitionend', onEnd);
    slot.style.height = 'auto'; // adapt to later content/language changes
  };
  slot.addEventListener('transitionend', onEnd);
}

function collapse(slot) {
  if (respectsReducedMotion()) { slot.style.height = '0px'; return; }
  const from = slot.offsetHeight;
  if (!from) { slot.style.height = '0px'; return; }
  slot.style.height = `${from}px`;
  void slot.offsetHeight;
  slot.style.height = '0px';
  const onEnd = (event) => {
    if (event.propertyName !== 'height') return;
    slot.removeEventListener('transitionend', onEnd);
    slot.style.height = '0px';
  };
  slot.addEventListener('transitionend', onEnd);
}

/**
 * The message is read straight off the settings badge the app just painted, so
 * the bar speaks in the app's own localized words. Only if that badge is empty
 * (a host without the settings markup) does the bar compose its own.
 */
function messageFor(latest) {
  let badge = null;
  try { badge = document.getElementById('updateBadge'); } catch (_) { /* no DOM */ }
  const painted = badge && badge.textContent;
  if (painted) return painted;
  return `${translate('updateAvailable', 'Update available')}: v${latest}`;
}

function show(slot, message, version) {
  const wasShown = slot.dataset.state === 'shown';
  const text = slot.querySelector('.announcement-text');
  if (text) text.textContent = message || '';
  const state = states.get(slot);
  if (state) {
    state.shown = true;
    state.version = version || null;
  }
  setSlotState(slot, true);
  // A bar already on screen just swaps its message; only a fresh reveal animates.
  if (!wasShown) expand(slot);
}

function hide(slot, { remembered = false } = {}) {
  const state = states.get(slot);
  const version = state && state.version;
  if (remembered && version) {
    try { localStorage.setItem(DISMISS_KEY, version); } catch (_) { /* blocked storage */ }
  }
  setSlotState(slot, false);
  const text = slot.querySelector('.announcement-text');
  if (text) text.textContent = '';
  if (state) {
    state.shown = false;
    state.version = null;
  }
  collapse(slot);
}

/**
 * Wrap the app's real update signal exactly once. The wrapper runs the app's
 * own `renderUpdateBadge` untouched first (the settings badge still paints), then
 * — only for a genuine `update_available` — reveals the bar. Any throw in the
 * bar is swallowed so it can never break the update flow it is announcing.
 */
function wrapUpdateSignal() {
  if (typeof window === 'undefined') return;
  const original = window.renderUpdateBadge;
  if (typeof original !== 'function' || original.__tokdashAnnouncement) return;
  const wrapper = function (info) {
    const result = original.apply(this, arguments);
    try {
      announceUpdate(info);
    } catch (_) { /* the announcement must never break the badge it mirrors */ }
    return result;
  };
  wrapper.__tokdashAnnouncement = true;
  window.renderUpdateBadge = wrapper;
}

/**
 * Present an update arrival, honouring both the settings badge's skip and the
 * bar's own dismiss memory. Returns true when the bar actually revealed.
 *
 * @param {object} info  the payload the app's update-check produced
 * @param {boolean} [info.update_available]
 * @param {string|number} [info.latest]
 * @param {object} [options]
 * @param {boolean} [options.force]  bypass the skip/dismiss guards (tests, programmatic re-show)
 */
export function announceUpdate(info, { force = false } = {}) {
  if (!appSlot || !info || !info.update_available || !info.latest) return false;
  const latest = String(info.latest);
  if (!force) {
    try {
      if (localStorage.getItem(SKIP_KEY) === latest) return false;
      if (localStorage.getItem(DISMISS_KEY) === latest) return false;
    } catch (_) { /* blocked storage: a failed read is not consent to hide */ }
  }
  show(appSlot, messageFor(latest), latest);
  return true;
}

/**
 * Collapse the bar. `remembered` persists the current version so the same
 * arrival does not return on the next load.
 */
export function hideAnnouncement({ remembered = false } = {}) {
  if (!appSlot) return false;
  if (appSlot.dataset.state !== 'shown') return false;
  hide(appSlot, { remembered });
  return true;
}

/** The bar as data. */
export function announcementState() {
  if (!appSlot) return null;
  const state = states.get(appSlot);
  const text = appSlot.querySelector('.announcement-text');
  return {
    mounted: state != null,
    shown: appSlot.dataset.state === 'shown',
    version: (state && state.version) || null,
    message: (text && text.textContent) || '',
  };
}

/**
 * Claim the static `#announcementBar` slot, wire its dismiss and detail
 * actions, and hook the app's real update signal. Idempotent: a second mount
 * returns the existing state and never double-wraps the signal.
 *
 * @param {Document|Element} root
 * @returns {object|null} the bar's state, or null when the host has no slot
 */
export function mountAnnouncementBar(root = document) {
  if (!root || typeof root.getElementById !== 'function') return null;
  const slot = root.getElementById(SLOT_ID);
  if (!slot) return null;
  const existing = states.get(slot);
  if (existing) return existing;

  const action = slot.querySelector('.announcement-action');
  const close = slot.querySelector('.announcement-close');

  // Dismiss is a plain button: the user's gesture owns focus, the bar itself
  // never reaches for it on reveal.
  if (close) {
    close.addEventListener('click', () => hide(slot, { remembered: true }));
  }

  // "Details" hands off to the real release-notes dialog — the app's own
  // what's-new surface — rather than inventing a second one.
  if (action) {
    action.addEventListener('click', () => {
      let host = null;
      try { host = document.getElementById('releaseNotesToggle'); } catch (_) { /* no DOM */ }
      if (host) host.click();
    });
  }

  const state = { slot, shown: false, version: null };
  states.set(slot, state);
  appSlot = slot;
  setSlotState(slot, slot.dataset.state === 'shown');

  wrapUpdateSignal();
  return state;
}

export default {
  mountAnnouncementBar,
  announceUpdate,
  hideAnnouncement,
  announcementState,
};
