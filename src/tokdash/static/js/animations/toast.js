/**
 * TokDash v4 Animation System - Toasts
 *
 * Brief confirmations for work that finished somewhere other than under the
 * user's cursor. The refresh control reports its outcome on the button itself,
 * but the durable detail (what changed, how many tools, why rows were kept)
 * belongs in a message that can outlive the two-second button flash — and that
 * still gets delivered when the user has since clicked to another tab.
 *
 * One region, one stack. A newer toast never silently evicts an older unread
 * one: the stack is capped, and the oldest is retired through the same exit
 * animation a manual dismissal uses.
 */

import { respectsReducedMotion } from './reduced-motion.js';

const REGION_ID = 'tokdashToastRegion';
const MAX_VISIBLE = 3;
// Enough to read a sentence and decide, short of becoming furniture.
const DEFAULT_DURATION_MS = 5200;

function ensureRegion(doc = document) {
  let region = doc.getElementById(REGION_ID);
  if (region) return region;
  region = doc.createElement('div');
  region.id = REGION_ID;
  region.className = 'toast-region';
  // Polite, not assertive: these confirm background work and must never
  // interrupt a screen reader mid-sentence. Errors are still announced because
  // the region is atomic per toast.
  region.setAttribute('role', 'status');
  region.setAttribute('aria-live', 'polite');
  region.setAttribute('aria-atomic', 'false');
  (doc.body || doc.documentElement).appendChild(region);
  return region;
}

const ICONS = {
  info: '<path d="m7 12 3 3 7-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  warn: '<path d="M12 8v5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="16.5" r="1.1" fill="currentColor"/>',
  error: '<path d="M12 8v5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="16.5" r="1.1" fill="currentColor"/>',
};

const timers = new WeakMap();

function clearToastTimer(toast) {
  const timer = timers.get(toast);
  if (timer) {
    clearTimeout(timer);
    timers.delete(toast);
  }
}

/**
 * Retire a toast through its exit animation. `immediate` skips straight to
 * removal for teardown paths (a language switch rebuilding the stack).
 */
export function dismissToast(toast, { immediate = false } = {}) {
  if (!toast || !toast.parentNode) return;
  clearToastTimer(toast);
  if (immediate || respectsReducedMotion()) {
    toast.remove();
    return;
  }
  toast.dataset.leaving = 'true';
  setTimeout(() => toast.remove(), 200);
}

export function clearToasts({ immediate = true } = {}) {
  const region = document.getElementById(REGION_ID);
  if (!region) return;
  Array.from(region.children).forEach((toast) => dismissToast(toast, { immediate }));
}

function enforceCap(region) {
  const live = Array.from(region.children).filter((toast) => toast.dataset.leaving !== 'true');
  while (live.length > MAX_VISIBLE) {
    dismissToast(live.shift());
  }
}

function buildIcon(tone) {
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">${ICONS[tone] || ICONS.info}</svg>`;
}

/**
 * Show a toast.
 *
 * @param {object} options
 * @param {string} options.title   Headline. Required; a toast with no title is a bug.
 * @param {string} [options.meta]  One line of supporting detail.
 * @param {'info'|'warn'|'error'} [options.tone]
 * @param {number} [options.duration]  ms on screen; 0 keeps it until dismissed.
 * @param {Array<{label: string, onClick: Function}>} [options.actions]
 * @param {string} [options.closeLabel]  Accessible name for the dismiss button.
 * @returns {HTMLElement|null} the toast node
 */
export function showToast({
  title,
  meta = '',
  tone = 'info',
  duration = DEFAULT_DURATION_MS,
  actions = [],
  closeLabel = 'Dismiss',
} = {}) {
  if (!title || typeof document === 'undefined') return null;
  const region = ensureRegion();
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.dataset.tone = tone;

  const mark = document.createElement('span');
  mark.className = 'toast-mark';
  mark.innerHTML = buildIcon(tone);

  const body = document.createElement('div');
  body.className = 'toast-body';
  const heading = document.createElement('p');
  heading.className = 'toast-title';
  heading.textContent = title;
  body.appendChild(heading);
  if (meta) {
    const note = document.createElement('p');
    note.className = 'toast-meta';
    note.textContent = meta;
    body.appendChild(note);
  }
  if (actions.length) {
    const row = document.createElement('div');
    row.className = 'toast-actions';
    actions.forEach((action) => {
      if (!action || !action.label) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'toast-action';
      button.textContent = action.label;
      button.addEventListener('click', () => {
        try {
          if (typeof action.onClick === 'function') action.onClick();
        } finally {
          dismissToast(toast);
        }
      });
      row.appendChild(button);
    });
    body.appendChild(row);
  }

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';
  close.setAttribute('aria-label', closeLabel);
  close.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
  close.addEventListener('click', () => dismissToast(toast));

  toast.append(mark, body, close);

  // A visible countdown, driven by the same duration the timer uses so the two
  // cannot disagree. Reduced motion keeps the bar but holds it still.
  if (duration > 0) {
    const progress = document.createElement('span');
    progress.className = 'toast-progress';
    progress.setAttribute('aria-hidden', 'true');
    if (!respectsReducedMotion() && typeof progress.animate === 'function') {
      progress.animate(
        [{ transform: 'scaleX(1)' }, { transform: 'scaleX(0)' }],
        { duration, easing: 'linear', fill: 'forwards' },
      );
    }
    toast.appendChild(progress);
  }

  region.appendChild(toast);
  enforceCap(region);

  if (duration > 0) {
    // Hovering pauses the countdown: a toast that vanishes mid-read is worse
    // than one that lingers.
    const arm = () => {
      timers.set(toast, setTimeout(() => dismissToast(toast), duration));
    };
    toast.addEventListener('mouseenter', () => clearToastTimer(toast));
    toast.addEventListener('mouseleave', arm);
    toast.addEventListener('focusin', () => clearToastTimer(toast));
    arm();
  }

  return toast;
}

export default { showToast, dismissToast, clearToasts };
